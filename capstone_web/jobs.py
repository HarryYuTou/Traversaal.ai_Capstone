"""Durable local jobs, a serial queue, and an isolated pipeline subprocess."""

import copy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
from uuid import uuid4

from .health import ROOT, SAMPLE, SEEDANCE_SAMPLE
from capstone_script.duration import requested_minimum

JOB_ID = re.compile(r"^[0-9a-f]{32}$")
EVENT_PREFIX = "CAPSTONE_EVENT:"
ACTIVE = {"queued", "running"}
STAGES = {"planning", "reviewing", "narrating", "storyboarding", "generating_video", "rendering"}
INTERRUPTED = "Generation was interrupted when the local server stopped. Resume if available, or submit a new job. No automatic retry was made."


class RequestError(ValueError):
    def __init__(self, message, code="invalid_request", status=400):
        super().__init__(message)
        self.code, self.status = code, status


def validate_request(body):
    if not isinstance(body, dict):
        raise RequestError("Send a JSON object with the video settings.")
    allowed = {"topic", "audience", "durationSeconds", "minimumDurationSec", "review", "theme", "music", "draft", "source",
               "visualMode", "videoResolution", "maxGeneratedSeconds"}
    if body.keys() - allowed:
        raise RequestError("Unknown request fields: " + ", ".join(sorted(body.keys() - allowed)))
    result = {"review": True, "theme": "light", "music": True, "draft": False, "source": "topic", **body}
    for name, limit in (("topic", 500), ("audience", 200)):
        value = result.get(name)
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
            raise RequestError(f"{name} must contain 1–{limit} characters.")
        if any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise RequestError(f"{name} contains unsupported control characters.")
        result[name] = value.strip()
    duration = result.get("durationSeconds")
    if type(duration) is not int or not 30 <= duration <= 600:
        raise RequestError("durationSeconds must be a whole number between 30 and 600.")
    for name in ("review", "music", "draft"):
        if type(result[name]) is not bool:
            raise RequestError(f"{name} must be true or false.")
    if result["theme"] not in ("light", "night"):
        raise RequestError("theme must be light or night.")
    if result["source"] not in ("topic", "sample"):
        raise RequestError("source must be topic or sample.")
    result.setdefault("visualMode", "animation")
    result.setdefault("videoResolution", "480p")
    if result["visualMode"] not in ("animation", "seedance"):
        raise RequestError("visualMode must be animation or seedance.")
    if result["videoResolution"] not in ("480p", "720p"):
        raise RequestError("videoResolution must be 480p or 720p.")
    if result["visualMode"] == "seedance":
        if "maxGeneratedSeconds" in body:
            raise RequestError("Seedance now generates the entire video. Refresh the page and choose one target length and video quality.")
        # Seedance quality controls both generation and export; animation-only settings cannot override it.
        result.update(draft=False, theme="light", minimumDurationSec=0)
    else:
        result.setdefault("maxGeneratedSeconds", 60)
        if type(result["maxGeneratedSeconds"]) is not int or not 4 <= result["maxGeneratedSeconds"] <= 120:
            raise RequestError("maxGeneratedSeconds must be a whole number between 4 and 120, including retries.")
    if result["source"] == "sample":
        sample = SEEDANCE_SAMPLE if result["visualMode"] == "seedance" else SAMPLE
        result.update({key: sample[key] for key in ("topic", "audience", "durationSeconds")}, review=False)
        result["minimumDurationSec"] = 0
    else:
        try:
            if "minimumDurationSec" in result and result["minimumDurationSec"] is None:
                raise ValueError("minimumDurationSec must be a whole number, not null.")
            result["minimumDurationSec"] = requested_minimum(duration, result.get("minimumDurationSec"))
        except ValueError as exc:
            raise RequestError(str(exc)) from None
    return result


