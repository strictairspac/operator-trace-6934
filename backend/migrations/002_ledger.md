# Schema v2 · 时态账本与课堂标记

在 v1（users / audits / datasets / plans / traces）基础上新增四张表，由
SQLAlchemy `Base.metadata.create_all` 幂等创建，旧库启动时自动补齐。

## ledger_seq（单行序号表，恒为 id=1）
| 列 | 说明 |
|---|---|
| next_seq | 下一个待领取的全局提交序号，初值 1 |

业务事务在**提交前**执行
`UPDATE ledger_seq SET next_seq = next_seq + 1 WHERE id = 1 RETURNING next_seq - 1`
领取序号。行锁使领取动作串行，因此 `commit_seq` 的大小顺序严格等于事务提交顺序：
早开始却晚提交的事务拿到晚序号，不会混入更早的标记。事务回滚时序号与版本行
一并回滚，历史中不留任何痕迹（未使用序号在正常运行下不会产生，回滚不占位）。

## entity_versions（只追加的实体版本链）
| 列 | 说明 |
|---|---|
| id | 版本主键 |
| entity_type | `dataset` / `plan` / `trace` |
| entity_id | 业务实体主键 |
| commit_seq | 全局提交序号；同一事务的多版本共享一个序号 |
| change_type | `I` 新增 / `U` 更新 |
| payload | 该次提交后的实体完整内容（一份增量版本，非整库副本） |
| created_at | 版本登记时间 |

约束与索引：
- `uq_version_entity_seq (entity_type, entity_id, commit_seq)` 唯一；
- `ix_version_lookup (entity_type, entity_id, commit_seq)` 服务单实体时间旅行；
- `ix_version_seq (entity_type, commit_seq)` 服务标记现场按类型列出。

时间旅行取某标记时点实体最新版本：
```sql
SELECT entity_id, payload FROM (
  SELECT entity_id, payload,
         row_number() OVER (PARTITION BY entity_id ORDER BY commit_seq DESC) rn
  FROM entity_versions
  WHERE entity_type = :type AND commit_seq <= :horizon
) t WHERE rn = 1;
```

## markers（课堂标记）
| 列 | 说明 |
|---|---|
| name | 标记名称，唯一 |
| note | 备注 |
| horizon_seq | 创建瞬间已提交的最大 commit_seq，之后写入对本标记不可见 |
| created_by | 创建人邮箱 |

标记行只保存一个整数序号，**不复制全库**；任意多标记共享同一条版本链。

## ledger_state（单行，id=1）
`building`（建账中：回填上线前旧数据）→ `ready`（可查：允许创建标记）。
回填按实体逐行、每 50 行一个小事务进行，与在线写入并发而不互相阻塞；
回填幂等（`NOT EXISTS` 找缺口，可断点续跑），确认无缺口后才翻为 `ready`。

## API
- `GET  /ledger/overview`（admin）账本状态与版本化进度，审计页展示建账中/可查
- `POST /markers`（admin，仅 ready）创建课堂标记
- `GET  /markers` / `GET /markers/{id}` 标记列表与详情
- `GET  /markers/{id}/scene` 现场总览（三类实体数量、剖面状态分布）
- `GET  /markers/{id}/scene/{entity_type}?limit=&cursor=` 键集分页翻看现场
- `GET  /markers/{id}/scene/{entity_type}/{entity_id}` 单实体当时版本
