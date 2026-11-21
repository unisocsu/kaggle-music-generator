"""Kaggle queue worker for ServeurpersoCom/acestep.cpp (CUDA build)."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

REPO = os.getenv("GITHUB_REPOSITORY", "unisocsu/kaggle-music-generator")
TOKEN = os.getenv("GITHUB_TOKEN")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "15"))
ENGINE_ROOT = Path(os.getenv("ACESTEP_CPP_ROOT", "/kaggle/working/acestep.cpp"))
MODELS_DIR = Path(os.getenv("ACESTEP_MODELS_DIR", str(ENGINE_ROOT / "models")))
DEVICE = os.getenv("ACESTEP_DEVICE", "CUDA0")
LM_MODEL = os.getenv("ACESTEP_LM_MODEL", "acestep-5Hz-lm-4B-Q8_0")
DIT_MODEL = os.getenv("ACESTEP_DIT_MODEL", "acestep-v15-turbo-Q8_0")
OUT = Path("/kaggle/working/generated")
OUT.mkdir(parents=True, exist_ok=True)

if not TOKEN:
    raise RuntimeError("Missing GITHUB_TOKEN Kaggle Notebook Secret.")

API = f"https://api.github.com/repos/{REPO}"
HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": f"Bearer {TOKEN}",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "kaggle-acestep-cpp-music-worker",
}


def api(path, method="GET", payload=None, raw=None, content_type="application/json"):
    data = json.dumps(payload).encode("utf-8") if payload is not None else raw
    headers = dict(HEADERS)
    headers["Content-Type"] = content_type
    req = Request(API + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=300) as response:
            body = response.read()
            return json.loads(body) if body else None
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API {exc.code}: {detail}") from exc


def parse_job(body):
    marker = "<!-- music-job-v1 -->"
    if marker not in body:
        return None
    tail = body.split(marker, 1)[1]
    if "```json" in tail:
        raw = tail.split("```json", 1)[1].split("```", 1)[0].strip()
    else:
        start, end = tail.find("{"), tail.rfind("}")
        if start < 0 or end < start:
            raise ValueError("Missing JSON request in issue body.")
        raw = tail[start:end + 1]
    job = json.loads(raw)
    if job.get("schema_version") != 1 or job.get("type") != "music_generation":
        raise ValueError("Unsupported job schema.")
    if not str(job.get("prompt", "")).strip():
        raise ValueError("Music prompt is required.")
    duration = int(job.get("duration_seconds", 210))
    if not 30 <= duration <= 300:
        raise ValueError("duration_seconds must be between 30 and 300.")
    return job


def run_command(command, cwd, timeout=7200):
    print("+", " ".join(str(part) for part in command), flush=True)
    subprocess.run(
        [str(part) for part in command],
        cwd=str(cwd),
        check=True,
        timeout=timeout,
        env=os.environ.copy(),
    )


def verify_engine():
    lm = ENGINE_ROOT / "build" / "ace-lm"
    synth = ENGINE_ROOT / "build" / "ace-synth"
    for binary in (lm, synth):
        if not binary.is_file():
            raise RuntimeError(f"Missing compiled executable: {binary}")
    if not MODELS_DIR.is_dir() or not list(MODELS_DIR.glob("*.gguf")):
        raise RuntimeError(f"No GGUF model files found in {MODELS_DIR}")
    print("Engine:", ENGINE_ROOT)
    print("Models:", MODELS_DIR)
    print("CUDA device:", DEVICE)
    print("GGUF files:", [p.name for p in MODELS_DIR.glob("*.gguf")])


def make_request(job, job_dir):
    instrumental = bool(job.get("instrumental", False))
    lyrics = "[Instrumental]" if instrumental else str(job.get("lyrics", "")).strip()
    language = str(job.get("language", "") or "").strip()
    if language.lower() in ("other", "unknown", "auto"):
        language = ""

    seed = job.get("seed")
    try:
        seed = int(seed) if seed not in (None, "", -1, "-1") else -1
    except (TypeError, ValueError):
        seed = -1

    request = {
        "task_type": "text2music",
        "caption": str(job.get("prompt", "")).strip()[:2000],
        "lyrics": lyrics[:12000],
        "duration": int(job.get("duration_seconds", 210)),
        "vocal_language": language,
        "seed": seed,
        "lm_batch_size": 1,
        "synth_batch_size": 1,
        "inference_steps": 8,
        "shift": 3.0,
        "solver": "euler",
        "output_format": "mp3",
        "mp3_bitrate": 192,
        "lm_mode": "generate",
        "synth_model": DIT_MODEL,
        "lm_model": LM_MODEL,
        "use_cot_caption": True,
    }
    request_path = job_dir / "request.json"
    request_path.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    return request_path


def generate_audio(job, issue_number):
    job_dir = OUT / f"issue-{issue_number}"
    if job_dir.exists():
        shutil.rmtree(job_dir)
    job_dir.mkdir(parents=True)

    request_path = make_request(job, job_dir)
    lm = ENGINE_ROOT / "build" / "ace-lm"
    synth = ENGINE_ROOT / "build" / "ace-synth"

    # ace-lm writes request0.json; ace-synth turns it into request00.mp3.
    run_command([lm, "--models", MODELS_DIR, "--request", request_path, "--device", DEVICE], job_dir)
    enriched = job_dir / "request0.json"
    if not enriched.is_file():
        raise RuntimeError("ace-lm finished but did not create request0.json.")

    run_command([synth, "--models", MODELS_DIR, "--request", enriched, "--device", DEVICE], job_dir)
    audio = job_dir / "request00.mp3"
    if not audio.is_file() or audio.stat().st_size < 1024:
        candidates = sorted(job_dir.glob("*.mp3"), key=lambda p: p.stat().st_size, reverse=True)
        if not candidates:
            raise RuntimeError("ace-synth finished but no MP3 output was found.")
        audio = candidates[0]

    final_path = OUT / f"song-{issue_number}.mp3"
    shutil.copy2(audio, final_path)
    print("Generated:", final_path, "bytes:", final_path.stat().st_size)
    return final_path


def comment(number, body):
    api(f"/issues/{number}/comments", "POST", {"body": body})


def set_labels(number, names):
    api(f"/issues/{number}/labels", "PUT", {"labels": names})


def upload_asset(number, path):
    tag = f"music-job-{number}"
    try:
        release = api("/releases", "POST", {
            "tag_name": tag,
            "name": f"Generated music - Issue #{number}",
            "body": f"Generated audio for Issue #{number} using acestep.cpp on Kaggle CUDA.",
            "draft": False,
            "prerelease": True,
        })
    except RuntimeError as exc:
        # A previous attempt may have created the release before failing to upload.
        if "422" not in str(exc):
            raise
        release = api(f"/releases/tags/{tag}")

    upload_url = release["upload_url"].split("{", 1)[0] + "?name=" + path.name
    req = Request(
        upload_url,
        data=path.read_bytes(),
        headers={**HEADERS, "Content-Type": "audio/mpeg"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=900) as response:
            asset = json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Release upload failed ({exc.code}): {detail}") from exc
    return asset["browser_download_url"], release["html_url"]


def process_issue(issue):
    number = issue["number"]
    job = parse_job(issue.get("body", ""))
    if job is None:
        return False

    set_labels(number, ["processing"])
    comment(number, "Kaggle CUDA worker claimed this request. Loading the ACE-Step C++ pipeline now.")
    try:
        audio = generate_audio(job, number)
        audio_url, release_url = upload_asset(number, audio)
        comment(
            number,
            f"Generation complete with acestep.cpp.\n\nRESULT_URL: {audio_url}\n\nRelease: {release_url}",
        )
        set_labels(number, ["completed"])
        api(f"/issues/{number}", "PATCH", {"state": "closed"})
        print("Completed issue", number, audio_url, flush=True)
    except Exception as exc:
        message = f"Generation failed: {type(exc).__name__}: {exc}"
        comment(number, message[:1800])
        set_labels(number, ["failed"])
        print(message, flush=True)
    return True


def main():
    verify_engine()
    print(f"Polling {REPO} every {POLL_SECONDS}s. GPU target: {DEVICE}", flush=True)
    while True:
        try:
            issues = api("/issues?state=open&per_page=100")
            queue = [
                issue for issue in issues
                if "pull_request" not in issue
                and any(label.get("name") == "queued" for label in issue.get("labels", []))
            ]
            if not queue:
                time.sleep(POLL_SECONDS)
                continue
            queue.sort(key=lambda issue: issue.get("created_at", ""))
            for issue in queue:
                if process_issue(issue):
                    break
        except KeyboardInterrupt:
            print("Worker stopped.", flush=True)
            return
        except Exception as exc:
            print("Worker loop error:", repr(exc), flush=True)
            time.sleep(max(30, POLL_SECONDS))


if __name__ == "__main__":
    main()
