"""Long-lived Kaggle session: public GitHub Issues -> persistent ACE-Step server.

Kaggle only performs anonymous GET requests to public Issues. GitHub Actions
watches Kaggle logs and performs all authenticated GitHub writes.
"""
import argparse, json, os, re, subprocess, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

API_BASE = "https://api.github.com/repos/{repo}/issues"
SERVER = "http://127.0.0.1:8085"
ENGINE = Path("/kaggle/working/acestep.cpp")
MODELS = ENGINE / "models"
OUTPUT = Path("/kaggle/working")  # Kaggle publishes files saved directly in working as kernel outputs.


def upload_temp_file(audio_path, issue_number):
    """Upload an MP3 to TempFile.org; GitHub Actions performs authenticated publishing."""
    boundary = "----KaggleMusic" + __import__("secrets").token_hex(16)
    filename = audio_path.name.replace('"', "")
    audio = audio_path.read_bytes()
    if not 1024 <= len(audio) <= 100 * 1024 * 1024:
        raise ValueError("MP3 size is outside TempFile.org's supported 1KB-100MB range")
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="files"; filename="{filename}"\r\n'
        "Content-Type: audio/mpeg\r\n\r\n"
    ).encode("utf-8") + audio + (
        f"\r\n--{boundary}\r\n"
        'Content-Disposition: form-data; name="expiryHours"\r\n\r\n'
        "24\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://tempfile.org/api/upload/local", data=body, method="POST",
        headers={
            "Content-Type": "multipart/form-data; boundary=" + boundary,
            "Content-Length": str(len(body)),
            "User-Agent": "kaggle-music-generator/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=300) as response:
        result = json.loads(response.read().decode("utf-8"))
    files = result.get("files") or []
    if not result.get("success") or not files:
        raise RuntimeError("TempFile.org upload failed: " + json.dumps(result, ensure_ascii=False)[:800])
    url = files[0].get("url", "")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "tempfile.org":
        raise RuntimeError("TempFile.org returned an unexpected upload URL")
    print(f"KAGGLE_TEMP_URL:{issue_number}:{url}", flush=True)
    return url
LM_MODEL = "acestep-5Hz-lm-4B-Q8_0.gguf"
DIT_MODEL = "acestep-v15-turbo-Q8_0.gguf"


def request(url, method="GET", payload=None, headers=None, timeout=60):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    h = {"User-Agent": "kaggle-music-session", "Accept": "application/vnd.github+json"}
    if headers: h.update(headers)
    if data is not None: h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(), response.headers


def server_json(path, method="GET", payload=None, timeout=120):
    body, headers = request(SERVER + path, method, payload, timeout=timeout)
    return json.loads(body.decode("utf-8")), headers

def download_reference_audio(url, issue_number):
    """Download only reference samples stored in this repository's public upload folder."""
    parsed = urllib.parse.urlparse(str(url or ""))
    expected_prefix = "/unisocsu/kaggle-music-generator/main/reference-audio/"
    if parsed.scheme != "https" or parsed.hostname != "raw.githubusercontent.com" or not parsed.path.startswith(expected_prefix):
        raise ValueError("reference_audio_url must point to this repository's reference-audio folder")
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in (".mp3", ".wav", ".flac", ".m4a", ".aac"):
        raise ValueError("Unsupported reference audio format")
    req = urllib.request.Request(url, headers={"User-Agent": "kaggle-music-session"})
    with urllib.request.urlopen(req, timeout=120) as response:
        data = response.read(25 * 1024 * 1024 + 1)
    if not 1024 <= len(data) <= 25 * 1024 * 1024:
        raise ValueError("Reference audio must be between 1KB and 25MB")
    target = OUTPUT / f"reference-{issue_number}{suffix}"
    target.write_bytes(data)
    return target


def server_synth_with_reference(payload, audio_path, timeout=120):
    """Send JSON request plus a separate timbre-reference audio part."""
    boundary = "----AceStepReference" + __import__("secrets").token_hex(16)
    request_json = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    filename = audio_path.name.replace('"', "")
    audio = audio_path.read_bytes()
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="request"; filename="request.json"\r\n'
        "Content-Type: application/json\r\n\r\n"
    ).encode("utf-8") + request_json + (
        f"\r\n--{boundary}\r\n"
        f'Content-Disposition: form-data; name="ref_audio"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + audio + (
        f"\r\n--{boundary}--\r\n"
    ).encode("utf-8")
    req = urllib.request.Request(
        SERVER + "/synth", data=body, method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary,
                 "Content-Length": str(len(body)), "User-Agent": "kaggle-music-session"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8")), response.headers

def start_server():
    binary = ENGINE / "build" / "ace-server"
    if not binary.is_file(): raise RuntimeError("Missing ace-server binary: " + str(binary))
    if not list(MODELS.glob("*.gguf")): raise RuntimeError("No GGUF models found in " + str(MODELS))
    log_path = Path("/kaggle/working/ace-server.log")
    log = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [str(binary), "--models", str(MODELS), "--device", "CUDA0",
         "--vae-chunk", "256", "--vae-overlap", "32",
         "--host", "127.0.0.1", "--port", "8085"],
        cwd=str(ENGINE), stdout=log, stderr=subprocess.STDOUT, env=os.environ.copy()
    )
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            log.close()
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-5000:]
            raise RuntimeError("ace-server exited during startup:\n" + tail)
        try:
            body, _ = request(SERVER + "/health", timeout=5)
            if json.loads(body.decode("utf-8")).get("status") == "ok":
                print("ACE_SERVER_READY:8085", flush=True)
                return proc, log
        except Exception:
            pass
        time.sleep(2)
    proc.terminate()
    log.close()
    raise TimeoutError("ace-server did not become healthy within 180 seconds")


