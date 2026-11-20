"""Loopback-only HTTP API and built frontend; no framework dependency."""

from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, unquote, urlsplit

from .accounts import SESSION_DAYS, AccountStore, validate_credentials
from .health import ROOT, health
from .jobs import JOB_ID, JobRunner, JobStore, RequestError, validate_request

MAX_BODY = 16_384
SESSION_COOKIE = "traversaal_session"


def byte_range(value, size):
    """Return one inclusive HTTP byte range, rejecting invalid/multipart ranges."""
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if match is None or size <= 0:
        raise ValueError("Invalid byte range")
    left, right = match.groups()
    if not left and not right:
        raise ValueError("Empty byte range")
    if not left:
        count = int(right)
        if count <= 0:
            raise ValueError("Invalid suffix range")
        return max(0, size - count), size - 1
    start, end = int(left), min(int(right), size - 1) if right else size - 1
    if start >= size or start > end:
        raise ValueError("Unsatisfiable byte range")
    return start, end


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address=("127.0.0.1", 8000), *, root=ROOT, store=None, runner=None, readiness=None,
                 accounts=None):
        if address[0] != "127.0.0.1":
            raise ValueError("The development server must bind to 127.0.0.1.")
        self.root = Path(root).resolve()
        self.readiness = readiness or (lambda: health(self.root))
        self.runner = runner
        super().__init__(address, Handler)
        try:
            # Binding first prevents a second launch on this port from interrupting live jobs.
            self.store = store or JobStore(self.root / "runs/web")
            self.accounts = accounts or AccountStore(self.root / "runs/web/accounts.sqlite3")
            self.runner = runner or JobRunner(self.store, self.root)
        except Exception:
            self.server_close()
            raise

    def server_close(self):
        if self.runner is not None:
            self.runner.close()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    server_version = "CapstoneLocal/1.0"

    def log_message(self, format, *args):
        # Avoid writing user prompts, credentials, or arbitrary request paths to the terminal.
        pass

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def _json(self, status, value, session=None):
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if session is not None:
            # HttpOnly keeps the token away from page scripts; Strict blocks it on cross-site requests.
            # An empty token clears the cookie. Add Secure when this is served over HTTPS.
            age = SESSION_DAYS * 86400 if session else 0
            self.send_header("Set-Cookie", f"{SESSION_COOKIE}={session}; Max-Age={age}; Path=/; HttpOnly; SameSite=Strict")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _error(self, status, code, message):
        self._json(status, {"error": {"code": code, "message": message}})

    def _local_request(self):
        hosts = self.headers.get_all("Host", [])
        port = self.server.server_address[1]
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        # Vite forwards requests to this local server. No remote hostname is accepted.
        allowed_hosts.update({"127.0.0.1:5173", "localhost:5173"})
        if len(hosts) != 1 or hosts[0].lower() not in allowed_hosts:
            self._error(403, "invalid_host", "Use the local server address.")
            return False
        origins = self.headers.get_all("Origin", [])
        allowed_origins = {f"http://{host}" for host in allowed_hosts}
        if len(origins) > 1 or origins and origins[0] not in allowed_origins:
            self._error(403, "invalid_origin", "Requests must come from the local Capstone website.")
            return False
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            self._error(403, "cross_site_request", "Cross-site requests are not allowed.")
            return False
        return True

    def _session_token(self):
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel is not None else None

    def _user(self):
        """Return the signed-in account, or send 401 and return None."""
        user = self.server.accounts.session_user(self._session_token())
        if user is None:
            self._error(401, "not_signed_in", "Sign in to use the studio.")
        return user

    def _read_json(self):
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
            raise RequestError("Send one Content-Length header with the JSON request.", "invalid_body")
        length = int(lengths[0])
        if not 0 < length <= MAX_BODY:
            raise RequestError("The JSON request must be smaller than 16 KB.", "body_too_large", 413)
        if self.headers.get_content_type() != "application/json":
            raise RequestError("Use Content-Type: application/json.", "unsupported_media_type", 415)
        self.connection.settimeout(10)
        data = self.rfile.read(length)
        if len(data) != length:
            raise RequestError("The request body is incomplete.", "invalid_json")
        try:
            return json.loads(data)
        except (ValueError, UnicodeDecodeError):
            raise RequestError("The request body is not valid JSON.", "invalid_json") from None

    def do_POST(self):
        if not self._local_request():
            return
        path = urlsplit(self.path).path
        routes = {"/api/jobs": self._create_job, "/api/auth/register": self._register,
                  "/api/auth/login": self._login, "/api/auth/logout": self._logout}
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "resume" and JOB_ID.fullmatch(parts[2]):
            routes[path] = lambda: self._resume_job(parts[2])
        if path not in routes:
            self._error(404, "not_found", "API route not found.")
            return
        try:
            routes[path]()
        except RequestError as exc:
            self._error(exc.status, exc.code, str(exc))
        except (ValueError, TimeoutError):
            self._error(400, "invalid_body", "The request body could not be read.")
        except (OSError, sqlite3.Error):
            self._error(500, "storage_error", "Could not save your data. Check local disk space and permissions.")

    def _register(self):
        username, password = validate_credentials(self._read_json())
        user = self.server.accounts.register(username, password)
        self._json(201, {"user": user}, session=self.server.accounts.create_session(user["id"]))

    def _login(self):
        username, password = validate_credentials(self._read_json())
        user = self.server.accounts.authenticate(username, password)
        if user is None:
            raise RequestError("The username or password is incorrect.", "invalid_credentials", 401)
        self._json(200, {"user": user}, session=self.server.accounts.create_session(user["id"]))

    def _logout(self):
        self.server.accounts.end_session(self._session_token())
        self._json(200, {"user": None}, session="")

    def _create_job(self):
        user = self._user()
        if user is None:
            return
        try:
            request = validate_request(self._read_json())
            readiness = self.server.readiness()
            ready = readiness["sampleReady"] if request["source"] == "sample" else readiness["liveReady"]
            if request["visualMode"] == "seedance":
                ready = readiness.get("seedanceSampleReady" if request["source"] == "sample" else "seedanceReady", False)
            if not ready:
                excluded = {"tts_cache", "claude_sdk", "claude_key"} if request["source"] == "sample" else {"tts_cache"}
                if request["visualMode"] == "animation":
                    excluded.add("seedance_key")
                missing = [check["label"] for check in readiness["checks"] if not check["ok"] and check["id"] not in excluded]
                raise RequestError("Setup is incomplete: " + ", ".join(missing) + ". Check the setup status before generating.",
                                   "not_ready", 503)
            job = self.server.store.create(request, owner=user["id"])
            self.server.runner.submit(job)
            self._json(202, job)
        except OSError:
            self._error(500, "storage_error", "Could not save the task. Check local disk space and permissions.")

    def _resume_job(self, job_id):
        user = self._user()
        if user is None:
            return
        if self._read_json() != {}:
            raise RequestError("Resume uses the saved settings; send an empty JSON object.")
        job = self.server.store.get(job_id)
        if job is None or job.get("owner") != user["id"]:
            raise RequestError("This task was not found on this local server.", "job_not_found", 404)
        resumed = self.server.store.resume(job_id)
        self.server.runner.submit(resumed)
        self._json(202, resumed)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._local_request():
            return
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        if path.startswith("/api/"):
            try:
                self._api_get(path, parsed.query)
            except sqlite3.Error:
                self._error(500, "storage_error", "Could not read your account. Check local disk space and permissions.")
            return
        dist = self.server.root / "web/dist"
        try:
            target = (dist / path.lstrip("/")).resolve()
            if not target.is_relative_to(dist.resolve()) or any(part.startswith(".") for part in Path(path).parts if part != "/"):
                raise ValueError
        except (ValueError, OSError):
            self._error(404, "not_found", "File not found.")
            return
        if path == "/" or not target.suffix and not target.is_file():
            target = dist / "index.html"
        if not target.is_file():
            self._error(404, "frontend_not_built", "Build the frontend with npm --prefix web run build, or use the Vite development server.")
            return
        self._file(target)

    def _api_get(self, path, query):
        if path == "/api/auth/me":
            user = self._user()
            if user is not None:
                self._json(200, {"user": user})
            return
        user = self._user()
        if user is None:
            return
        if path == "/api/health":
            self._json(200, self.server.readiness())
            return
        if path == "/api/jobs":
            self._json(200, {"jobs": self.server.store.list(user["id"])})
            return
        parts = path.strip("/").split("/")
        if len(parts) >= 3 and parts[:2] == ["api", "jobs"]:
            job_id = parts[2]
            job = self.server.store.get(job_id) if JOB_ID.fullmatch(job_id) else None
            # Another account's job answers exactly like a missing one, so IDs reveal nothing.
            if job is None or job.get("owner") != user["id"]:
                self._error(404, "job_not_found", "This task was not found on this local server.")
            elif len(parts) == 3:
                self._json(200, job)
            elif len(parts) == 5 and parts[3] == "files":
                self._artifact(job, parts[4], parse_qs(query).get("download") == ["1"])
            else:
                self._error(404, "not_found", "API route not found.")
            return
        self._error(404, "not_found", "API route not found.")

    def _artifact(self, job, filename, download):
        if job["status"] != "completed" or job["result"] is None:
            self._error(409, "not_completed", "This task has no completed video yet.")
            return
        allowed = {"video.mp4": "video-draft.mp4" if job["request"]["draft"] else "video.mp4",
                   "thumbnail.png": "thumbnail.png", "subtitles.vtt": "video/subtitles.vtt"}
        if filename not in allowed:
            self._error(404, "not_found", "Artifact not found.")
            return
        directory = self.server.store.directory / job["id"] / "output"
        target = (directory / allowed[filename]).resolve()
        if not target.is_relative_to(directory.resolve()) or not target.is_file():
            self._error(404, "artifact_missing", "This generated file is no longer available on disk.")
            return
        self._file(target, download_name=f"capstone-{job['id'][:8]}-{filename}" if download else None)

    def _file(self, path, download_name=None):
        try:
            with path.open("rb") as handle:
                size = path.stat().st_size
                start, end, status = 0, size - 1, 200
                if self.headers.get("Range"):
                    try:
                        start, end = byte_range(self.headers["Range"], size)
                        status = 206
                    except ValueError:
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{size}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                self.send_response(status)
                media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                self.send_header("Content-Type", media_type)
                self.send_header("Content-Length", str(max(0, end - start + 1)))
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "no-cache")
                if status == 206:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                if download_name:
                    self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
                self.end_headers()
                if self.command == "HEAD":
                    return
                handle.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = handle.read(min(64 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError:
            self._error(404, "file_unavailable", "This file is unavailable on disk.")
