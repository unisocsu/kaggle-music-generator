"""ACE-Step 1.5 Kaggle queue worker. Loads models once and processes Issues sequentially."""
import json, os, re, shutil, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

REPO=os.getenv("GITHUB_REPOSITORY","unisocsu/kaggle-music-generator")
TOKEN=os.getenv("GITHUB_TOKEN")
POLL_SECONDS=int(os.getenv("POLL_SECONDS","15"))
PROJECT_ROOT=Path(os.getenv("ACESTEP_ROOT","/kaggle/working/ACE-Step-1.5"))
MODEL_CONFIG=os.getenv("ACESTEP_CONFIG_PATH","acestep-v15-turbo")
LM_MODEL=os.getenv("ACESTEP_LM_MODEL_PATH","acestep-5Hz-lm-0.6B")
LM_BACKEND=os.getenv("ACESTEP_LM_BACKEND","pt")
OUT=Path("/kaggle/working/generated"); OUT.mkdir(parents=True,exist_ok=True)
if not TOKEN: raise RuntimeError("Missing GITHUB_TOKEN Kaggle Notebook Secret.")

API=f"https://api.github.com/repos/{REPO}"
HEADERS={"Accept":"application/vnd.github+json","Authorization":f"Bearer {TOKEN}","X-GitHub-Api-Version":"2022-11-28","User-Agent":"kaggle-music-generator"}

def api(path,method="GET",payload=None,raw=None,content_type="application/json"):
    data=json.dumps(payload).encode() if payload is not None else raw
    headers=dict(HEADERS); headers["Content-Type"]=content_type
    req=Request(API+path,data=data,headers=headers,method=method)
    try:
        with urlopen(req,timeout=240) as r:
            body=r.read(); return json.loads(body) if body else None
    except HTTPError as e:
        raise RuntimeError(f"GitHub API {e.code}: {e.read().decode(errors='replace')}") from e

def parse_job(body):
    marker="<!-- music-job-v1 -->"
    if marker not in body: return None
    tail=body.split(marker,1)[1]
    start=tail.find("{"); end=tail.rfind("}")
    if start<0 or end<start: raise ValueError("Missing JSON request in issue body.")
    job=json.loads(tail[start:end+1])
    if job.get("schema_version")!=1 or job.get("type")!="music_generation":
        raise ValueError("Unsupported job schema.")
    if not str(job.get("prompt","")).strip() and not str(job.get("lyrics","")).strip():
        raise ValueError("Job must include a prompt or lyrics.")
    if not 30<=int(job.get("duration_seconds",210))<=300:
        raise ValueError("duration_seconds must be between 30 and 300.")
    return job

def load_models():
    import torch
    from acestep.handler import AceStepHandler
    from acestep.llm_inference import LLMHandler
    if not torch.cuda.is_available(): raise RuntimeError("GPU is not enabled for this Kaggle notebook.")
    print("GPU:",torch.cuda.get_device_name(0))
    dit=AceStepHandler(); lm=LLMHandler()
    print("Loading DiT:",MODEL_CONFIG)
    ok=dit.initialize_service(project_root=str(PROJECT_ROOT),config_path=MODEL_CONFIG,device="cuda")
    if ok is False: raise RuntimeError("DiT initialization returned False.")
    print("Loading LM:",LM_MODEL,"backend:",LM_BACKEND)
    ok=lm.initialize(checkpoint_dir=str(PROJECT_ROOT),lm_model_path=LM_MODEL,backend=LM_BACKEND,device="cuda")
    if ok is False: raise RuntimeError("LM initialization returned False.")
    print("ACE-Step models loaded.")
    return dit,lm

def generate_audio(job,output_path,models):
    from acestep.inference import GenerationParams,GenerationConfig,generate_music
    prompt=str(job.get("prompt","")).strip()[:512]
    lyrics=str(job.get("lyrics","")).strip()[:4096]
    instrumental=bool(job.get("instrumental",False))
    if instrumental: lyrics="[Instrumental]"
    language=str(job.get("language","unknown") or "unknown")
    duration=int(job.get("duration_seconds",210))
    seed=job.get("seed")
    seed=int(seed) if seed not in (None,"",-1) else -1
    params=GenerationParams(
        task_type="text2music",caption=prompt,lyrics=lyrics,instrumental=instrumental,
        vocal_language=language,duration=duration,inference_steps=8,seed=seed,
        shift=3.0,infer_method="ode",thinking=True,use_cot_metas=True,
        use_cot_caption=True,use_cot_language=True)
    config=GenerationConfig(batch_size=1,use_random_seed=(seed==-1),audio_format="mp3")
    result=generate_music(models[0],models[1],params,config,save_dir=str(OUT))
    if not result.success: raise RuntimeError(result.error or "ACE-Step generation failed.")
    if not result.audios: raise RuntimeError("ACE-Step returned no audio.")
    source=Path(result.audios[0]["path"])
    if not source.exists(): raise RuntimeError(f"Output file missing: {source}")
    shutil.copy2(source,output_path)
    print("Timing:",result.extra_outputs.get("time_costs",{}))

def comment(number,body): api(f"/issues/{number}/comments","POST",{"body":body})
def set_labels(number,names): api(f"/issues/{number}/labels","PUT",{"labels":names})

def upload_asset(number,path):
    release=api("/releases","POST",{
        "tag_name":f"music-job-{number}","name":f"Generated music - Issue #{number}",
        "body":f"Generated audio for Issue #{number}.","draft":False,"prerelease":True})
    upload_url=release["upload_url"].split("{",1)[0]+"?name="+path.name
    req=Request(upload_url,data=path.read_bytes(),headers={**HEADERS,"Content-Type":"audio/mpeg"},method="POST")
    try:
        with urlopen(req,timeout=600) as r: asset=json.loads(r.read())
    except HTTPError as e:
        raise RuntimeError(f"Release upload failed ({e.code}): {e.read().decode(errors='replace')}") from e
    return asset["browser_download_url"],release["html_url"]

def process_issue(issue,models):
    number=issue["number"]; job=parse_job(issue.get("body",""))
    if job is None: return False
    set_labels(number,["processing"])
    comment(number,"Kaggle worker claimed this job. ACE-Step generation is starting.")
    output=OUT/f"song-{number}.mp3"
    try:
        generate_audio(job,output,models)
        if not output.exists() or output.stat().st_size<1024:
            raise RuntimeError("Generated MP3 is missing or unexpectedly small.")
        audio_url,release_url=upload_asset(number,output)
        comment(number,f"Generation complete.\n\nRESULT_URL: {audio_url}\n\nRelease: {release_url}")
        set_labels(number,["completed"])
        api(f"/issues/{number}","PATCH",{"state":"closed"})
        print("Completed issue",number,audio_url)
    except Exception as e:
        comment(number,"Generation failed: "+str(e)[:1200])
        set_labels(number,["failed"])
        print("Job failed:",repr(e))
    return True

def main():
    models=load_models()
    print(f"Polling {REPO} every {POLL_SECONDS}s; model remains loaded.")
    while True:
        try:
            issues=api("/issues?state=open&per_page=100")
            queue=[i for i in issues if any(x.get("name")=="queued" for x in i.get("labels",[]))]
            if not queue: time.sleep(POLL_SECONDS); continue
            queue.sort(key=lambda i:i.get("created_at",""))
            for issue in queue:
                if process_issue(issue,models): break
        except KeyboardInterrupt:
            print("Worker stopped."); return
        except Exception as e:
            print("Worker loop error:",repr(e)); time.sleep(max(30,POLL_SECONDS))

if __name__=="__main__": main()