def wait_server_job(job_id, timeout_seconds=3 * 60 * 60):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        state, _ = server_json("/job?id=" + urllib.parse.quote(str(job_id)), timeout=30)
        status = state.get("status")
        if status == "done": return
        if status in ("failed", "cancelled"):
            diagnostics = {"state": state}
            try:
                result, _ = server_json("/job?id=" + urllib.parse.quote(str(job_id)) + "&result=1", timeout=30)
                diagnostics["result"] = result
            except Exception as exc:
                diagnostics["result_error"] = type(exc).__name__ + ": " + str(exc)
            log_path = Path("/kaggle/working/ace-server.log")
            if log_path.is_file():
                diagnostics["server_log_tail"] = log_path.read_text(encoding="utf-8", errors="replace")[-12000:]
            raise RuntimeError(
                "ACE-Step job " + str(job_id) + " ended as " + status + "; diagnostics="
                + json.dumps(diagnostics, ensure_ascii=False, default=str)[:9000]
            )
        time.sleep(3)
    raise TimeoutError("ACE-Step job timed out: " + str(job_id))


def parse_multipart_audio(data, content_type):
    boundary = None
    for item in content_type.split(";"):
        item = item.strip()
        if item.startswith("boundary="):
            boundary = item[len("boundary="):].strip().strip('"').encode("ascii")
            break
    if not boundary:
        if content_type.lower().startswith(("audio/mpeg", "audio/wav")): return [data]
        raise ValueError("No multipart boundary in synth response: " + content_type)
    found = []
    for chunk in data.split(b"--" + boundary):
        if not chunk or chunk.startswith(b"--"): continue
        chunk = chunk.strip(b"\r\n")
        split_at = chunk.find(b"\r\n\r\n")
        if split_at < 0: continue
        headers = chunk[:split_at].decode("latin-1", errors="replace").lower()
        body = chunk[split_at + 4:]
        if body.endswith(b"\r\n"): body = body[:-2]
        if "content-type: audio/mpeg" in headers or "content-type: audio/wav" in headers:
            found.append(body)
    if not found: raise RuntimeError("Synth response contained no audio part.")
    return found


