# 变更日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/) 思路记录变更。

## [1.8.0] - 2026-11-11

### 新增（自动化体检 + K 线指标副图）
- **`deploy/weekly_check.py` 每周策略绩效体检**：全池回测（恒带置信度加权，可选止损）→ JSON 存档 `data/checks/pool_check_*.json` + stdout 摘要与单行健康摘要（便于 grep/监控）；无数据时退出码 1。README 附 cron 示例（每周一 08:00）
- **K 线 API 指标序列**：`/api/stock/<m>/<c>/klines?indicators=1` 逐行返回 rsi14/macd_dif/macd_dea/macd_hist/kdj_k/kdj_d/kdj_j（口径与分析层一致：Cutler RSI、RSV→SMA KDJ），预热期为 null
- **个股 K 线图升级为四面板**：K线+均线 → 成交量 → MACD（柱+DIF/DEA）→ RSI（含 70/30 虚线参考），tooltip 带 RSI/DIF/DEA 值，dataZoom 四面板联动
- `backtest.py` 抽取 `load_pool_from_db()`（CLI / Web / 体检脚本三处复用，SQL 只留一份）

## [1.7.0] - 2026-11-11

### 新增（组合加权与风控）
- **引擎止损** `stop_loss_pct`（百分数单位，0=关）：
  - 触发口径：持仓中当日 low 触及止损价即成交——跳空低开按开盘价、否则按止损价
  - **止损冷却**：止损后同一信号不再入场，信号转空后恢复（防止"止损后立刻买回"）
  - 交易明细新增 `reason` 字段（signal/stop/open），CLI 与 Web 表格展示
- **置信度加权组合** `weighted_pool_curve`：看涨标的按置信度加权（confidence_score 显式优先，缺省 高/中/低 = 3/2/1），日频调仓含换手费用（佣金双边 + 卖出印花），收盘近似口径，与 sleeve 等权组合互为参照
- CLI：`--stop-loss 8`（=8% 止损）、`--weighted`（全池附带加权组合）；Web：全池/单标的止损输入、加权组合统计卡与曲线（橙线）
- API：pool/stock 坞点支持 `stop_loss`，pool 支持 `weighted`（默认开）

### 修复
- 回测交易 `ret_pct` 口径统一为百分数（未平仓标记此前漏乘 100，与已平仓/展示不一致）
- 全池 SQL 丢失 `FROM predictions` 与误查不存在的 `confidence_score` 列（1.6.0 引入的 500）

## [1.6.0] - 2026-11-11

### 新增（Web 策略绩效页）
- **「回测与准确率」页新增策略绩效区**：
  - **全池预测跟随**：一键生成等权组合 vs 买入持有基准（ECharts 资金曲线对比 + 分方向前瞻收益表 + 分标的超额表），支持起始日过滤，结果 60s 缓存
  - **单标的策略回测**：表单选 ma/rsi/pred 策略与参数，输出绩效统计 + 资金曲线 + 交易明细
- **API**：`GET /api/backtest/pool?since=` 与 `GET /api/backtest/stock/<market>/<code>?strategy=&fast=&slow=&rsi_*&since=`，参数校验与缺数据时的明确报错（指引跑回补/pipeline）

### 修复
- 表格列格式化改用 ant-design-vue 4 的 `#bodyCell` 插槽（原 `render` 回调为旧版 API，在 antd-vue 4 下被忽略——命中率三表的颜色/百分比格式实际未生效，现修复）

## [1.5.0] - 2026-11-11

### 新增（P3：全池预测跟随回测 + 等权组合）
- **`pred_pool_report`**：对 predictions 全池批量回测，回答"跟三层预测操作到底赚不赚钱"：
  - **等权 sleeve 组合模拟**：总资金均分各标的独立跑 pred_follow（复用单标的引擎保证成交/费用口径一致），组合曲线=按日合并（停牌缺日沿用前值、标的数据前记现金）；基准=同 universe 等权买入持有
  - **分方向前瞻收益**：看涨/看跌/震荡 预测后的实际次日（预测目标日）/5日收益与胜率
  - **分标的绩效表**：策略收益 / 买入持有 / 超额 / 交易 / 胜率，按超额降序
  - CLI：`python backtest.py --pool [--since ...] [--json ...]`
