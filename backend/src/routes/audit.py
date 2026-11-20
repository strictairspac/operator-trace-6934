from fastapi import APIRouter,Depends,Query
from src.middlewares.auth import current,admin
from src.config.database import Session
from src.models.identity import Audit
from src.schemas.business import MarkerInput
from src.services import ledger
from src.controllers.business import create_marker
from src.utils.serialization import record
router=APIRouter()
@router.get('/audit')
def audit(u=Depends(admin)):
 with Session() as s:return [record(r) for r in s.query(Audit).order_by(Audit.id.desc()).limit(100)]
# 账本建账状态：仅管理员（审计页展示 建账中/可查）
@router.get('/ledger/overview')
def overview(u=Depends(admin)):return ledger.ledger_overview()
# 课堂标记：账本可查后由管理员创建
@router.post('/markers')
def add_marker(data:MarkerInput,u=Depends(admin)):return create_marker(data,u)
@router.get('/markers')
def markers(u=Depends(current)):return ledger.list_markers()
@router.get('/markers/{marker_id}')
def marker(marker_id:int,u=Depends(current)):return ledger.marker_detail(marker_id)
@router.get('/markers/{marker_id}/scene')
def scene(marker_id:int,u=Depends(current)):return ledger.scene_overview(marker_id)
@router.get('/markers/{marker_id}/scene/{entity_type}')
def scene_list(marker_id:int,entity_type:str,u=Depends(current),
               limit:int=Query(default=20,ge=1,le=100),
               cursor:int|None=None):
 return ledger.list_scene_entities(marker_id,entity_type,limit=limit,after_id=cursor)
@router.get('/markers/{marker_id}/scene/{entity_type}/{entity_id}')
def scene_one(marker_id:int,entity_type:str,entity_id:int,u=Depends(current)):
 return ledger.get_scene_entity(marker_id,entity_type,entity_id)
