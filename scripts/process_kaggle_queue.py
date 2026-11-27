"""GitHub Actions orchestrator for a long-lived Kaggle music session."""
import json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlparse
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


def process_log_line(line, announced, failed, engine_sessions, published):
    match = re.search(r"KAGGLE_ENGINE_READY:(\d+)", line)
    if match:
        number = int(match.group(1))
        engine_sessions.add(number)
        try:
            set_status(number, "processing")
            comment(number, "מנוע ACE-Step הופעל והסשן מוכן. אפשר לשלוח כמה בקשות שירים ברצף; המנוע יישאר פעיל בזמן השימוש.")
        except Exception as exc:
            print(f"Could not acknowledge engine session #{number}: {exc}", file=sys.stderr, flush=True)
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
            comment(number, "היצירה הסתיימה ב־Kaggle. בודק כעת את ההעלאה המיידית ל־GitHub.")
        except Exception as exc:
            print(f"Could not update issue #{number}: {exc}", file=sys.stderr, flush=True)
    match = re.search(r"KAGGLE_TEMP_URL:(\d+):(https://\S+)", line)
    if match:
        number, temp_url = int(match.group(1)), match.group(2)
        if number not in published:
            try:
                url, release_url = download_temp_and_publish(number, temp_url)
                finalize_published_issue(number, url, release_url)
                published.add(number)
                print(f"Published issue #{number} from TempFile.org to GitHub Release: {url}", flush=True)
            except Exception as exc:
                print(f"Could not publish temporary upload for issue #{number}: {exc}", file=sys.stderr, flush=True)
                try:
                    comment(number, "העלאת השיר לשרת הזמני הצליחה, אך הפרסום ב־GitHub נכשל. אנסה לפרסם את קובץ הפלט של Kaggle בסיום הסשן. פרטים: " + str(exc)[:500])
                except Exception:
                    pass
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


def kernel_status():
    result = subprocess.run(
        ["kaggle", "kernels", "status", KERNEL],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    status_text = (result.stdout + "\n" + result.stderr).strip()
    if result.returncode != 0:
        print("Kaggle status query failed:", status_text, flush=True)
    else:
        print("Kaggle status:", status_text, flush=True)
    return status_text, result.returncode


def follow_logs(announced, failed, engine_sessions, published):
    # Kaggle's current CLI uses an SSE stream for --follow. Its stream endpoint
    # can transiently return HTTP 500 while a newly pushed kernel is QUEUED.
    # Reconnect instead of treating that temporary stream failure as a failed run.
    deadline = time.monotonic() + 5 * 60 * 60 + 40 * 60
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        command = ["kaggle", "kernels", "logs", KERNEL, "--follow"]
        print(f"Opening Kaggle log stream (attempt {attempt}):", " ".join(command), flush=True)
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1
        )
        try:
            for line in process.stdout:
                print("[KAGGLE] " + line.rstrip(), flush=True)
                process_log_line(line, announced, failed, engine_sessions, published)
        finally:
            if process.stdout:
                process.stdout.close()
        code = process.wait()
        status_text, status_code = kernel_status()
        upper = status_text.upper()

        if "KERNELWORKERSTATUS.COMPLETE" in upper or re.search(r"\\bCOMPLETE\\b", upper):
            if code != 0:
                print("Log stream ended with an error after Kaggle completed; continuing to collect output.", flush=True)
            return

        if any(marker in upper for marker in (
            "KERNELWORKERSTATUS.ERROR", "KERNELWORKERSTATUS.CANCELLED",
            "KERNELWORKERSTATUS.FAILED"
        )) or re.search(r"\\b(FAILED|CANCELLED)\\b", upper):
            raise RuntimeError("Kaggle session ended unsuccessfully: " + status_text)

        print(
            f"Kaggle log stream ended (exit {code}, status-query exit {status_code}); "
            "kernel is not in a terminal state. Retrying in 20 seconds.",
            flush=True
        )
        time.sleep(20)

    status_text, _ = kernel_status()
    raise TimeoutError("Timed out waiting for Kaggle kernel to finish. Last status: " + status_text)

