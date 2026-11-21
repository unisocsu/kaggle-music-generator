"""Polling worker skeleton for the Kaggle notebook.

Connect generate_audio() to the installed ACE-Step 1.5 inference API.
Keep model initialization outside the polling loop so the weights stay loaded.
"""
import json, os, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

REPO = os.getenv("GITHUB_REPOSITORY", "unisocsu/kaggle-music-generator")
TOKEN = os.getenv("GITHUB_TOKEN")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "15"))
OUT = Path("/kaggle/working/generated"); OUT.mkdir(parents=True, exist_ok=True)
if not TOKEN: raise RuntimeError("Set GITHUB_TOKEN as a Kaggle Notebook Secret.")
API = "https://api.github.com/repos/" + REPO
H = {"Accept":"application/vnd.github+json","Authorization":"Bearer "+TOKEN,"X-GitHub-Api-Version":"2022-11-28","User-Agent":"kaggle-music-generator"}

def api(path, method="GET", payload=None, raw=None, content_type="application/json"):
    data = json.dumps(payload).encode() if payload is not None else raw
    headers = dict(H); headers["Content-Type"] = content_type
    req = Request(API+path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=180) as r:
            b=r.read(); return json.loads(b) if b else None
    except HTTPError as e:
        raise RuntimeError(f"GitHub API {e.code}: {e.read().decode(errors='replace')}")

def parse_job(body):
    if "<!-- music-job-v1 -->" not in body: return None
    job=json.loads(body.split("```json",1)[1].split("```",1)[0].strip())
    if job.get("schema_version") != 1 or job.get("type") != "music_generation": raise ValueError("Unsupported job schema")
    return job

def generate_audio(job, output_path):
    # TODO: integrate the exact ACE-Step 1.5 inference API used by this Kaggle notebook.
    # Load the model once before polling; this function should only run inference.
    raise NotImplementedError("ACE-Step inference adapter is not connected yet.")

def upload_asset(number, path):
    release=api("/releases","POST",{"tag_name":f"job-{number}","name":f"Generated song · Issue #{number}","body":f"Generated for issue #{number}.","draft":False,"prerelease":True})
    upload=release["upload_url"].split("{",1)[0]+"?name="+path.name
    req=Request(upload,data=path.read_bytes(),headers={**H,"Content-Type":"audio/mpeg"},method="POST")
    with urlopen(req,timeout=300) as r: asset=json.loads(r.read())
    return asset["browser_download_url"], release["html_url"]

def comment(number, body): api(f"/issues/{number}/comments","POST",{"body":body})
def labels(number, names): api(f"/issues/{number}/labels","PUT",{"labels":names})

def handle(issue):
    n=issue["number"]; job=parse_job(issue.get("body",""))
    if job is None: return
    labels(n,["processing"]); comment(n,"Kaggle worker claimed this job; generation started.")
    path=OUT/f"song-{n}.mp3"
    try:
        generate_audio(job,path)
        if not path.exists() or not path.stat().st_size: raise RuntimeError("No audio file was produced.")
        audio_url,release_url=upload_asset(n,path)
        comment(n,f"Generation complete.\n\nRESULT_URL: {audio_url}\n\nRelease: {release_url}")
        labels(n,["completed"]); api(f"/issues/{n}","PATCH",{"state":"closed"})
    except Exception as e:
        comment(n,"Generation failed: "+str(e)[:1200]); labels(n,["failed"]); raise

def main():
    print(f"Polling {REPO} every {POLL_SECONDS}s. Keep this Kaggle session running.")
    while True:
        try:
            issues=api("/issues?state=open&per_page=100")
            queue=[i for i in issues if any(x["name"]=="queued" for x in i.get("labels",[]))]
            if queue: handle(sorted(queue,key=lambda x:x["created_at"])[0])
            else: time.sleep(POLL_SECONDS)
        except KeyboardInterrupt: print("Worker stopped."); return
        except Exception as e: print("Worker error:",repr(e)); time.sleep(max(30,POLL_SECONDS))

if __name__=="__main__": main()