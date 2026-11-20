"""时态账本服务：版本化提交、时间旅行读取、课堂标记、旧数据回填。

可见性规则（需求对应）：
- 标记冻结 horizon_seq；读取标记现场只取 commit_seq <= horizon 的版本。
- commit_seq 在业务事务内、提交前由 ledger_seq 单行 UPDATE 领取，行锁保证
  序号顺序 == 提交顺序；晚提交的写入即使开始得早，也只会拿到晚序号。
- 事务回滚则领取的序号与写入的版本全部不存在，历史中不留版本。
- 标记只保存一个序号整数，版本按实体增量追加，均不复制整库。
"""
from fastapi import HTTPException
from sqlalchemy import text, func
from sqlalchemy.orm import Session as OrmSession

from src.config.database import Session
from src.constants.enums import LEDGER_ENTITIES, LEDGER_STATES
from src.models.ledger import LedgerSeq, LedgerState, EntityVersion, Marker
from src.utils.serialization import record

# 回填时每多少行提交一次小事务
BACKFILL_BATCH = 50


# ---------- 账本状态 ----------

def ensure_ledger():
    """启动时确保单行序号表存在（幂等）。"""
    with Session() as s:
        if not s.get(LedgerSeq, 1):
            s.add(LedgerSeq(id=1, next_seq=1))
            s.commit()


def get_state(s: OrmSession) -> str:
    row = s.execute(text(
        "SELECT state FROM ledger_state WHERE id=1"
    )).first()
    return row[0] if row else LEDGER_STATES[0]


def ledger_overview() -> dict:
    with Session() as s:
        state = get_state(s)
        versioned = {
            et: s.execute(
                text("SELECT count(DISTINCT entity_id) FROM entity_versions WHERE entity_type=:et"),
                {'et': et},
            ).scalar_one()
            for et in LEDGER_ENTITIES
        }
        totals = {
            'dataset': text("SELECT count(*) FROM datasets"),
            'plan': text("SELECT count(*) FROM plans"),
            'trace': text("SELECT count(*) FROM traces"),
        }
        actual = {et: s.execute(sql).scalar_one() for et, sql in totals.items()}
        markers = s.query(Marker).count()
        return {
            'state': state,
            'state_label': '可查' if state == 'ready' else '建账中',
            'versioned_entities': versioned,
            'total_entities': actual,
            'version_rows': s.query(EntityVersion).count(),
            'markers': markers,
        }


# ---------- 版本化提交 ----------

def _next_commit_seq(s: OrmSession) -> int:
    """在当前事务内领取下一个全局提交序号（行锁串行，调用即提交）。

    PostgreSQL 走 UPDATE ... RETURNING；SQLite 写事务本身串行，退化为读后写。
    """
    if s.bind.dialect.name == 'postgresql':
        seq = s.execute(text(
            "UPDATE ledger_seq SET next_seq = next_seq + 1 WHERE id = 1 RETURNING next_seq - 1"
        )).scalar_one()
    else:
        row = s.get(LedgerSeq, 1)
        seq = row.next_seq
        row.next_seq = seq + 1
        s.flush()
    return seq


def stage_version(s: OrmSession, entity_type: str, entity, change_type: str) -> None:
    """在业务事务内登记一条待提交版本（与业务行同生共死）。

    entity 必须是已挂在该 session 上的 ORM 实例；先 flush 取得 id 与最新列值。
    """
    if entity_type not in LEDGER_ENTITIES:
        raise ValueError('未知账本实体类型: %s' % entity_type)
    if change_type not in ('I', 'U'):
        raise ValueError('版本变更类型仅支持 I/U')
    s.flush()
    s.info.setdefault('pending_versions', []).append(
        (entity_type, entity, change_type)
    )


def commit_versioned(s: OrmSession) -> int:
    """给本事务所有暂存版本领取同一 commit_seq 并提交；返回该序号。"""
    pending = s.info.get('pending_versions', [])
    if not pending:
        s.commit()
        return 0
    seq = _next_commit_seq(s)
    for entity_type, entity, change_type in pending:
        s.add(EntityVersion(
            entity_type=entity_type,
            entity_id=entity.id,
            commit_seq=seq,
            change_type=change_type,
            payload=record(entity),
        ))
    s.commit()
    s.info['pending_versions'] = []
    return seq