def make_request(job):
    duration = int(job.get("duration_seconds", 210))
    if not 30 <= duration <= 300: raise ValueError("duration_seconds must be between 30 and 300")
    language = str(job.get("language") or "").strip()
    if language.lower() in ("other", "unknown", "auto"): language = ""
    lyrics = "[Instrumental]" if job.get("instrumental") else str(job.get("lyrics") or "").strip()
    try: seed = int(job.get("seed")) if job.get("seed") not in (None, "", -1, "-1") else -1
    except (TypeError, ValueError): seed = -1
    genre = str(job.get("genre") or "").strip()
    try: inference_steps = int(job.get("inference_steps", 8))
    except (TypeError, ValueError): raise ValueError("inference_steps must be an integer between 1 and 32")
    if not 1 <= inference_steps <= 32: raise ValueError("inference_steps must be between 1 and 32")
    prompt = str(job.get("prompt") or "").strip()
    caption = (f"Genre: {genre}. " if genre else "") + prompt
    return {
        "task_type": "text2music", "caption": caption[:2000],
        "lyrics": lyrics[:12000], "duration": duration, "vocal_language": language, "seed": seed,
        "lm_batch_size": 1, "synth_batch_size": 1, "inference_steps": inference_steps, "shift": 3.0,
        "solver": "euler", "output_format": "mp3", "mp3_bitrate": 192, "lm_mode": "generate",
        "synth_model": DIT_MODEL, "lm_model": LM_MODEL, "use_cot_caption": True
    }


def generate(job):
    n = int(job["issue_number"])
    lm_ticket, _ = server_json("/lm", "POST", make_request(job))
    lm_id = lm_ticket.get("id")
    if not lm_id: raise RuntimeError("ACE-Step /lm did not return a job id: " + repr(lm_ticket))
    print("ACE_LM_JOB:" + str(n) + ":" + str(lm_id), flush=True)
    wait_server_job(lm_id)
    enriched, _ = server_json("/job?id=" + urllib.parse.quote(str(lm_id)) + "&result=1")
    if not isinstance(enriched, list) or not enriched: raise RuntimeError("ACE-Step /lm returned an empty result.")
    reference_path = None
    if job.get("reference_audio_url"):
        reference_path = download_reference_audio(job["reference_audio_url"], n)
    if reference_path:
        synth_ticket, _ = server_synth_with_reference(enriched, reference_path)
    else:
        synth_ticket, _ = server_json("/synth", "POST", enriched)
    synth_id = synth_ticket.get("id")
    if not synth_id: raise RuntimeError("ACE-Step /synth did not return a job id: " + repr(synth_ticket))
    print("ACE_SYNTH_JOB:" + str(n) + ":" + str(synth_id), flush=True)
    wait_server_job(synth_id)
    audio_data, audio_headers = request(
        SERVER + "/job?id=" + urllib.parse.quote(str(synth_id)) + "&result=1", timeout=900
    )
    audio_parts = parse_multipart_audio(audio_data, audio_headers.get("Content-Type", ""))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for i, audio in enumerate(audio_parts):
        suffix = "" if len(audio_parts) == 1 else f"-{i + 1}"
        target = OUTPUT / f"song-{n}{suffix}.mp3"
        target.write_bytes(audio)
        if target.stat().st_size < 1024:
            target.unlink(missing_ok=True)
            raise RuntimeError("ACE-Step produced an unexpectedly small MP3.")
        print(f"KAGGLE_DONE:{n}:{target.name}:{target.stat().st_size}", flush=True)
        try:
            upload_temp_file(target, n)
        except Exception as exc:
            print(f"KAGGLE_TEMP_UPLOAD_ERROR:{n}:{type(exc).__name__}:{str(exc)[:500]}", flush=True)


def get_queued_issues(repo, etag):
    url = API_BASE.format(repo=repo) + "?state=open&labels=queued&per_page=100"
    headers = {"If-None-Match": etag} if etag else {}
    try:
        body, response_headers = request(url, headers=headers, timeout=45)
        return json.loads(body.decode("utf-8")), response_headers.get("ETag", etag), False
    except urllib.error.HTTPError as exc:
        if exc.code == 304: return [], etag, True
        raise