- `pred_pool_report(..., min_bars)` 样本门槛参数化

### 修复
- **`pred_positions` 生效时点**：原实现预测(P)自 P+1 根 K 线起生效、P+2 开盘才成交，**丢掉预测目标日本身**；改为预测(P)更新「最后一条日期 ≤ P 的 K 线」起的持仓意图、下一根开盘成交，恰好持有预测目标日。周末/节假日预测自动回溯到前一交易日（下一交易日开盘成交），同日多次预测按时间戳后者生效

## [1.4.0] - 2026-11-10

### 新增（量化能力：指标序列化 + 策略回测器）
- **`indicators.py` 序列化 API**：`rsi_series` / `kdj_series` / `compute_series`（与 klines 等长的对齐序列，样本不足处置 None）；`kdj()` 改为委托 `kdj_series` 保证标量/序列口径零漂移，`rsi()` 标量行为不变（简单平均/Cutler 口径，与序列版逐位一致）
- **`backtest.py` 策略回测器**（纯 Python，零新增依赖，适配低配主机）：
  - 执行口径防未来函数：t 日收盘信号 → **t+1 日开盘**成交，全仓进出、只做多
  - 费用模型：佣金双边 + 卖出印花税（默认万三/万五）+ 滑点 bps
  - 绩效报告：累计/年化收益、最大回撤、夏普、胜率、盈亏比、**买入持有基准对比**、交易明细
  - 内置策略：`ma_cross`（双均线）、`rsi`（均值回归，进出场状态机）、`pred`（**三层预测跟随**——持有最近一次"看涨"预测，次日起生效，直接检验预测框架的可交易性）
  - CLI：`python backtest.py --code 600519.SH --strategy ma|rsi|pred [--fast/--slow/--since/--json ...]`

### 修复
- **`get_klines` 的 `limit` 语义**：原为"最早 N 根"（ASC LIMIT），改为"**最近** N 根、升序输出"——修复 K 线前端兜底路径在库中数据多时取到陈旧数据的问题

## [1.3.0] - 2026-11-10

### 新增（量化底座：K 线历史落库）
- **`klines` 表**：按 `code+market+date` 幂等积累日线 OHLCV（MySQL/SQLite 双 schema），口径统一**后复权（hfq）**——后复权历史值不随新增除权事件变动，避免前复权"每次除权全量重算"导致的新旧口径混杂
- **每日增量落库**：pipeline 抓 K 线时同步以后复权重取一份入 `klines`（分析路径保持前复权不变，行为零变化）；落库失败仅告警不阻断主流程
- **`deploy/backfill_klines.py` 历史回补**：以 `end` 为游标向前翻页（实测腾讯 A 股 fqkline 认 start/end 区间、港股 hkfqkline 只认 end+count，统一 end 翻页两市通用；单次上限 640 根），支持 `--since/--codes/--market/--limit/--list`，幂等可重复执行
- `db.py` 新增 `upsert_klines` / `get_klines` / `kline_coverage`（覆盖体检）
- `scrapers.py` `fetch_kline` 支持 `fq`（qfq/hfq/''）与 `start/end` 参数，默认行为不变
- `migrate_sqlite_to_mysql.py` 表清单补上 `klines`（迁移不丢历史）

## [1.2.0] - 2026-10-27

### 变更
- **部署模式改为 Docker Compose**：`zstock-web`（Flask + gunicorn）+ `zstock-mysql`（mysql:8.0），替换原 systemd + 裸机 venv
- **数据层迁移到 MySQL**：结构化数据 + 报告 HTML 全部入库，`mysqldump` 一条命令即完整备份；保留 SQLite 兜底（未设 `DB_HOST` 时本地开发可用）
- **新增 `reports` 表**：报告 HTML/JSON 全文入库，报告页优先从库读取
- **MySQL 低内存调优**：`innodb_buffer_pool_size=128M`、关 performance_schema 等，适配 2G 主机（实测 MySQL 145M + web 40M）
- cron 改为 `docker compose exec web python run_pipeline.py`
- 移除 systemd 服务文件，新增 `install-docker.sh` 一键 Docker 部署

