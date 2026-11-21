import json, os, sys
from pathlib import Path
p=Path(sys.argv[1])
job=json.loads(os.environ["MUSIC_JOB_JSON"])
data=json.loads(p.read_text(encoding="utf-8"))
cell=next(c for c in data["cells"] if c.get("id")=="job-payload")
src="".join(cell["source"])
marker="JOB_PAYLOAD = None"
if marker not in src: raise SystemExit("Missing notebook payload placeholder")
literal=json.dumps(job,ensure_ascii=False,separators=(",",":"))
src=src.replace(marker,"JOB_PAYLOAD = json.loads("+repr(literal)+")")
cell["source"]=[line+"\n" for line in src.splitlines()]
p.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print("Injected request for issue #"+str(job["issue_number"]))
