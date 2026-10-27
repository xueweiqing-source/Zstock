# 变更日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/) 思路记录变更。

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
