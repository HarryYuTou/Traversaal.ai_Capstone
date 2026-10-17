"""Offline tests for the local website API. No paid API, TTS, or renderer runs."""

import http.client
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from capstone_web.accounts import AccountStore, hash_password, validate_credentials, verify_password
from capstone_web.health import SAMPLE, api_key_available, health
from capstone_web.jobs import EVENT_PREFIX, INTERRUPTED, JobRunner, JobStore, RequestError, WorkerError, validate_request
from capstone_web.server import LocalServer, byte_range
from capstone_web.worker import error_message, generate


def request_body(**overrides):
    return {"topic": "How does a browser load a page?", "audience": "Curious adults",
            "durationSeconds": 90, "review": True, "theme": "light", "music": True,
            "draft": False, "source": "topic", **overrides}


def ready(**overrides):
    return {"status": "ok", "liveReady": True, "sampleReady": True,
            "checks": [], "sample": SAMPLE, **overrides}


class ValidationTests(unittest.TestCase):
    def test_normalizes_text_and_fixed_sample(self):
        self.assertEqual(validate_request(request_body(topic="  Hello  "))["topic"], "Hello")
        sample = validate_request(request_body(source="sample", theme="night", draft=True))
        self.assertEqual(sample["topic"], SAMPLE["topic"])
        self.assertFalse(sample["review"])
        self.assertTrue(sample["draft"])
        self.assertEqual(sample["theme"], "night")

    def test_rejects_invalid_types_limits_and_arbitrary_sources(self):
        for body in ([], request_body(durationSeconds=True), request_body(durationSeconds=90.0),
                     request_body(durationSeconds=29), request_body(durationSeconds=601),
                     request_body(topic=" "), request_body(topic="x" * 501),
                     request_body(audience="x" * 201), request_body(review="false"),
                     request_body(theme="unknown"), request_body(source="../../.env"),
                     request_body(referenceUrl="https://example.com")):
            with self.subTest(body=body), self.assertRaises(RequestError):
                validate_request(body)

    def test_single_byte_ranges(self):
        self.assertEqual(byte_range("bytes=2-4", 10), (2, 4))
        self.assertEqual(byte_range("bytes=7-", 10), (7, 9))
        self.assertEqual(byte_range("bytes=-3", 10), (7, 9))
        self.assertEqual(byte_range("bytes=-50", 10), (0, 9))
        self.assertEqual(byte_range("bytes=8-100", 10), (8, 9))
        for invalid in ("bytes=10-", "bytes=5-2", "bytes=-0", "bytes=-", "bytes=0-1,4-5", "items=0-1"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                byte_range(invalid, 10)


class HealthTests(unittest.TestCase):
    def test_sample_needs_no_claude_and_cache_is_advisory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "fixtures").mkdir()
            (root / "fixtures/scene-plan.valid.json").write_text('{"scenes": []}')
            cli = root / "renderer/node_modules/@remotion/cli/remotion-cli.js"
            cli.parent.mkdir(parents=True)
            cli.touch()
            with patch("capstone_web.health.has_module", side_effect=lambda name: name != "anthropic"), \
                    patch("capstone_web.health.shutil.which", return_value="node"), \
                    patch("capstone_web.health.api_key_available", return_value=False), \
                    patch("capstone_web.health.model_cached", return_value=False):
                result = health(root)
            self.assertTrue(result["sampleReady"])
            self.assertFalse(result["liveReady"])

    def test_env_is_checked_without_mutating_environment_or_leaking_key(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            (Path(directory) / ".env").write_text('export ANTHROPIC_API_KEY="local-test-secret"\n')
            self.assertTrue(api_key_available(Path(directory)))
            self.assertNotIn("ANTHROPIC_API_KEY", os.environ)
            os.environ["ANTHROPIC_API_KEY"] = ""
            self.assertFalse(api_key_available(Path(directory)))


class PersistenceAndQueueTests(unittest.TestCase):
    def assert_queue_drains(self, runner):
        drained = threading.Event()

        def wait():
            runner.pending.join()
            drained.set()

        threading.Thread(target=wait, daemon=True).start()
        self.assertTrue(drained.wait(3), "The queue stopped processing tasks.")

    def test_restarts_fail_pending_jobs_but_preserve_completed_results(self):
        with tempfile.TemporaryDirectory() as directory:
            first = JobStore(directory)
            running = first.create(request_body())
            first.update(running["id"], status="running", stage="rendering")
            queued = first.create(request_body())
            complete = first.create(request_body())
            first.update(complete["id"], status="completed", stage="completed", result={"title": "Done"})
            restarted = JobStore(directory)
            for job in (running, queued):
                self.assertEqual(restarted.get(job["id"])["status"], "failed")
                self.assertEqual(restarted.get(job["id"])["error"], INTERRUPTED)
            self.assertEqual(restarted.get(complete["id"])["result"], {"title": "Done"})

    def test_jobs_are_serial_and_progress_is_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(directory)
            started, release = threading.Event(), threading.Event()
            order = []

            def executor(job_id, progress):
                order.append(job_id)
                progress({"stage": "narrating", "message": "One line complete.",
                          "lineProgress": {"current": 1, "total": 3}})
                started.set()
                release.wait(3)
                return {"title": job_id}

            runner = JobRunner(store, executor=executor)
            try:
                first, second = store.create(request_body()), store.create(request_body())
                runner.submit(first)
                runner.submit(second)
                self.assertTrue(started.wait(2))
                self.assertEqual(store.get(first["id"])["lineProgress"], {"current": 1, "total": 3})
                self.assertEqual(store.get(second["id"])["status"], "queued")
                release.set()
                runner.pending.join()
                self.assertEqual(order, [first["id"], second["id"]])
                self.assertEqual(store.get(second["id"])["status"], "completed")
            finally:
                release.set()
                runner.close()

    def test_executor_failure_does_not_leak_exception_text_and_next_job_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(directory)
            first, second = store.create(request_body()), store.create(request_body())

            def executor(job_id, progress):
                if job_id == first["id"]:
                    raise ValueError("SECRET_API_KEY")
                return {"title": "Done"}

            runner = JobRunner(store, executor=executor)
            try:
                runner.submit(first)
                runner.submit(second)
                runner.pending.join()
                self.assertEqual(store.get(first["id"])["status"], "failed")
                self.assertNotIn("SECRET", store.get(first["id"])["error"])
                self.assertEqual(store.get(second["id"])["status"], "completed")
            finally:
                runner.close()

    def test_worker_subprocess_requires_success_even_after_result_event(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(directory)
            job = store.create(request_body())
            runner = JobRunner(store)
            process = Mock()
            process.stdout = io.StringIO("Render log\n" + EVENT_PREFIX + json.dumps(
                {"type": "result", "result": {"title": "Premature result"}}) + "\n")
            process.wait.return_value = 1
            try:
                with patch("capstone_web.jobs.subprocess.Popen", return_value=process) as popen, \
                        self.assertRaises(WorkerError):
                    runner._subprocess(job["id"], Mock())
                self.assertIsInstance(popen.call_args.args[0], list)
                self.assertNotIn("shell", popen.call_args.kwargs)
                self.assertIn("Render log", (store.directory / job["id"] / "worker.log").read_text())
            finally:
                runner.close()

    def test_initial_and_failure_status_write_errors_do_not_kill_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(directory)
            first, second = store.create(request_body()), store.create(request_body())
            write = store._write
            executor = Mock(return_value={"title": "Done"})
            runner = JobRunner(store, executor=executor)

            def disk_failure(job):
                if job["id"] == first["id"]:
                    raise OSError("private disk detail")
                write(job)

            try:
                with patch.object(store, "_write", side_effect=disk_failure):
                    runner.submit(first)
                    runner.submit(second)
                    self.assert_queue_drains(runner)
                    self.assertTrue(runner.thread.is_alive())
                    failed = store.get(first["id"])
                    self.assertEqual(failed["status"], "failed")
                    self.assertIn("memory only", failed["error"])
                    self.assertNotIn("private disk detail", failed["error"])
                    self.assertEqual(store.get(second["id"])["status"], "completed")
                    self.assertEqual(executor.call_count, 1)
                # Once storage recovers, the same worker accepts and persists more work.
                third = store.create(request_body())
                runner.submit(third)
                self.assert_queue_drains(runner)
                saved = json.loads((store.directory / third["id"] / "job.json").read_text())
                self.assertEqual(saved["status"], "completed")
            finally:
                runner.close()

    def test_failure_record_write_error_is_visible_and_next_job_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(directory)
            first, second = store.create(request_body()), store.create(request_body())
            write = store._write

            def executor(job_id, callback):
                if job_id == first["id"]:
                    raise ValueError("secret error text")
                return {"title": "Done"}

            def disk_failure(job):
                if job["id"] == first["id"] and job["status"] == "failed":
                    raise OSError("disk full")
                write(job)

            runner = JobRunner(store, executor=executor)
            try:
                with patch.object(store, "_write", side_effect=disk_failure):
                    runner.submit(first)
                    runner.submit(second)
                    self.assert_queue_drains(runner)
                    self.assertTrue(runner.thread.is_alive())
                    failed = store.get(first["id"])
                    self.assertEqual(failed["status"], "failed")
                    self.assertIn("memory only", failed["error"])
                    self.assertNotIn("secret error text", failed["error"])
                    self.assertEqual(store.get(second["id"])["status"], "completed")
            finally:
                runner.close()

    def test_subprocess_callback_error_terminates_and_reaps_process(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(directory)
            job = store.create(request_body())
            runner = JobRunner(store)
            process = Mock(pid=876543)
            process.stdout = io.StringIO(EVENT_PREFIX + json.dumps(
                {"type": "progress", "stage": "narrating", "message": "Speaking."}) + "\n")
            process.wait.return_value = -signal.SIGTERM
            callback = Mock(side_effect=OSError("status write failed"))
            try:
                with patch("capstone_web.jobs.subprocess.Popen", return_value=process), \
                        patch("capstone_web.jobs.os.killpg") as kill, \
                        self.assertRaisesRegex(OSError, "status write failed"):
                    runner._subprocess(job["id"], callback)
                kill.assert_called_once_with(process.pid, signal.SIGTERM)
                process.wait.assert_called_once_with(timeout=3)
                self.assertTrue(process.stdout.closed)
                self.assertIsNone(runner.process)
            finally:
                runner.close()

    def test_subprocess_log_error_escalates_to_kill_and_reaps_process(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(directory)
            job = store.create(request_body())
            runner = JobRunner(store)
            process = Mock(pid=876544)
            process.stdout = io.StringIO("Remotion output\n")
            process.wait.side_effect = [subprocess.TimeoutExpired("worker", 3), -signal.SIGKILL]
            log = Mock()
            log.write.side_effect = OSError("log disk full")
            context = Mock()
            context.__enter__ = Mock(return_value=log)
            context.__exit__ = Mock(return_value=False)
            try:
                with patch("capstone_web.jobs.Path.open", return_value=context), \
                        patch("capstone_web.jobs.subprocess.Popen", return_value=process), \
                        patch("capstone_web.jobs.os.killpg") as kill, \
                        self.assertRaisesRegex(OSError, "log disk full"):
                    runner._subprocess(job["id"], Mock())
                self.assertEqual([call.args for call in kill.call_args_list],
                                 [(process.pid, signal.SIGTERM), (process.pid, signal.SIGKILL)])
                self.assertEqual(process.wait.call_count, 2)
                self.assertTrue(process.stdout.closed)
                self.assertIsNone(runner.process)
            finally:
                runner.close()


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = JobStore(self.root / "runs/web")
        self.runner = Mock()
        self.readiness = Mock(return_value=ready())
        self.accounts = AccountStore(self.root / "runs/web/accounts.sqlite3", iterations=1000)
        self.server = LocalServer(("127.0.0.1", 0), root=self.root, store=self.store,
                                  runner=self.runner, readiness=self.readiness, accounts=self.accounts)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie = self.sign_up("alice")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temporary.cleanup()

    def call(self, method, path, body=None, headers=None, cookie=True):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        if isinstance(body, dict):
            body = json.dumps(body)
        session = {"Cookie": self.cookie if cookie is True else cookie} if cookie else {}
        connection.request(method, path, body=body,
                           headers={"Content-Type": "application/json", **session, **(headers or {})})
        response = connection.getresponse()
        status, response_headers, data = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return status, response_headers, data

    def sign_up(self, username, password="correct horse"):
        status, headers, _ = self.call("POST", "/api/auth/register",
                                       {"username": username, "password": password}, cookie=False)
        self.assertEqual(status, 201)
        return headers["Set-Cookie"].split(";")[0]

    def test_submit_get_health_and_reload_saved_job(self):
        status, _, data = self.call("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(data)["liveReady"])
        status, _, data = self.call("POST", "/api/jobs", request_body())
        self.assertEqual(status, 202)
        job = json.loads(data)
        self.runner.submit.assert_called_once_with(job)
        self.assertTrue((self.store.directory / job["id"] / "job.json").is_file())
        status, _, data = self.call("GET", "/api/jobs/" + job["id"])
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(data)["request"]["topic"], request_body()["topic"])

    def test_setup_failure_creates_no_job(self):
        self.readiness.return_value = ready(liveReady=False, checks=[
            {"id": "claude_key", "label": "Claude API credential", "ok": False}])
        status, _, data = self.call("POST", "/api/jobs", request_body())
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(data)["error"]["code"], "not_ready")
        self.assertFalse(self.store.jobs)
        self.runner.submit.assert_not_called()
        self.assertEqual(self.call("POST", "/api/jobs", request_body(source="sample"))[0], 202)

    def test_validation_json_size_and_content_type(self):
        for body in (request_body(durationSeconds=False), "{invalid"):
            self.assertEqual(self.call("POST", "/api/jobs", body)[0], 400)
        self.assertEqual(self.call("POST", "/api/jobs", "x" * 17000)[0], 413)
        self.assertEqual(self.call("POST", "/api/jobs", "{}", {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.call("GET", "/api/jobs/not-a-task")[0], 404)
        self.runner.submit.assert_not_called()

    def test_loopback_host_origin_and_browser_cross_site_protection(self):
        for headers in ({"Host": "attacker.example"}, {"Origin": "https://attacker.example"},
                        {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.call("POST", "/api/jobs", request_body(), headers)[0], 403)
        self.runner.submit.assert_not_called()
        self.assertEqual(self.call("POST", "/api/jobs", request_body(), {"Origin": "http://localhost:5173"})[0], 202)

    def completed_job(self):
        job = self.store.create(request_body(draft=True), owner=self.accounts.session_user(self.cookie.split("=", 1)[1])["id"])
        output = self.store.directory / job["id"] / "output"
        output.mkdir()
        (output / "video-draft.mp4").write_bytes(b"0123456789")
        (output / ".env").write_text("SECRET")
        self.store.update(job["id"], status="completed", stage="completed", result={"title": "Done"})
        return "/api/jobs/" + job["id"] + "/files/"

    def test_video_ranges_head_and_download(self):
        base = self.completed_job()
        status, headers, data = self.call("GET", base + "video.mp4", headers={"Range": "bytes=2-5"})
        self.assertEqual((status, data), (206, b"2345"))
        self.assertEqual(headers["Content-Range"], "bytes 2-5/10")
        self.assertEqual(headers["Content-Type"], "video/mp4")
        status, headers, data = self.call("HEAD", base + "video.mp4")
        self.assertEqual((status, data), (200, b""))
        self.assertEqual(headers["Content-Length"], "10")
        self.assertEqual(self.call("GET", base + "video.mp4", headers={"Range": "bytes=-2"})[2], b"89")
        self.assertEqual(self.call("GET", base + "video.mp4", headers={"Range": "bytes=20-"})[0], 416)
        status, headers, data = self.call("GET", base + "video.mp4?download=1")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Disposition"].startswith("attachment;"))

    def test_only_completed_allowlisted_artifacts_and_no_path_escape(self):
        base = self.completed_job()
        for path in (base + ".env", base + "../job.json", base + "%2E%2E/worker.log", "/%2E%2E/.env"):
            self.assertEqual(self.call("GET", path)[0], 404)
        job = self.store.create(request_body(), owner=json.loads(self.call("GET", "/api/auth/me")[2])["user"]["id"])
        self.assertEqual(self.call("GET", f"/api/jobs/{job['id']}/files/video.mp4")[0], 409)

    def test_api_requires_a_session_but_the_site_and_sign_in_do_not(self):
        for method, path in (("GET", "/api/health"), ("GET", "/api/jobs"), ("POST", "/api/jobs"),
                             ("GET", "/api/auth/me"), ("GET", "/api/jobs/" + "a" * 32)):
            status, _, data = self.call(method, path, request_body() if method == "POST" else None, cookie=False)
            self.assertEqual((status, json.loads(data)["error"]["code"]), (401, "not_signed_in"))
        self.assertEqual(self.call("GET", "/api/health", cookie="traversaal_session=forged")[0], 401)
        self.assertEqual(self.call("GET", "/api/health", cookie='traversaal_session="bad\\')[0], 401)
        self.runner.submit.assert_not_called()
        self.assertEqual(self.call("GET", "/studio", cookie=False)[0], 404)  # frontend not built, not 401

    def test_register_login_logout_and_cookie_attributes(self):
        status, headers, data = self.call("POST", "/api/auth/register",
                                          {"username": "Bob", "password": "long password"}, cookie=False)
        self.assertEqual(status, 201)
        self.assertEqual(json.loads(data)["user"]["username"], "Bob")
        for attribute in ("HttpOnly", "SameSite=Strict", "Path=/", "Max-Age=1209600"):
            self.assertIn(attribute, headers["Set-Cookie"])
        self.assertNotIn("password", data.decode())
        taken = self.call("POST", "/api/auth/register", {"username": "bob", "password": "another password"}, cookie=False)
        self.assertEqual((taken[0], json.loads(taken[2])["error"]["code"]), (409, "username_taken"))
        for password in ("wrong password", "LONG PASSWORD"):
            status, headers, data = self.call("POST", "/api/auth/login", {"username": "bob", "password": password}, cookie=False)
            self.assertEqual((status, json.loads(data)["error"]["code"]), (401, "invalid_credentials"))
            self.assertNotIn("Set-Cookie", headers)
        unknown = self.call("POST", "/api/auth/login", {"username": "nobody", "password": "long password"}, cookie=False)
        self.assertEqual(json.loads(unknown[2])["error"]["message"], json.loads(data)["error"]["message"])
        status, headers, _ = self.call("POST", "/api/auth/login", {"username": "BOB", "password": "long password"}, cookie=False)
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"].split(";")[0]
        self.assertEqual(json.loads(self.call("GET", "/api/auth/me", cookie=cookie)[2])["user"]["username"], "Bob")
        status, headers, _ = self.call("POST", "/api/auth/logout", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        self.assertEqual(self.call("GET", "/api/auth/me", cookie=cookie)[0], 401)
        # Signing out one browser leaves the other session working.
        self.assertEqual(self.call("GET", "/api/auth/me")[0], 200)

    def test_sign_in_rejects_bad_input_and_cross_site_requests(self):
        for body in ({"username": "ab", "password": "long password"}, {"username": "bad name", "password": "long password"},
                     {"username": "carol", "password": "short"}, {"username": "carol", "password": "x" * 129},
                     {"username": "carol"}, {"username": "carol", "password": "long password", "admin": True}, []):
            self.assertEqual(self.call("POST", "/api/auth/register", body, cookie=False)[0], 400)
        self.assertEqual(self.call("POST", "/api/auth/register", {"username": "carol", "password": "long password"},
                                   {"Origin": "https://attacker.example"}, cookie=False)[0], 403)
        self.assertEqual(self.call("POST", "/api/auth/login", {"username": "alice", "password": "correct horse"},
                                   {"Sec-Fetch-Site": "cross-site"}, cookie=False)[0], 403)

    def test_history_lists_only_your_jobs_newest_first(self):
        first = json.loads(self.call("POST", "/api/jobs", request_body(topic="First"))[2])
        second = json.loads(self.call("POST", "/api/jobs", request_body(topic="Second"))[2])
        bob = self.sign_up("bob")
        bobs = json.loads(self.call("POST", "/api/jobs", request_body(topic="Bob's"), cookie=bob)[2])
        self.store.create(request_body(topic="Saved before accounts existed"))
        status, _, data = self.call("GET", "/api/jobs")
        self.assertEqual(status, 200)
        self.assertEqual([job["id"] for job in json.loads(data)["jobs"]], [second["id"], first["id"]])
        self.assertEqual([job["id"] for job in json.loads(self.call("GET", "/api/jobs", cookie=bob)[2])["jobs"]], [bobs["id"]])
        self.assertEqual(first["owner"], json.loads(self.call("GET", "/api/auth/me")[2])["user"]["id"])

    def test_another_accounts_job_and_media_look_missing(self):
        base = self.completed_job()
        job_id = base.split("/")[3]
        self.assertEqual(self.call("GET", base + "video.mp4")[0], 200)
        bob = self.sign_up("bob")
        for path in ("/api/jobs/" + job_id, base + "video.mp4", base + "video.mp4?download=1", base + "subtitles.vtt"):
            status, _, data = self.call("GET", path, cookie=bob)
            self.assertEqual((status, json.loads(data)["error"]["code"]), (404, "job_not_found"))
        self.assertEqual(self.call("GET", base + "video.mp4", cookie=False)[0], 401)

    def test_static_frontend_and_missing_build(self):
        self.assertEqual(self.call("GET", "/")[0], 404)
        dist = self.root / "web/dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text("<main>Studio</main>")
        self.assertEqual(self.call("GET", "/")[2], b"<main>Studio</main>")
        self.assertEqual(self.call("GET", "/studio")[2], b"<main>Studio</main>")


class AccountTests(unittest.TestCase):
    def test_passwords_are_salted_and_verified_in_constant_form(self):
        first, second = hash_password("same password", 1000), hash_password("same password", 1000)
        self.assertNotEqual(first, second)
        self.assertNotIn("same password", first)
        self.assertTrue(verify_password("same password", first))
        self.assertFalse(verify_password("Same password", first))
        for stored in ("", "md5$1$00$00", "pbkdf2_sha256$x$00$00", "pbkdf2_sha256$1000$zz$00"):
            self.assertFalse(verify_password("same password", stored))

    def test_credentials_are_trimmed_and_limited(self):
        self.assertEqual(validate_credentials({"username": " dana.k ", "password": "  spaced  "}), ("dana.k", "  spaced  "))
        for body in ({"username": "d" * 33, "password": "long password"}, {"username": "dana", "password": 12345678},
                     {"username": "dañ", "password": "long password"}):
            with self.subTest(body=body), self.assertRaises(RequestError):
                validate_credentials(body)

    def test_sessions_survive_restart_expire_and_store_only_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "accounts.sqlite3"
            accounts = AccountStore(path, iterations=1000)
            user = accounts.register("erin", "long password")
            token = accounts.create_session(user["id"])
            self.assertEqual(AccountStore(path, iterations=1000).session_user(token), user)
            self.assertNotIn(token.encode(), path.read_bytes())
            self.assertIsNone(accounts.authenticate("erin", "wrong password"))
            self.assertIsNone(accounts.authenticate("nobody", "long password"))
            self.assertEqual(accounts.authenticate("ERIN", "long password"), user)
            with patch("capstone_web.accounts.now", return_value="9999-01-01T00:00:00+00:00"):
                self.assertIsNone(accounts.session_user(token))
            accounts.end_session(token)
            self.assertIsNone(accounts.session_user(token))
            self.assertIsNone(accounts.session_user(None))

    def test_jobs_keep_their_owner_across_restarts(self):
        with tempfile.TemporaryDirectory() as directory:
            store = JobStore(directory)
            job = store.create(request_body(), owner="u1")
            store.create(request_body(), owner="u2")
            restarted = JobStore(directory)
            self.assertEqual([saved["id"] for saved in restarted.list("u1")], [job["id"]])
            self.assertEqual(restarted.list(None), [])


class WorkerTests(unittest.TestCase):
    def test_topic_plans_reviews_reloads_and_then_narrates(self):
        from capstone_script.scene_plan import dump_plan, load_plan
        from capstone_web.health import ROOT
        plan = load_plan(ROOT / "fixtures/scene-plan.valid.json")
        order, events = [], []

        def planning(output, spec, client, reference, **kwargs):
            order.append("planning")
            output.mkdir()
            (output / "scene-plan.json").write_text(dump_plan(plan))
            return plan

        def review(output, client, reference, **kwargs):
            order.append("reviewing")
            data = json.loads((output / "scene-plan.json").read_text())
            data["title"] = "Reviewed title"
            (output / "scene-plan.json").write_text(json.dumps(data))

        def narration(revised, *args, **kwargs):
            self.assertEqual(revised.title, "Reviewed title")
            order.append("narrating")

        with tempfile.TemporaryDirectory() as directory, \
                patch("anthropic.Anthropic") as client, \
                patch("capstone_script.planner.load_env_file"), \
                patch("capstone_script.planner.write_plan_run", side_effect=planning), \
                patch("capstone_script.review.write_review", side_effect=review), \
                patch("capstone_script.narrate.narrate_plan", side_effect=narration), \
                patch("capstone_script.timeline.write_timeline"), \
                patch("capstone_script.render.render_video", return_value={
                    "probedSeconds": 90, "width": 1920, "height": 1080, "bytes": 4000}):
            result = generate({"id": "a" * 32, "request": request_body()}, Path(directory), events.append)
        self.assertEqual(order, ["planning", "reviewing", "narrating"])
        self.assertEqual(result["title"], "Reviewed title")
        self.assertTrue(any(event.get("stage") == "reviewing" for event in events))
        client.assert_called_once()

    def test_sample_real_pipeline_calls_skip_claude_and_emit_narration_progress(self):
        events = []
        info = {"probedSeconds": 88.3, "width": 960, "height": 540, "bytes": 2000}

        def narrate(plan, output, factory, **kwargs):
            kwargs["progress"](plan.scenes[0].narration[0].id + ": 1.25 s")

        with tempfile.TemporaryDirectory() as directory, \
                patch("capstone_script.planner.write_plan_run") as planner, \
                patch("capstone_script.review.write_review") as review, \
                patch("capstone_script.narrate.narrate_plan", side_effect=narrate) as narration, \
                patch("capstone_script.timeline.write_timeline") as timeline, \
                patch("capstone_script.render.render_video", return_value=info) as render, \
                patch("capstone_web.worker.model_cached", return_value=True):
            job = {"id": "a" * 32, "request": validate_request(request_body(source="sample", draft=True))}
            result = generate(job, Path(directory), events.append)
            planner.assert_not_called()
            review.assert_not_called()
            self.assertEqual(narration.call_args.kwargs["threads"], 2)
            self.assertTrue(narration.call_args.kwargs["offline"])
            timeline.assert_called_once()
            self.assertTrue(render.call_args.kwargs["draft"])
        self.assertEqual(result["durationSeconds"], 88.3)
        self.assertEqual(events[-1]["type"], "result")
        self.assertTrue(any(event.get("lineProgress", {}).get("current") == 1 for event in events))
        self.assertFalse(any(event.get("stage") in {"planning", "reviewing"} for event in events))

    def test_renderer_failure_never_emits_a_result_even_if_info_file_exists(self):
        events = []
        with tempfile.TemporaryDirectory() as directory, \
                patch("capstone_script.narrate.narrate_plan"), \
                patch("capstone_script.timeline.write_timeline"), \
                patch("capstone_script.render.render_video", side_effect=ValueError("private-secret")), \
                patch("capstone_web.worker.traceback.print_exc"), \
                self.assertRaises(ValueError):
            generate({"id": "b" * 32, "request": validate_request(request_body(source="sample"))},
                     Path(directory), events.append)
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(events[-1]["stage"], "rendering")
        self.assertNotIn("private-secret", events[-1]["message"])
        self.assertFalse(any(event["type"] == "result" for event in events))

    def test_errors_explain_stage_without_credential_or_raw_exception(self):
        message = error_message("planning", ValueError("sk-private"))
        self.assertIn("planning", message)
        self.assertIn("ValueError", message)
        self.assertNotIn("sk-private", message)


if __name__ == "__main__":
    unittest.main()