def publish(number, audio_path):
    tag = f"music-job-{number}"
    try:
        release = api("/releases/tags/" + tag)
    except RuntimeError as exc:
        if "404" not in str(exc):
            raise
        release = api("/releases", "POST", {
            "tag_name": tag,
            "name": f"Generated music - Issue #{number}",
            "body": f"ACE-Step session output for issue #{number}.",
            "draft": False,
            "prerelease": True
        })
    existing = next((item for item in release.get("assets", []) if item.get("name") == audio_path.name), None)
    if existing:
        return existing["browser_download_url"], release["html_url"]
    upload_url = release["upload_url"].split("{", 1)[0] + "?name=" + audio_path.name
    asset = api("", "POST", raw=audio_path.read_bytes(), content_type="audio/mpeg", url=upload_url)
    return asset["browser_download_url"], release["html_url"]


def finalize_published_issue(number, url, release_url):
    issue = api(f"/issues/{number}")
    body = issue.get("body") or ""
    if f"RESULT_URL: {url}" not in body:
        body = re.sub(r"\n*RESULT_URL:\\s*https://\S+\\s*$", "", body)
        body += f"\n\nRESULT_URL: {url}\n"
        api(f"/issues/{number}", "PATCH", {"body": body})
        comment(number, f"השיר מוכן! 🎵\n\n[האזנה / הורדה]({url})\n\n[GitHub Release]({release_url})")
    set_status(number, "completed")
    api(f"/issues/{number}", "PATCH", {"state": "closed", "state_reason": "completed"})


def download_temp_and_publish(number, temp_url):
    parsed = urlparse(temp_url)
    if parsed.scheme != "https" or parsed.hostname != "tempfile.org":
        raise ValueError("Rejected temporary upload URL: unexpected host or scheme")
    match = re.fullmatch(r"/([A-Za-z0-9]{11})/?", parsed.path)
    if not match:
        raise ValueError("Rejected temporary upload URL: invalid file identifier")
    download_url = f"https://tempfile.org/{match.group(1)}/download"
    target = Path(tempfile.gettempdir()) / f"song-{number}.mp3"
    total = 0
    try:
        with urlopen(Request(download_url, headers={"User-Agent": "actions-kaggle-session"}), timeout=300) as response:
            with target.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 100 * 1024 * 1024:
                        raise RuntimeError("Temporary MP3 exceeded the 100MB download limit")
                    output.write(chunk)
        if total < 1024:
            raise RuntimeError(f"Temporary MP3 download was too small ({total} bytes)")
        release_url, page_url = publish(number, target)
        return release_url, page_url
    finally:
        target.unlink(missing_ok=True)


def main():
    if not queued_issues():
        print("No queued music issues; no Kaggle session needed.")
        return
    if not USER:
        raise RuntimeError("Missing KAGGLE_USER_NAME secret.")
    announced, failed, engine_sessions, published = set(), set(), set(), set()
    with tempfile.TemporaryDirectory(prefix="kaggle-music-session-") as temp:
        notebook_folder = Path(temp)
        push_session(notebook_folder)
        follow_logs(announced, failed, engine_sessions, published)
        output = notebook_folder / "output"
        output.mkdir(exist_ok=True)
        cli(["kaggle", "kernels", "output", KERNEL, "-p", str(output), "--force"])
        mp3_files = sorted(output.rglob("song-*.mp3"))
        if not mp3_files and not engine_sessions:
            raise RuntimeError("Kaggle session completed but returned no song-*.mp3 files and no engine-start event.")
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
            issue = api(f"/issues/{number}")
            issue_body = issue.get("body") or ""
            already_recorded = f"RESULT_URL: {url}" in issue_body
            if not already_recorded:
                comment(number, f"השיר מוכן! 🎵\n\n[האזנה / הורדה]({url})\n\n[GitHub Release]({release_url})")
                issue_body = re.sub(r"\n*RESULT_URL:\\s*https://\S+\\s*$", "", issue_body)
                issue_body += f"\n\nRESULT_URL: {url}\n"
                api(f"/issues/{number}", "PATCH", {"body": issue_body})
            set_status(number, "completed")
            api(f"/issues/{number}", "PATCH", {"state": "closed", "state_reason": "completed"})
        for number in engine_sessions:
            try:
                comment(number, "סשן המנוע הסתיים. להפעלה מחדש לחץ שוב על ״הפעל מנוע״.")
                set_status(number, "completed")
                api(f"/issues/{number}", "PATCH", {"state": "closed", "state_reason": "completed"})
            except Exception as exc:
                print(f"Could not close engine session issue #{number}: {exc}", file=sys.stderr, flush=True)
    print("Kaggle session queue processing complete.")


if __name__ == "__main__":
    main()