# ---------- 标记 ----------

def current_horizon(s: OrmSession) -> int:
    """当前已提交的最大序号；尚无任何版本时为 0。"""
    value = s.query(func.max(EntityVersion.commit_seq)).scalar()
    return int(value or 0)


def create_marker(data, user) -> dict:
    with Session() as s:
        if get_state(s) != 'ready':
            raise HTTPException(409, '账本建账中，回填完成后才能创建课堂标记')
        horizon = current_horizon(s)
        row = Marker(
            name=data.name,
            note=data.note or '',
            horizon_seq=horizon,
            created_by=user.email,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return record(row)


def list_markers() -> list:
    with Session() as s:
        return [record(r) for r in s.query(Marker).order_by(Marker.id.desc()).all()]


def get_marker(s: OrmSession, marker_id: int) -> Marker:
    row = s.get(Marker, marker_id)
    if not row:
        raise HTTPException(404, '未找到课堂标记')
    return row


def marker_detail(marker_id: int) -> dict:
    with Session() as s:
        return record(get_marker(s, marker_id))


# ---------- 时间旅行读取 ----------

def _latest_versions_sql() -> str:
    """取每个实体在 horizon 内的最新版本（窗口函数，PG/SQLite 均支持）。"""
    return """
        SELECT entity_id, payload, commit_seq, change_type
        FROM (
            SELECT entity_id, payload, commit_seq, change_type,
                   row_number() OVER (PARTITION BY entity_id ORDER BY commit_seq DESC) AS rn
            FROM entity_versions
            WHERE entity_type = :et AND commit_seq <= :horizon
        ) ranked
        WHERE rn = 1
        ORDER BY entity_id
    """


def scene_overview(marker_id: int) -> dict:
    """标记现场三类实体的数量与状态分布。"""
    with Session() as s:
        marker = get_marker(s, marker_id)
        horizon = marker.horizon_seq
        counts = {}
        for et in LEDGER_ENTITIES:
            counts[et] = s.execute(text(
                "SELECT count(*) FROM (%s) t" % _latest_versions_sql()
            ), {'et': et, 'horizon': horizon}).scalar_one()
        trace_statuses = {}
        rows = s.execute(text(_latest_versions_sql()),
                         {'et': 'trace', 'horizon': horizon}).all()
        for _, payload, _, _ in rows:
            trace_statuses[payload['status']] = trace_statuses.get(payload['status'], 0) + 1
        return {
            'marker': record(marker),
            'counts': counts,
            'trace_statuses': trace_statuses,
        }


def list_scene_entities(marker_id: int, entity_type: str, limit: int = 20,
                        after_id: int | None = None) -> dict:
    """翻看标记现场的某类实体（键集分页，中断后可用 cursor 回到原位置）。

    排序固定为 entity_id；新写入只产生更大的 commit_seq，被 horizon 挡住，
    因此翻页期间新写入不会改变所见，cursor 也不会漂移。
    """
    if entity_type not in LEDGER_ENTITIES:
        raise HTTPException(404, '未知实体类型')
    limit = max(1, min(int(limit), 100))
    with Session() as s:
        marker = get_marker(s, marker_id)
        params = {'et': entity_type, 'horizon': marker.horizon_seq, 'lim': limit + 1}
        sql = (
            "SELECT entity_id, payload, commit_seq, change_type FROM (%s) latest"
            % _latest_versions_sql()
        )
        if after_id is not None:
            sql += " WHERE entity_id > :after"
            params['after'] = after_id
        sql += " ORDER BY entity_id LIMIT :lim"
        rows = s.execute(text(sql), params).all()
    items = [
        {'entity_id': entity_id, 'commit_seq': seq, 'change_type': chg, 'entity': payload}
        for entity_id, payload, seq, chg in rows[:limit]
    ]
    next_after = items[-1]['entity_id'] if len(rows) > limit else None
    return {
        'marker_id': marker_id,
        'entity_type': entity_type,
        'limit': limit,
        'next_cursor': next_after,
        'items': items,
    }


def get_scene_entity(marker_id: int, entity_type: str, entity_id: int) -> dict:
    """查看标记现场中单个实体当时的完整版本。"""
    if entity_type not in LEDGER_ENTITIES:
        raise HTTPException(404, '未知实体类型')
    with Session() as s:
        marker = get_marker(s, marker_id)
        row = s.execute(text("""
            SELECT payload, commit_seq, change_type
            FROM entity_versions
            WHERE entity_type = :et AND entity_id = :eid AND commit_seq <= :horizon
            ORDER BY commit_seq DESC LIMIT 1
        """), {'et': entity_type, 'eid': entity_id, 'horizon': marker.horizon_seq}).first()
        if not row:
            raise HTTPException(404, '该标记时点不存在此实体（可能尚未写入）')
        payload, seq, chg = row
        return {
            'marker_id': marker_id,
            'entity_type': entity_type,
            'entity_id': entity_id,
            'commit_seq': seq,
            'change_type': chg,
            'entity': payload,
        }


# ---------- 旧数据回填 ----------

def _backfill_pending(s: OrmSession) -> dict:
    """统计每类实体中尚无任何版本的行（回填只补缺口，可断点续跑）。"""
    pending = {}
    for et, table in (('dataset', 'datasets'), ('plan', 'plans'), ('trace', 'traces')):
        rows = s.execute(text("""
            SELECT t.id FROM {table} t
            WHERE NOT EXISTS (
                SELECT 1 FROM entity_versions v
                WHERE v.entity_type = :et AND v.entity_id = t.id
            ) ORDER BY t.id
        """.format(table=table)), {'et': et}).all()
        pending[et] = [r[0] for r in rows]
    return pending


def backfill_needed() -> bool:
    with Session() as s:
        if get_state(s) != 'building':
            return False
        return any(_backfill_pending(s).values())


def backfill_gaps() -> dict:
    """补写所有缺版本的业务行（不看账本状态，供回填与种子脚本共用）。

    每行随小事务领取正常 commit_seq；可断点续跑、与在线写入并发安全。
    """
    from src.models.dataset import Dataset
    from src.models.plan import Plan
    from src.models.trace import Trace
    models = {'dataset': Dataset, 'plan': Plan, 'trace': Trace}
    done = {et: 0 for et in LEDGER_ENTITIES}
    with Session() as s:
        pending = _backfill_pending(s)
    for et, ids in pending.items():
        model = models[et]
        for start in range(0, len(ids), BACKFILL_BATCH):
            batch = ids[start:start + BACKFILL_BATCH]
            with Session() as s:
                for entity_id in batch:
                    row = s.get(model, entity_id)
                    if row is None:
                        continue
                    stage_version(s, et, row, 'I')
                    done[et] += 1
                commit_versioned(s)
    return done


def backfill_once() -> dict:
    """幂等回填：把建账前的旧行按小事务补写为初始版本，不阻塞在线保存。

    每行独立事务领取正常 commit_seq，因此回填与并发写入互不覆盖；
    回填完成且无缺口时，原子地把账本翻到 ready。
    """
    done = {et: 0 for et in LEDGER_ENTITIES}
    with Session() as s:
        if get_state(s) != 'building':
            return {'state': 'ready', 'backfilled': done}
    done = backfill_gaps()  # 全新库时缺口为空，立刻进入下方状态翻转
    # 复核无缺口后翻转状态（ORM 条件更新，断点续跑/多实例均幂等）
    with Session() as s:
        state_row = s.get(LedgerState, 1)
        if state_row is not None and state_row.state == 'building':
            gap = _backfill_pending(s)
            if not any(gap.values()):
                state_row.state = 'ready'
                s.commit()
    return {'state': ledger_overview()['state'], 'backfilled': done}
