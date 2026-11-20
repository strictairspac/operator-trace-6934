# 松原 · 分析算子执行剖面仪

松原数据库教学研发组 6 人用真实 Python scan/filter/hash join/group 算子，复查一条分析查询的每一步输出。

## 场景与模块
上游是设备可靠性课程的采样文件、传感器表和分析需求。过去在白板画算子、手动算中间行数，再把截图发给助教；重复键丢失、空结果误判、输入版本变化后无法复现实验是三个痛点。本站保存数据集与有界计划 DSL，worker 真执行并保存不可变快照/逐步摘要，下游讲师和同学只读复查。

数据集录入/编辑、算子计划编排、执行队列、算子剖面/JSON导出、课堂标记五个业务页面；管理员有审计。三个业务实体 datasets / plans / traces 均贯穿数据库、模型、schema、service、controller、route、前端api/store/page，并由时态账本（ledger_seq / entity_versions / markers / ledger_state）逐次提交版本化。

## 启动
```sh
cp .env.example .env
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```
前端 http://localhost:18244 ；后端 http://localhost:19244/docs ；PostgreSQL localhost:17744，trace / tracepass / operatortrace。结束 `docker compose down -v --remove-orphans` 会删本地数据。

| 角色 | 账号 | 页面与权限 | 动作 |
|---|---|---|---|
| admin | admin@operator.local | 全部含审计 | 复核执行人与完成事件 |
| operator | operator@operator.local | 创建/编辑/执行/导出 | 新建计划并交给worker |
| viewer | viewer@operator.local | 只读和导出 | 观察轨迹，写接口403 |

密码统一 `Trace2026!`。密码PBKDF2，JWT八小时；演示凭据和密钥仅限本地，部署前更换。

## 一天剧本与种子
1. 09:00 operator 登录读取「松原日班温升采样」。
2. 09:05 查看12传感器、240采样，北场/南场/试验间三分区。
3. 09:10 新建 `shift-20261117` 数据集，备注 `daily-readings-20261117.json`。
4. 09:15 保存高于50度→按sensor_id连接→按zone平均的计划。
5. 09:20 提交 `shift-20261117`，观察worker排队到完成。
6. 09:25 逐算子复查输入/输出行数与结果预览。
7. 09:30 导出 `trace-<id>.json`，viewer只读验证。
8. 10:00 admin 查看审计。

seed三账号、三个数据集（240行日班、空数据、重复右键）、三个对应计划。固定公式，无随机数；自然键补缺不覆盖用户修改，连续运行不新增。种子行自动补入时态账本，手工补跑 `python -m scripts.backfill_ledger`。

## 课堂标记与时态账本
助教要给一节课的现场做标记，日后翻看标记时已提交的采样、计划和剖面状态。实现是系统版本表 + 标记快照点，不是整库复制：

- 每次业务写入在同一事务内向单行 `ledger_seq` 领取全局连续 `commit_seq`（PG 行锁 `UPDATE ... RETURNING` 串行），并向只追加的 `entity_versions` 写一条该实体的增量版本。标记只保存一个 `horizon_seq` 整数，现场查询取 `commit_seq <= horizon` 的每实体最新版本（窗口函数），存储量随写入次数、与标记数量无关。
- 序号在提交前领取，顺序等于提交顺序：早开始却晚提交的写入拿到晚序号，混不进更早的标记；事务回滚则序号与版本一并消失，历史不留痕。
- 上线旧数据由后台线程按每50行一个小事务回填，期间不同数据集的并发保存照常提交；账本状态 `building（建账中）→ ready（可查）`，审计页实时显示版本化进度，可查后管理员才能创建标记。
- 标记现场按 `entity_id` 键集分页（`cursor`），查阅中断后带 cursor 回到原位置；标记之后的新写入被 horizon 挡住，同一标记反复读取结果不变。
- 接口：`GET /ledger/overview`（admin）、`POST/GET /markers`、`GET /markers/{id}/scene[/{type}[/{entity_id}]]`。设计细节见 `backend/migrations/002_ledger.md`。

## 算法与边界
这是教学内核模型，不是PostgreSQL执行器剖面。PostgreSQL真实保存业务元数据；Python worker真实计算表扫描、数值/相等筛选、构建哈希桶与内连接、Decimal累积分组。右表重复键保留倍数，空集合输出空集合。分组avg/sum保留6位小数，输出按规范JSON排序，SHA-256使用排序key紧凑JSON UTF-8；相同输入和计划结果摘要相同。每步输出输入/输出行数、耗时、明细、前5行与checksum。scan 的 input_rows=0 表示从源读取，detail.scanned_rows为扫描源行数；row_visits是扫描/过滤/哈希构建与探测/聚合各步逻辑行访问总和，不代表物理I/O。

DSL最多6步，首步仅scan readings；filter eq/gte/lte；hash_join仅readings.sensor_id=sensors.sensor_id且最多一次；group仅value的count/sum/avg。禁止eval、任意代码和任意SQL。最多100传感器、2000采样、10000连接输出行；超限失败，不保存部分结果。JSON非法、字段错误、非法算子、孤立引用、重复名有可恢复错误。任务使用Redis简单单消费者，进程崩溃后的running任务不自动重试，保留供人工复查后新建任务。

## 技术、目录与本地开发
Python3.11 / FastAPI / SQLAlchemy / psycopg / Redis / PostgreSQL16；原生 HTML/CSS/JS ES modules / nginx1.27。五服务frontend/backend/worker/db/redis均健康探针，命名卷数据库/Redis/共享产物。DB/Redis健康后启动backend，backend健康后启worker/frontend。

backend/src按models/schemas/services/controllers/routes/middlewares/config/constants/utils分层；backend/scripts/seed_demo.py与backfill_ledger.py；backend/migrations元数据建表版本（002为时态账本）。frontend/src按api/stores/pages/components/common/hooks/router/types/constants/utils分层。三共享组件table/status/feedback，两hooks forms/poll。角色/状态/算子/账本枚举在backend/src/constants/enums.py与frontend/src/constants/enums.js；权限/auth、worker状态、operator校验、前端状态展示使用相同枚举值。请求追踪和全局错误中间件、JWT授权、业务审计贯穿模块。

石墨黄铜工程蓝图视觉，双字体Noto Sans SC/Space Mono来自Google Fonts，离线回退；响应桌面/平板/手机。环境变量见.env.example：COMPOSE_PROJECT_NAME、三端口、JWT_SECRET、SEED_DEMO。DATABASE_URL/REDIS_URL由Compose提供。SEED_DEMO启动失败只记日志。

本地后端：pip install -r backend/requirements.txt，设置DATABASE_URL、REDIS_URL、JWT_SECRET，在backend运行uvicorn src.main:app --reload；前端需代理/api，不支持file://。截图、测试、日志和报告在批次根test-artifacts/gb-4105，源码无测试产物。License MIT。
