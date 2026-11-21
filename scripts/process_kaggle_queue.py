"""GitHub Actions queue: GitHub API -> Kaggle CLI -> GitHub Release."""
import json, os, re, shutil, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
REPO=os.environ["GITHUB_REPOSITORY"]; TOKEN=os.environ["GITHUB_TOKEN"]
USER=os.environ["KAGGLE_USER_NAME"].strip(); KERNEL=USER+"/kaggle-music-generator-worker"
API="https://api.github.com/repos/"+REPO
H={"Accept":"application/vnd.github+json","Authorization":"Bearer "+TOKEN,"X-GitHub-Api-Version":"2022-11-28","User-Agent":"actions-kaggle-queue"}
POLL=int(os.getenv("KAGGLE_POLL_SECONDS","45"))

def api(path,method="GET",payload=None,raw=None,ctype="application/json",url=None):
    data=json.dumps(payload).encode() if payload is not None else raw
    headers=dict(H); headers["Content-Type"]=ctype
    try:
        with urlopen(Request(url or API+path,data=data,headers=headers,method=method),timeout=900) as r:
            b=r.read(); return json.loads(b) if b else None
    except HTTPError as e: raise RuntimeError(f"GitHub API {e.code}: "+e.read().decode(errors="replace")) from e

def comment(n,s): api(f"/issues/{n}/comments","POST",{"body":s})
def status(n,label):
    issue=api(f"/issues/{n}")
    labels=[x["name"] for x in issue.get("labels",[]) if x["name"] not in ("queued","processing","completed","failed")]
    labels.append(label); api(f"/issues/{n}/labels","PUT",{"labels":labels})

def parse(issue):
    body=issue.get("body") or ""
    if "<!-- music-job-v1 -->" not in body: return None
    tail=body.split("<!-- music-job-v1 -->",1)[1]
    fence=chr(96)*3
    m=re.search(re.escape(fence)+r"json\s*(.*?)\s*"+re.escape(fence),tail,re.S)
    if not m: raise ValueError("No JSON request block in issue.")
    job=json.loads(m.group(1))
    if job.get("schema_version")!=1 or job.get("type")!="music_generation" or not str(job.get("prompt","")).strip():
        raise ValueError("Invalid music request.")
    if not 30<=int(job.get("duration_seconds",210))<=300: raise ValueError("Duration must be 30..300 seconds.")
    job["issue_number"]=issue["number"]; return job

def cli(args):
    print("+"," ".join(map(str,args)),flush=True)
    subprocess.run(list(map(str,args)),check=True)

def push_job(job,folder):
    shutil.copytree("kaggle/notebook",folder,dirs_exist_ok=True)
    mp=folder/"kernel-metadata.json"; meta=json.loads(mp.read_text())
    meta["id"]=KERNEL; meta["enable_gpu"]=True; meta["enable_internet"]=True
    mp.write_text(json.dumps(meta,indent=2)+"\n")
    os.environ["MUSIC_JOB_JSON"]=json.dumps(job,ensure_ascii=False)
    cli([sys.executable,"scripts/prepare_kaggle_notebook.py",str(folder/"worker.ipynb")])
    cli(["kaggle","kernels","push","-p",str(folder),"--timeout","43200"])

def wait():
    end=time.time()+5*3600+45*60
    while time.time()<end:
        r=subprocess.run(["kaggle","kernels","status",KERNEL],capture_output=True,text=True)
        s=(r.stdout+"\n"+r.stderr).strip(); low=s.lower()
        print("Kaggle status:",s,flush=True)
        if "complete" in low and not any(x in low for x in ("incomplete","not complete")): return
        if any(x in low for x in ("kernelworkerstatus.error","kernelworkerstatus.cancel","status: error","status: failed","kernel failed")):
            raise RuntimeError("Kaggle execution failed: "+s[-2500:])
        if r.returncode and not s: raise RuntimeError("Could not retrieve Kaggle kernel status.")
        time.sleep(POLL)
    raise TimeoutError("Kaggle run exceeded the GitHub Actions polling window.")

def publish(n,path):
    tag=f"music-job-{n}"
    try:
        rel=api("/releases","POST",{"tag_name":tag,"name":f"Generated music - Issue #{n}","body":f"ACE-Step C++ audio for issue #{n}.","draft":False,"prerelease":True})
    except RuntimeError as e:
        if "422" not in str(e): raise
        rel=api("/releases/tags/"+tag)
    upload=rel["upload_url"].split("{",1)[0]+"?name="+path.name
    asset=api("","POST",raw=path.read_bytes(),ctype="audio/mpeg",url=upload)
    return asset["browser_download_url"],rel["html_url"]

def process(issue):
    n=issue["number"]; job=parse(issue)
    if job is None: return
    status(n,"processing"); comment(n,"GitHub Actions is launching a one-shot Kaggle GPU run through Kaggle CLI. No GitHub token is sent to Kaggle.")
    try:
        with tempfile.TemporaryDirectory(prefix=f"music-{n}-") as t:
            folder=Path(t); push_job(job,folder); wait()
            out=folder/"output"; out.mkdir(exist_ok=True)
            cli(["kaggle","kernels","output",KERNEL,"-p",str(out),"--force"])
            files=list(out.rglob("*.mp3"))
            if not files: raise RuntimeError("Kaggle completed but returned no MP3 output.")
            mp3=max(files,key=lambda p:p.stat().st_size)
            if mp3.stat().st_size<1024: raise RuntimeError("MP3 output is unexpectedly small.")
            audio,release=publish(n,mp3)
        comment(n,f"Generation complete.\n\nRESULT_URL: {audio}\n\nRelease: {release}")
        status(n,"completed"); api(f"/issues/{n}","PATCH",{"state":"closed","state_reason":"completed"})
    except Exception as e:
        msg=f"Kaggle generation failed: {type(e).__name__}: {e}"
        comment(n,msg[:4500]); status(n,"failed"); print(msg,file=sys.stderr,flush=True)

def main():
    while True:
        items=api("/issues?state=open&per_page=100")
        queued=[x for x in items if "pull_request" not in x and any(l["name"]=="queued" for l in x.get("labels",[]))]
        queued.sort(key=lambda x:x.get("created_at",""))
        if not queued: print("Queue empty."); return
        process(queued[0])
if __name__=="__main__": main()