def now():
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.jobs = {}
        for path in self.directory.glob("*/job.json"):
            if not JOB_ID.fullmatch(path.parent.name):
                continue
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if job["id"] != path.parent.name or job["status"] not in ACTIVE | {"completed", "failed"}:
                    continue
                self.jobs[job["id"]] = job
                if job["status"] in ACTIVE:
                    self.fail(job["id"], INTERRUPTED)
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def _write(self, job):
        directory = self.directory / job["id"]
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "job.json.tmp"
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(job, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(directory / "job.json")

    def create(self, request, owner=None):
        with self.lock:
            if sum(job["status"] in ACTIVE for job in self.jobs.values()) >= 8:
                raise RequestError("The local queue is full. Wait for a job to finish.", "queue_full", 429)
            timestamp = now()
            job = {"id": uuid4().hex, "status": "queued", "stage": "queued",
                   "message": "Queued. Jobs run one at a time on this computer.",
                   "createdAt": timestamp, "updatedAt": timestamp, "request": copy.deepcopy(request),
                   "error": None, "result": None, "owner": owner}
            if request.get("visualMode") == "seedance":
                job["pipelineVersion"] = 2
            self._write(job)
            self.jobs[job["id"]] = job
            return copy.deepcopy(job)

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            return copy.deepcopy(job) if job is not None else None

    def list(self, owner):
        """Return one owner's jobs, newest first. Jobs saved without an owner are not listed."""
        with self.lock:
            jobs = [job for job in self.jobs.values() if owner is not None and job.get("owner") == owner]
            return copy.deepcopy(sorted(jobs, key=lambda job: job["createdAt"], reverse=True))

    def update(self, job_id, **values):
        with self.lock:
            job = {**self.jobs[job_id], **values, "updatedAt": now()}
            self._write(job)
            self.jobs[job_id] = job
            return copy.deepcopy(job)

    def fail(self, job_id, message):
        """Keep failure visible even if the disk cannot accept a status update."""
        with self.lock:
            job = {**self.jobs[job_id], "status": "failed", "stage": "failed", "message": message,
                   "error": message, "result": None, "updatedAt": now(), "canResume": self.can_resume(job_id)}
            try:
                self._write(job)
            except Exception:
                # Reporting an I/O failure must not itself kill the only queue worker.
                detail = (message + " The failed status could not be saved and is currently kept in memory only. "
                          "Check local disk space and permissions before restarting the server.")
                job.update(message=detail, error=detail)
            self.jobs[job_id] = job
            return copy.deepcopy(job)

    def can_resume(self, job_id):
        job = self.jobs[job_id]
        output = self.directory / job_id / "output"
        if job["request"].get("visualMode") != "seedance" or not (output / "pipeline-checkpoint.json").is_file():
            return False
        try:
            manifest_path = output / "video-generation.json"
            manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"shots": {}}
            return all(row["state"] not in ("submitting", "submission_unknown") for row in manifest["shots"].values())
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def resume(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            if job["status"] != "failed" or not self.can_resume(job_id):
                raise RequestError("This job cannot be resumed safely. Existing task records were preserved.", "not_resumable", 409)
            if sum(item["status"] in ACTIVE for item in self.jobs.values()) >= 8:
                raise RequestError("The local queue is full.", "queue_full", 429)
            return self.update(job_id, status="queued", stage="queued", message="Queued to resume saved video tasks.",
                               error=None, result=None, canResume=False, resumeCount=job.get("resumeCount", 0) + 1)

    def interrupt(self):
        with self.lock:
            for job in list(self.jobs.values()):
                if job["status"] in ACTIVE:
                    self.fail(job["id"], INTERRUPTED)


class JobRunner:
    def __init__(self, store, root=ROOT, executor=None):
        self.store, self.root = store, Path(root).resolve()
        self.executor = executor or self._subprocess
        self.pending = queue.Queue()
        self.stop = threading.Event()
        self.process_lock = threading.Lock()
        self.process = None
        self.thread = threading.Thread(target=self._work, name="capstone-video-worker", daemon=True)
        self.thread.start()

    def submit(self, job):
        self.pending.put(job["id"])

    def _work(self):
        while not self.stop.is_set():
            job_id = self.pending.get()
            try:
                if job_id is None or self.stop.is_set():
                    return
                request = self.store.get(job_id)["request"]
                first = "narrating" if request["source"] == "sample" else "planning"
                self.store.update(job_id, status="running", stage=first,
                                  message="Starting the built-in sample." if first == "narrating" else "Planning your video.")
                result = self.executor(job_id, lambda event: self._event(job_id, event))
                minimum = request.get("minimumDurationSec", 0)
                if minimum and (not isinstance(result, dict)
                                or type(result.get("durationSeconds")) not in (int, float)
                                or not math.isfinite(result["durationSeconds"])
                                or not result["durationSeconds"] >= minimum):
                    raise WorkerError(f"The generated video did not meet the {minimum} second minimum. "
                                      "It has not been marked ready; inspect the duration check before retrying.")
                if not self.stop.is_set():
                    self.store.update(job_id, status="completed", stage="completed",
                                      message="Your video is ready to play and download.", result=result, error=None)
            except Exception as exc:
                if not self.stop.is_set():
                    current = self.store.get(job_id)
                    stage = current["stage"] if current else "startup"
                    if isinstance(exc, WorkerError):
                        message = str(exc)
                    elif isinstance(exc, OSError):
                        message = (f"Generation stopped during {stage} because a local file or process operation failed. "
                                   "Check disk space, permissions, and the local worker.log before retrying.")
                    else:
                        message = (f"Generation failed during {stage} ({type(exc).__name__}). "
                                   "Check the local worker.log for details.")
                    self.store.fail(job_id, message)
            finally:
                self.pending.task_done()

    def _event(self, job_id, event):
        if self.stop.is_set() or not isinstance(event, dict):
            return
        if event.get("stage") in STAGES:
            values = {"stage": event["stage"], "message": str(event.get("message", "Generating video."))[:500]}
            for field in ("lineProgress", "clipProgress"):
                progress = event.get(field)
                if isinstance(progress, dict) and type(progress.get("current")) is int and type(progress.get("total")) is int:
                    if 0 <= progress["current"] <= progress["total"]:
                        values[field] = {"current": progress["current"], "total": progress["total"]}
            self.store.update(job_id, **values)

    def _subprocess(self, job_id, callback):
        job_dir = self.store.directory / job_id
        command = [sys.executable, "-m", "capstone_web.worker", "--job", str(job_dir / "job.json")]
        result, failure = None, None
        with (job_dir / "worker.log").open("a", encoding="utf-8") as log:
            with self.process_lock:
                if self.stop.is_set():
                    raise WorkerError(INTERRUPTED)
                process = subprocess.Popen(command, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, encoding="utf-8", errors="replace", bufsize=1,
                                           start_new_session=True)
                self.process = process
            try:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    if not line.startswith(EVENT_PREFIX):
                        continue
                    try:
                        event = json.loads(line[len(EVENT_PREFIX):])
                    except ValueError:
                        continue
                    if event.get("type") == "result":
                        result = event["result"]
                    elif event.get("type") == "error":
                        failure = event.get("message")
                    else:
                        callback(event)
                code = process.wait()
            except BaseException:
                # A disk error or progress callback can interrupt stdout consumption while
                # Python, TTS, and Remotion are still running. Stop the owned process group
                # and reap the worker before allowing another queued job to start.
                self._terminate_process(process)
                raise
            finally:
                try:
                    process.stdout.close()
                finally:
                    with self.process_lock:
                        self.process = None
        if code != 0 or not result:
            stage = self.store.get(job_id)["stage"]
            raise WorkerError(failure or f"Generation stopped during {stage}. Check the local worker.log for details.")
        return result

    @staticmethod
    def _terminate_process(process):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()

    def close(self):
        self.stop.set()
        with self.process_lock:
            if self.process is not None and self.process.poll() is None:
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        self.pending.put(None)
        self.thread.join(timeout=5)
        with self.process_lock:
            if self.process is not None and self.process.poll() is None:
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        self.store.interrupt()


class WorkerError(RuntimeError):
    """An already-sanitized, user-facing worker failure."""
