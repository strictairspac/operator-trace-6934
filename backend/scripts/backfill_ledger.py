"""手动回填旧数据到时态账本（启动时通常已自动执行；此脚本供运维补跑）。

用法：docker compose exec backend python -m scripts.backfill_ledger
幂等：已有版本的行跳过，可断点续跑；完成后账本翻为 ready。
"""
import logging
from src.config.database import Base, engine, Session
from src.models.ledger import LedgerState
from src.services.ledger import ensure_ledger, backfill_needed, backfill_once, ledger_overview

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')


def main():
    Base.metadata.create_all(engine)
    ensure_ledger()
    with Session() as s:
        if s.get(LedgerState, 1) is None:
            s.add(LedgerState(id=1, state='building'))
            s.commit()
    if not backfill_needed():
        print('无需回填：', ledger_overview())
        return
    print('回填前：', ledger_overview())
    print('回填结果：', backfill_once())
    print('回填后：', ledger_overview())


if __name__ == '__main__':
    main()
