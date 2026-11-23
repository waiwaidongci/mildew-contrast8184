# 档案库房霉斑伴随条件筛查

比较有霉斑与未见霉斑的巡检，查出值得复核的库房条件。

浦桥区档案馆保管组，4 名保管员分班巡检三个库房，设施组负责风口和除湿设备。 保管员按架位登记可见霉斑、现场相对湿度、风口遮挡和设施报修状态，每周汇总成 CSV。筛查按有霉斑和未见霉斑分组比较单项及成对条件。保管组按巡检单号复核，设施组根据复核记录安排现场检查。

- 只数有霉斑的记录，容易把两个组都常见的条件列入排查清单。
- 在表格里逐项筛选时，很难同时看到两项条件共现的比例。
- 组间比例差异很大时，现场人员还得回到原表核对样本量和架位。

## 业务模块

| 模块 | 用途 |
|---|---|
| 库房值班总览 | 查阅业务口径、当班流程及最新运行。主管可以核对审计记录。 |
| 巡检台账 | 下载「浦桥档案库房巡检_20261116-20.csv」并核对字段。分析员可导入 UTF-8 CSV，保留数据指纹和原始行。 |
| 条件筛查 | 选择批次和参数并提交后台计算，可从运行列表追踪状态。 |
| 伴随模式与证据 | 查看业务指标、证据表和解释，通过来源链接回查数据。 |
| 现场复核单 | 查看待处理或已完成记录。复核主管可提交现场复核安排及依据。 |
| 排查清单交接 | 接收外站交接包，按包内声明的规则版本独立验算；只显示验算通过的报告，可查重算排名与两组命中单号。 |

## 启动

```bash
cp -n .env.example .env
docker compose config --quiet
docker compose up -d --build --wait
docker compose exec -T backend python -m scripts.seed_demo
```

浏览器访问 `http://127.0.0.1:18276`。FastAPI 文档位于 `http://127.0.0.1:19276/docs`，PostgreSQL 16 的本地端口为 `17776`。本批在带空格和中文的工作区验证启动。

| 角色 | 演示账号 / 密码 | 权限 |
|---|---|---|
| 复核主管 | `admin` / `admin-demo-2611` | 查看审计、导入数据、运行、签核。 |
| 分析员 | `analyst` / `analyst-demo-2611` | 导入数据、运行、查看结果和下载报告。 |
| 只读查看 | `viewer` / `viewer-demo-2611` | 可查看数据与运行结果并下载报告。 |

## 演示流程

1. 11 月 20 日 15:00，合并 11 月 16–20 日的架位巡检单，保存为「浦桥档案库房巡检_20261116-20.csv」。
2. 在「巡检台账」导入 40 条巡检，核对每条记录的架位、现场湿度和报修状态。
3. 在「条件筛查」以 65% 为高湿切分点，设置平滑量 0.5、正组命中至少 3 条、两组合计至少 5 条。
4. 用默认的 1.5 倍增长门槛运行，确认有霉斑 16 条、未见霉斑 24 条。
5. 在「伴随模式与证据」找到「高湿且风口遮挡」，核对正组命中 9 条、负组命中 1 条。
6. 用模式编号查巡检证据，复核 PQ-20261116-07 的湿度、风口和架位。
7. 在「现场复核单」登记待检查的架位与设施。
8. 外站按同一口径生成交接包后在「排查清单交接」提交，本站按包内规则版本独立验算；验算通过的报告才出现在交接列表。

## 计算口径