### 新增
- `Dockerfile`（python:3.11-slim）
- `docker-compose.yml`（web + mysql，健康检查，内存限额）
- `deploy/mysql-tuning.cnf`（MySQL 调优）
- `deploy/migrate_sqlite_to_mysql.py`（SQLite → MySQL 迁移，可重复执行）
- `deploy/install-docker.sh`（一键部署 + 自动数据迁移）

### 修复
- MySQL 8 `rank` 保留字导致建表失败（加反引号）

## [1.1.0] - 2026-10-27

### 新增
- **总览 Dashboard**（`/dashboard`）：最新期大盘判断、预测方向与置信度分布、回测速览、最近运行、系统状态
- **规则与研判配置页**（`/settings`）：43 项阈值可视化可调（三层权重、方向阈值、基本面分档、估值阈值、技术面权重、大盘广度线、回测阈值），保存即生效，支持一键恢复默认
- **LLM 研判配置**：Web 页可开关、填 API Base/Key/Model、一键测试连接；OpenAI 兼容（DeepSeek / Mimo 等），未配置自动降级为规则叙事
- **规则配置持久化**：`data/rules_config.json`，`analysis.py` 每次打分读盘，Web 改配置即刻生效

### 变更
- **改为每日分析**：cron 由「周六日 22:00」改为「每日 22:00」
- **预测目标由「下周」改为「次一交易日」**，报告标题、章节、口径全部同步改写
- **消息面窗口改为当日** 00:00 至执行时点
- **回测震荡阈值**默认由 3% 收敛到 1%（每日口径）
- 三层打分阈值参数化，默认值与 1.0 行为一致

### 安全
- **凭据脱敏**：代码不再包含任何真实口令/密钥
  - `SF_ADMIN_PASSWORD` 必填，缺失拒绝启动（避免用已知口令上线）
  - `SF_SECRET_KEY` 缺省时自动生成并持久化到 `data/secret_key.txt`
  - systemd 改用 `EnvironmentFile=/etc/stock-forecast.env`（权限 600，不入库）
  - `install.sh` 首次安装自动生成随机口令并打印

## [1.0.0] - 2026-10-19

### 新增
- **热股池抓取**：A股东财人气榜 TOP100 ∪ 同花顺热股榜 TOP100；港股东财成交额榜 TOP100 ∪ 涨幅榜 TOP50（热度代理口径），按代码去重合并、标注来源与抓取时间
- **三层分析框架**：基本面（值不值得买）→ 估值（贵不贵）→ 技术面（相对时机）逐层打分，交叉验证输出方向、置信度、依据
- **大盘趋势预测**：指数趋势（MA20/60、5/20 日涨幅）+ 市场广度（涨跌家数）+ 消息面情绪 → 偏多/震荡/偏空，附影响因素与风险提示
- **消息面情绪**：东财 7x24 快讯，关键词规则打分（透明可复核）
- **HTML 报告**：无 JS、内联样式、涨红跌绿；含大盘预测、个股预测表、数据来源与抓取时间、数据缺口、固定免责声明
- **回测对账**：预测结果落库，下次运行自动回填实际涨跌与命中率（按方向/置信度/市场统计）
- **Web 平台**：报告中心、个股工作台（三层评分卡 + 历史对账）、回测与准确率
- **登录鉴权**：PBKDF2 口令哈希、服务端签名会话（HttpOnly + SameSite=Lax）、登录 CSRF、失败 5 次锁定 15 分钟、安全响应头、路径穿越防护
- **部署**：systemd（gunicorn）+ nginx 子路径反代 + crontab 定时任务 + 一键部署脚本

### 数据源（均实测）
- 东方财富人气榜 / F10 财务 / 7x24 快讯 / 指数广度
- 同花顺热股榜
- 腾讯财经批量行情与前复权日线