def parse_issue(issue):
    body = issue.get("body") or ""
    if "<!-- music-session-start-v1 -->" in body:
        return {"issue_number": int(issue["number"]), "_session_start": True}
    if "<!-- music-job-v1 -->" not in body: return None
    tail = body.split("<!-- music-job-v1 -->", 1)[1]
    match = re.search(r"\`\`\`json\s*(.*?)\s*\`\`\`", tail, re.S)
    if not match: raise ValueError("Issue does not contain a JSON request block.")
    job = json.loads(match.group(1))
    if job.get("schema_version") != 1 or job.get("type") != "music_generation":
        raise ValueError("Unsupported music request schema.")
    if not str(job.get("prompt") or "").strip(): raise ValueError("Music prompt is empty.")
    job["issue_number"] = int(issue["number"])
    make_request(job)
    return job


def run_session(repo, poll_seconds, idle_seconds, max_seconds):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    server, server_log = start_server()
    seen, etag = set(), None
    started = last_activity = time.monotonic()
    try:
        print("KAGGLE_SESSION_READY:" + repo, flush=True)
        while time.monotonic() - started < max_seconds:
            try:
                issues, etag, unchanged = get_queued_issues(repo, etag)
            except Exception as exc:
                print("KAGGLE_POLL_ERROR:" + type(exc).__name__ + ":" + str(exc)[:500], flush=True)
                time.sleep(min(60, poll_seconds * 2))
                continue
            if not unchanged:
                issues.sort(key=lambda x: x.get("created_at", ""))
                for issue in issues:
                    n = int(issue["number"])
                    if n in seen or "pull_request" in issue: continue
                    seen.add(n)
                    last_activity = time.monotonic()
                    print(f"KAGGLE_SEEN:{n}", flush=True)
                    try:
                        job = parse_issue(issue)
                        if job is None:
                            print(f"KAGGLE_FAILED:{n}:Missing music-job marker", flush=True)
                            continue
                        if job.get("_session_start"):
                            print(f"KAGGLE_ENGINE_READY:{n}", flush=True)
                            continue
                        generate(job)
                    except Exception as exc:
                        # Kaggle log streams may use ASCII; escape non-ASCII diagnostics so Hebrew
                        # text in ACE-Step errors cannot crash the error-reporting path itself.
                        message = (type(exc).__name__ + ": " + str(exc)).replace("\n", " ")[:4000]
                        message = message.encode("ascii", errors="backslashreplace").decode("ascii")
                        print(f"KAGGLE_FAILED:{n}:{message}", flush=True)
                    last_activity = time.monotonic()
            if time.monotonic() - last_activity >= idle_seconds:
                print("KAGGLE_SESSION_IDLE_EXIT", flush=True)
                break
            time.sleep(poll_seconds)
        else:
            print("KAGGLE_SESSION_MAX_RUNTIME_REACHED", flush=True)
    finally:
        if server.poll() is None:
            server.terminate()
            try: server.wait(timeout=30)
            except subprocess.TimeoutExpired: server.kill()
        server_log.close()
        print("KAGGLE_SESSION_STOPPED", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--poll-seconds", type=int, default=15)
    # Keep the GPU session warm so the user can submit several songs without restarting it.
    # The matching GitHub Pages frontend is validated in the same CI workflow, including the multi-song chat UI.
    parser.add_argument("--idle-seconds", type=int, default=900)
    parser.add_argument("--max-seconds", type=int, default=5 * 60 * 60 + 35 * 60)
    args = parser.parse_args()
    if "/" not in args.repo or args.repo.startswith("/") or args.repo.endswith("/"):
        raise ValueError("--repo must be owner/name")
    run_session(args.repo, max(10, args.poll_seconds), max(60, args.idle_seconds), max(600, args.max_seconds))


if __name__ == "__main__":
    main()
