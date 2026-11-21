"""One-shot Kaggle ACE-Step C++ job runner. No GitHub credentials or API calls."""
import argparse, json, shutil, subprocess, os
from pathlib import Path
ENGINE=Path("/kaggle/working/acestep.cpp")
MODELS=ENGINE/"models"
OUT=Path("/kaggle/working/output")
DEVICE="CUDA0"
LM="acestep-5Hz-lm-4B-Q8_0"
DIT="acestep-v15-turbo-Q8_0"

def run(cmd,cwd,timeout=7200):
    print("+"," ".join(map(str,cmd)),flush=True)
    subprocess.run(list(map(str,cmd)),cwd=str(cwd),check=True,timeout=timeout,env=os.environ.copy())

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--job-file",default="/kaggle/working/job.json")
    args=ap.parse_args()
    job=json.loads(Path(args.job_file).read_text(encoding="utf-8"))
    if job.get("schema_version")!=1 or job.get("type")!="music_generation" or not str(job.get("prompt","")).strip():
        raise ValueError("Invalid music job payload.")
    duration=int(job.get("duration_seconds",210))
    if not 30<=duration<=300: raise ValueError("duration_seconds must be 30..300.")
    for b in (ENGINE/"build/ace-lm",ENGINE/"build/ace-synth"):
        if not b.is_file(): raise RuntimeError("Missing executable: "+str(b))
    if not list(MODELS.glob("*.gguf")): raise RuntimeError("No GGUF models found.")
    number=int(job["issue_number"])
    folder=OUT/f"issue-{number}"
    if folder.exists(): shutil.rmtree(folder)
    folder.mkdir(parents=True)
    lang=str(job.get("language","") or "").strip()
    if lang.lower() in ("other","unknown","auto"): lang=""
    lyrics="[Instrumental]" if job.get("instrumental") else str(job.get("lyrics","")).strip()
    try: seed=int(job.get("seed")) if job.get("seed") not in (None,"",-1,"-1") else -1
    except (TypeError,ValueError): seed=-1
    req={"task_type":"text2music","caption":str(job["prompt"]).strip()[:2000],"lyrics":lyrics[:12000],
         "duration":duration,"vocal_language":lang,"seed":seed,"lm_batch_size":1,"synth_batch_size":1,
         "inference_steps":8,"shift":3.0,"solver":"euler","output_format":"mp3","mp3_bitrate":192,
         "lm_mode":"generate","synth_model":DIT,"lm_model":LM,"use_cot_caption":True}
    rp=folder/"request.json"
    rp.write_text(json.dumps(req,ensure_ascii=False,indent=2),encoding="utf-8")
    run([ENGINE/"build/ace-lm","--models",MODELS,"--request",rp,"--device",DEVICE],folder)
    enriched=folder/"request0.json"
    if not enriched.is_file(): raise RuntimeError("ace-lm did not create request0.json")
    run([ENGINE/"build/ace-synth","--models",MODELS,"--request",enriched,"--device",DEVICE],folder)
    audio=folder/"request00.mp3"
    if not audio.is_file() or audio.stat().st_size<1024:
        candidates=sorted(folder.glob("*.mp3"),key=lambda p:p.stat().st_size,reverse=True)
        if not candidates: raise RuntimeError("No MP3 output found")
        audio=candidates[0]
    OUT.mkdir(parents=True,exist_ok=True)
    final=OUT/f"song-{number}.mp3"
    shutil.copy2(audio,final)
    print("RESULT_MP3="+str(final),flush=True)
    print("RESULT_BYTES="+str(final.stat().st_size),flush=True)

if __name__=="__main__": main()
