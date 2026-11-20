import os,logging,threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import text
from src.config.database import Base,engine,Session
from src.models.ledger import LedgerState
from src.services.ledger import ensure_ledger,backfill_once
from src.services.traces import queue
from src.routes import auth,datasets,plans,traces,audit
from src.middlewares.errors import install_errors
from src.middlewares.requests import RequestTrace

def _backfill_worker():
 # 后台小事务回填，不阻塞 API；不同数据集的并发保存照常提交
 try:
  result=backfill_once()
  logging.info('ledger backfill finished: %s',result)
 except Exception:logging.exception('ledger backfill failed; retry on next startup')

@asynccontextmanager
async def lifespan(app):
 # 所有模型已导入，metadata 建表幂等；账本表同时就位
 Base.metadata.create_all(engine)
 ensure_ledger()
 with Session() as s:
  # 账本初始恒为 building；回填线程确认无缺口后才翻 ready
  if s.get(LedgerState,1) is None:s.add(LedgerState(id=1,state='building'));s.commit()
 if os.getenv('SEED_DEMO','true').lower()=='true':
  try:
   from scripts.seed_demo import seed
   seed()
  except Exception:logging.exception('seed failed; API remains available')
 # 旧行/种子行仍有缺口，或全新库需要把 building 翻为 ready：统一由回填线程处理
 threading.Thread(target=_backfill_worker,name='ledger-backfill',daemon=True).start()
 yield
app=FastAPI(title='松原 · 分析算子执行剖面仪',lifespan=lifespan)
app.add_middleware(RequestTrace);install_errors(app)
for r in (auth,datasets,plans,traces,audit):app.include_router(r.router)
@app.get('/health')
def health():
 with engine.connect() as c:c.execute(text('SELECT 1'))
 queue.ping();return {'status':'ok'}