- 每个巡检单号计一条记录。见霉斑为正组，未见霉斑为负组。湿度达到切分点即计高湿，风口遮挡和报修待结均使用巡检时登记的状态。
- 枚举各字段的两种取值，以及来自不同字段的两项条件。成对条件须同时成立。原始支持度为组内命中数 k 除以该组巡检总数 n。
- 对命中和未命中各加同一平滑量 α，得平滑支持度 (k+α)/(n+2α)。增长倍数等于正组平滑支持度除以负组平滑支持度。任一组缺失时停止比较。
- 模式须达到正组原始命中下限、两组合计原始命中下限和增长倍数下限。负组零命中允许入选。结果优先按增长倍数降序，同倍数时正组命中多的优先。
- 结果用于确定复核顺序。库房差异、巡检日期和同一架位的重复巡检都可能影响关联，需结合湿度趋势和设施记录核查，无法据此判断霉斑成因。

## 规则版本与交接验算

- 计算口径按版本冻结在 `backend/src/domain/rules/`，当前版本由 `rules.CURRENT` 指定。口径调整须新增版本模块（如 `r2.py`），并在 `rules/__init__.py` 登记；已发布模块不改写。
- 每次运行在 `runs.rule_version` 记录所用版本，交接报告在 `handoff_reports.rule_version` 记录外站声明的版本。
- 「排查清单交接」接收 JSON 交接包，须带 `station`、`report_no`、`rule_version`、`params`、`rows`（原巡检）与 `claimed`（外站声明的 `ranking`、`positive_hits`、`negative_hits`）；`batch_key` 可省略，省略时按原巡检内容指纹生成。
- 本站始终按交接包声明的规则版本重算，排名或两组命中单号不一致即退回；本站升级规则后，旧交接包仍按原版得到同样的对账结果。
- 相同巡检内容只存一份（`handoff_batches.batch_key` 与 `checksum` 均唯一）；各站同号报告各自保留（`(station, report_no)` 唯一）；同站同号但内容变化即退回。
- 验算通过的批次先落库再落报告，中断后重跑同一条交接包会续用已验批次，不新增报告；验算不一致的交接包不入库，也不占用批次编号。
- 交接页面只列出验算通过的报告，报告详情展示按原版重算的排名与两组命中单号，便于逐条核对。

```json
{
  "station": "东馆",
  "report_no": "R-001",
  "batch_key": "PQ-20261116-20",
  "rule_version": "r1",
  "params": {"humidity_threshold": 65, "smoothing": 0.5, "min_positive_count": 3, "min_total_count": 5, "min_growth": 1.5},
  "rows": [{"inspection_id": "PQ-20261116-07", "...": "..."}],
  "claimed": {"ranking": [{"conditions": [["high_humidity", true], ["vent_blocked", true]], "positive_count": 9, "negative_count": 1}], "positive_hits": ["..."], "negative_hits": ["..."]}
}
```

## 本地开发

| 组件 | 实现 |
|---|---|
| 前端 | Nginx 与原生 HTML、CSS、JavaScript。`frontend/src/pages` 放页面，`components/common` 放共用表格、图表及表单。 |
| API | Python 3.11、FastAPI、SQLAlchemy。`backend/src/domain` 放本项目字段、业务计算和演示数据，`routes` 放接口，`models` 放表模型。 |
| 后台 | 独立 Python worker，通过 Redis 唤醒，从数据库租约领取计算，CSV 写入共享卷。 |
| 数据 | PostgreSQL 16 存储批次、运行与审计。`backend/scripts/seed_demo.py` 可安全重复执行。 |

改动前端后执行 `docker compose up -d --build frontend`。改动接口或算法后执行 `docker compose up -d --build backend worker`，再刷新浏览器。如需保留数据，停止时执行 `docker compose down`。使用 `docker compose down -v --remove-orphans` 会清除该项目的数据库、Redis 和报表卷。

`.env.example` 中的 `COMPOSE_PROJECT_NAME`、`FRONTEND_PORT`、`BACKEND_PORT`、`DB_PORT`、`APP_SUBNET` 控制项目隔离。`DB_PASSWORD`、`JWT_SECRET` 和 `SEED_DEMO` 为本机演示默认设置。后端 `constants/enums.py` 与前端 `src/constants/enums.js` 保持角色、运行状态和复核状态一致。项目许可证见 `LICENSE`。
