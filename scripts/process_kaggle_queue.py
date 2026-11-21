"""GitHub Actions orchestrator for a long-lived Kaggle music session."""
import json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

REPO = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ["GITHUB_TOKEN"]
USER = os.environ["KAGGLE_USER_NAME"].strip()
KERNEL = USER + "/kaggle-music-generator-worker"
API = "https://api.github.com/repos/" + REPO
HEADERS = {
    "Accept": "application/vnd.github+json",
    "Authorization": "Bearer " + TOKEN,
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "actions-kaggle-session"
}


def api(path, method="GET", payload=None, raw=None, content_type="application/json", url=None):
    data = json.dumps(payload).encode() if payload is not None else raw
    headers = dict(HEADERS)
    headers["Content-Type"] = content_type
    try:
        with urlopen(Request(url or API + path, data=data, headers=headers, method=method), timeout=900) as response:
            body = response.read()
            return json.loads(body) if body else None
    except HTTPError as exc:
        raise RuntimeError(f"GitHub API {exc.code}: " + exc.read().decode(errors="replace")) from exc


def comment(number, message):
    api(f"/issues/{number}/comments", "POST", {"body": message})


def set_status(number, label):
    issue = api(f"/issues/{number}")
    labels = [
        item["name"] for item in issue.get("labels", [])
        if item["name"] not in ("queued", "processing", "completed", "failed")
    ]
    labels.append(label)
    api(f"/issues/{number}/labels", "PUT", {"labels": labels})


def queued_issues():
    items = api("/issues?state=open&per_page=100")
    return [
        issue for issue in items
        if "pull_request" not in issue
        and any(label["name"] == "queued" for label in issue.get("labels", []))
    ]


def cli(args):
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True)


def push_session(folder):
    shutil.copytree("kaggle/notebook", folder, dirs_exist_ok=True)
    metadata_path = folder / "kernel-metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["id"] = KERNEL
    metadata["enable_gpu"] = True
    metadata["enable_internet"] = True
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    cli(["kaggle", "kernels", "push", "-p", str(folder), "--timeout", "21600", "--accelerator", "NvidiaTeslaT4"])


def process_log_line(line, announced, failed):
    match = re.search(r"KAGGLE_SEEN:(\d+)", line)
    if match:
        number = int(match.group(1))
        if number not in announced:
            announced.add(number)
            try:
                set_status(number, "processing")
                comment(number, "ראיתי את הבקשה! השיר נכנס לעיבוד ב־Kaggle. אעדכן כאן כשהקובץ יהיה מוכן.")
            except Exception as exc:
                print(f"Could not acknowledge issue #{number}: {exc}", file=sys.stderr, flush=True)
    match = re.search(r"KAGGLE_DONE:(\d+):([^:\s]+):(\d+)", line)
    if match:
        number = int(match.group(1))
        try:
            comment(number, "היצירה הסתיימה בהצלחה. אני מוריד כעת את קובץ השיר ומעלה אותו ל־GitHub Releases.")
        except Exception as exc:
            print(f"Could not update issue #{number}: {exc}", file=sys.stderr, flush=True)
    match = re.search(r"KAGGLE_FAILED:(\d+):(.+)", line)
    if match:
        number = int(match.group(1))
        message = match.group(2).strip()[:2500]
        if number not in failed:
            failed.add(number)
            try:
                set_status(number, "failed")
                comment(number, "יצירת השיר נכשלה: " + message)
            except Exception as exc:
                print(f"Could not report failure for issue #{number}: {exc}", file=sys.stderr, flush=True)


def follow_logs(announced, failed):
    command = ["kaggle", "kernels", "logs", KERNEL, "--follow"]
    print("+", " ".join(command), flush=True)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
    try:
        for line in process.stdout:
            print("[KAGGLE] " + line.rstrip(), flush=True)
            process_log_line(line, announced, failed)
    finally:
        process.stdout.close()
    code = process.wait()
    status = subprocess.run(["kaggle", "kernels", "status", KERNEL], capture_output=True, text=True)
    status_text = (status.stdout + "\n" + status.stderr).strip()
    print("Final Kaggle status:", status_text, flush=True)
    if code != 0:
        raise RuntimeError("kaggle kernels logs --follow exited with code " + str(code))
    if "ERROR" in status_text.upper() or "FAILED" in status_text.upper():
        raise RuntimeError("Kaggle session failed: " + status_text)


def publish(number, audio_path):
    tag = f"music-job-{number}"
    try:
        release = api("/releases", "POST", {
            "tag_name": tag,
            "name": f"Generated music - Issue #{number}",
            "body": f"ACE-Step session output for issue #{number}.",
            "draft": False,
            "prerelease": True
        })
    except RuntimeError as exc:
        if "422" not in str(exc):
            raise
        release = api("/releases/tags/" + tag)
    upload_url = release["upload_url"].split("{", 1)[0] + "?name=" + audio_path.name
    asset = api("", "POST", raw=audio_path.read_bytes(), content_type="audio/mpeg", url=upload_url)
    return asset["browser_download_url"], release["html_url"]


def main():
    if not queued_issues():
        print("No queued music issues; no Kaggle session needed.")
        return
    if not USER:
        raise RuntimeError("Missing KAGGLE_USER_NAME secret.")
    announced, failed = set(), set()
    with tempfile.TemporaryDirectory(prefix="kaggle-music-session-") as temp:
        notebook_folder = Path(temp)
        push_session(notebook_folder)
        follow_logs(announced, failed)
        output = notebook_folder / "output"
        output.mkdir(exist_ok=True)
        cli(["kaggle", "kernels", "output", KERNEL, "-p", str(output), "--force"])
        mp3_files = sorted(output.rglob("song-*.mp3"))
        if not mp3_files:
            raise RuntimeError("Kaggle session completed but returned no song-*.mp3 files.")
        for audio in mp3_files:
            match = re.fullmatch(r"song-(\d+)(?:-\d+)?\.mp3", audio.name)
            if not match:
                continue
            number = int(match.group(1))
            if number in failed:
                continue
            if audio.stat().st_size < 1024:
                set_status(number, "failed")
                comment(number, "הקובץ שהוחזר מ־Kaggle קטן מדי ולכן לא פורסם.")
                continue
            url, release_url = publish(number, audio)
            comment(number, f"השיר מוכן! 🎵\n\n[האזנה / הורדה]({url})\n\n[GitHub Release]({release_url})")
            set_status(number, "completed")
            api(f"/issues/{number}", "PATCH", {"state": "closed", "state_reason": "completed"})
            print(f"Published issue #{number}: {url}", flush=True)
    print("Kaggle session queue processing complete.")


if __name__ == "__main__":
    main()
