"""Small REST adapter. No SDK retries, alternate models, or configurable API hosts."""

import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import httpx

from . import BASE_URL, MODEL_ID, RESOLUTIONS, SubmissionUnknown, VideoError

TASK_ID = re.compile(r"^[A-Za-z0-9_-]{1,180}$")
MAX_DOWNLOAD_BYTES = 150 * 1024 * 1024


class ArkVideoClient:
    def __init__(self, key=None, *, transport=None):
        key = key if key is not None else os.environ.get("ARK_API_KEY", "")
        if not key.strip():
            raise VideoError("Add ARK_API_KEY to the server environment or project .env.")
        configured = os.environ.get("ARK_VIDEO_MODEL", MODEL_ID)
        if configured != MODEL_ID:
            raise VideoError(f"Only {MODEL_ID} is allowed. Remove the conflicting ARK_VIDEO_MODEL setting.")
        self.client = httpx.Client(base_url=BASE_URL + "/", headers={"Authorization": f"Bearer {key.strip()}"},
                                   timeout=httpx.Timeout(45, connect=15), transport=transport,
                                   follow_redirects=False)

    def close(self):
        self.client.close()

    def preflight(self):
        """Read-only connectivity/authentication check before any new paid submission."""
        self._request("GET", "contents/generations/tasks", params={"page_size": 1})

    def _request(self, method, path, **kwargs):
        try:
            response = self.client.request(method, path, **kwargs)
        except httpx.TransportError:
            if method == "POST":
                raise SubmissionUnknown("The submission was interrupted before a task ID was saved. It may have been "
                                        "accepted. No automatic resubmission will be made; check the Ark task list "
                                        "before creating another video.") from None
            raise VideoError("Cannot reach the Ark video API. Check the network, then resume this job; "
                             "saved task IDs will be reused.") from None
        if response.is_error:
            messages = {
                400: "Ark rejected the video parameters. Inspect the local error code before retrying.",
                401: "Ark authentication failed. Check ARK_API_KEY.",
                403: "Ark denied this request. Check model activation, key permissions and service availability.",
                404: "Ark could not find this model or task. Task records may have expired; no replacement was submitted.",
                429: "Ark rate or account limit reached. Wait and check your balance before resuming.",
            }
            try:
                code = response.json().get("error", {}).get("code", "")
                code = code if isinstance(code, str) and re.fullmatch(r"[\w.:-]{1,100}", code) else ""
            except (ValueError, AttributeError):
                code = ""
            message = messages.get(response.status_code, f"Ark returned HTTP {response.status_code}.")
            # A server error after POST is ambiguous, even when the body is JSON.
            error = SubmissionUnknown if method == "POST" and response.status_code >= 500 else VideoError
            raise error(message + (f" Code: {code}." if code else ""))
        try:
            return response.json()
        except ValueError:
            error = SubmissionUnknown if method == "POST" else VideoError
            raise error("Ark returned an unreadable response. No automatic resubmission was made.") from None

    def submit(self, prompt, duration, resolution, seed):
        if type(duration) is not int or not 4 <= duration <= 15 or resolution not in RESOLUTIONS:
            raise VideoError("Seedance Fast requires 4–15 seconds and 480p or 720p.")
        if not isinstance(prompt, str) or not 30 <= len(prompt) <= 5000:
            raise VideoError("Each video prompt must contain 30–5000 characters.")
        if type(seed) is not int or not 0 <= seed <= 2147483647:
            raise VideoError("Invalid video seed.")
        body = {"model": MODEL_ID, "content": [{"type": "text", "text": prompt}],
                "duration": duration, "resolution": resolution, "ratio": "16:9",
                "generate_audio": False, "watermark": False, "seed": seed}
        result = self._request("POST", "contents/generations/tasks", json=body)
        task_id = result.get("id") if isinstance(result, dict) else None
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            raise SubmissionUnknown("Ark did not return a usable task ID. Check the Ark task list before submitting again.")
        return task_id

    def get(self, task_id):
        if not isinstance(task_id, str) or not TASK_ID.fullmatch(task_id):
            raise VideoError("Invalid saved video task ID.")
        result = self._request("GET", "contents/generations/tasks/" + task_id)
        if not isinstance(result, dict) or result.get("id", task_id) != task_id:
            raise VideoError("Ark returned an unexpected video task.")
        if result.get("model") not in (None, MODEL_ID):
            raise VideoError("The returned model does not match the required Seedance 2.0 Fast model.")
        return result

    def download(self, url, path):
        parsed = urlsplit(url)
        hostname = parsed.hostname or ""
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443)
                or not any(hostname.endswith(suffix) for suffix in (".volces.com", ".volcengine.com", ".byteimg.com"))):
            raise VideoError("Ark returned an unsupported media download address.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".download")
        try:
            # Separate client: the API credential must never be sent to the media host.
            with httpx.stream("GET", url, timeout=60, follow_redirects=False) as response:
                if response.status_code != 200:
                    raise VideoError("The video download failed. Resume to request a fresh task result.")
                size = 0
                with temporary.open("wb") as handle:
                    for block in response.iter_bytes():
                        size += len(block)
                        if size > MAX_DOWNLOAD_BYTES:
                            raise VideoError("The video download exceeds the local size limit.")
                        handle.write(block)
                if size < 100:
                    raise VideoError("Ark returned an empty video file.")
            temporary.replace(path)
        except httpx.TransportError:
            raise VideoError("The video download was interrupted. Resume to reuse the saved generation task.") from None
        finally:
            temporary.unlink(missing_ok=True)
