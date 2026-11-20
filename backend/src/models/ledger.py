"""时态账本模型：全局提交序号、实体版本链、课堂标记。

设计要点：
- ledger_seq 是单行序号表，业务事务在提交前对该行做 UPDATE ... RETURNING
  领取连续序号；行锁把“领取序号”串行化，因此 commit_seq 的大小顺序严格等于
  事务提交顺序。早开始但晚提交的写入拿到晚序号，不会混进更早的标记。
- 回滚的事务连序号带版本一起消失（序列未使用会留下空洞，但版本行不存在），
  历史版本中看不到任何回滚写入。
- entity_versions 只追加增量版本，标记本身只存一个 horizon 序号，均不复制全库。
"""
from sqlalchemy import Column, Integer, BigInteger, String, JSON, DateTime, UniqueConstraint, Index, func
from src.config.database import Base


class LedgerSeq(Base):
    __tablename__ = 'ledger_seq'
    # 恒为单行，id=1；next_seq 保存下一个待领取的提交序号
    id = Column(Integer, primary_key=True)
    next_seq = Column(BigInteger, nullable=False, default=1)


class EntityVersion(Base):
    __tablename__ = 'entity_versions'
    id = Column(BigInteger, primary_key=True)
    # dataset / plan / trace
    entity_type = Column(String(20), nullable=False)
    entity_id = Column(Integer, nullable=False)
    # 全局提交序号，同一业务事务内的多条版本共享同一个序号
    commit_seq = Column(BigInteger, nullable=False)
    # I=新增 U=更新
    change_type = Column(String(1), nullable=False)
    # 该次提交后的实体完整内容（增量版本，仅一份，不复制全库）
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint('entity_type', 'entity_id', 'commit_seq', name='uq_version_entity_seq'),
        # 时间旅行主查询：某实体在某 horizon 下的最新版本
        Index('ix_version_lookup', 'entity_type', 'entity_id', 'commit_seq'),
        # 标记现场翻页：按类型列出 horizon 内全部实体的最新版本
        Index('ix_version_seq', 'entity_type', 'commit_seq'),
    )


class LedgerState(Base):
    __tablename__ = 'ledger_state'
    # 恒为单行 id=1；building=建账回填中，ready=可查、可创建标记
    id = Column(Integer, primary_key=True)
    state = Column(String(20), nullable=False, default='building')


class Marker(Base):
    __tablename__ = 'markers'
    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)
    note = Column(String(500), nullable=False, default='')
    # 创建标记的瞬间已提交的最大 commit_seq；标记之后的写入对该标记不可见
    horizon_seq = Column(BigInteger, nullable=False)
    created_by = Column(String(120), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
