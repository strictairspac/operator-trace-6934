import time,logging,redis
from pathlib import Path
from src.config.settings import REDIS_URL
from src.config.database import Base,engine,Session
from src.models.dataset import Dataset
from src.models.plan import Plan
from src.models.trace import Trace
from src.services.operators import execute
from src.services.audit import log
from src.services.ledger import ensure_ledger, stage_version, commit_versioned
q=redis.Redis.from_url(REDIS_URL)
# worker 独立进程，先确保账本序号表存在（建表/回填由后端进程负责）
Base.metadata.create_all(engine);ensure_ledger()
while True:
 Path('/tmp/worker-heartbeat').touch()
 try:
  item=q.blpop('operator-traces',timeout=2)
  if not item:continue
  run_id=int(item[1])
  with Session() as s:
   row=s.get(Trace,run_id)
   if not row or row.status!='queued':continue
   row.status='running'
   snapshot=row.snapshot
   stage_version(s,'trace',row,'U');commit_versioned(s)
  try:
   result=execute(snapshot['dataset'],snapshot['plan']['steps'])
   with Session() as s:
    r=s.get(Trace,run_id);r.result=result;r.status='completed'
    stage_version(s,'trace',r,'U');commit_versioned(s)
   log('worker','trace.completed',str(run_id))
  except Exception as exc:
   logging.exception('trace failed')
   with Session() as s:
    r=s.get(Trace,run_id);r.status='failed';r.error=str(exc)[:1000]
    stage_version(s,'trace',r,'U');commit_versioned(s)
 except Exception:logging.exception('worker loop');time.sleep(2)
