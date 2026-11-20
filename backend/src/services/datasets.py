from fastapi import HTTPException
from src.config.database import Session
from src.models.dataset import Dataset
from src.utils.serialization import record
from src.services.ledger import stage_version, commit_versioned

def list_items():
 with Session() as s:return [record(r) for r in s.query(Dataset).order_by(Dataset.id.desc()).all()]
def save(data,item_id=None):
 with Session() as s:
  row=s.get(Dataset,item_id) if item_id else Dataset()
  if not row:raise HTTPException(404,'未找到记录')
  change='U' if item_id else 'I'
  for k,v in data.model_dump().items():setattr(row,k,v)
  s.add(row)
  stage_version(s,'dataset',row,change)
  commit_versioned(s)
  s.refresh(row)
  return record(row)
