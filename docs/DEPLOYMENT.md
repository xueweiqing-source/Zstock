# 部署指南（Docker 模式）

目标环境：Linux + nginx + Docker（已在京东云 CentOS 7 + Docker 26 验证）。

## 一、系统要求

| 项 | 要求 |
|---|---|
| Docker | 20+（含 `docker compose`） |
| 镜像 | `python:3.11-slim`、`mysql:8.0`（可本地已有，无需外网） |
| 内存 | ≥ 700MB 可用（MySQL 调优后约 145MB + web 约 40MB） |
| nginx | 1.20+（反代子路径用） |
| 出网 | 需访问东财/同花顺/腾讯行情接口 |

## 二、一键部署

```bash
cd /var/www/stock-forecast
bash deploy/install-docker.sh
```

脚本依次完成：

1. 备份 nginx 配置
2. **生成 `.env`（权限 600）**，首次安装随机生成登录口令并打印
3. 构建 `zstock-web` 镜像
4. 启动 `zstock-web` + `zstock-mysql`（Compose 编排，含健康检查）
5. 初始化表结构
6. **自动迁移历史 SQLite 数据**（若有）
7. 写入 nginx `/forecast/` 反代
8. **停掉旧 systemd 服务**（改由 Docker 接管）
9. 写入 crontab（每日 22:00，容器内跑流水线）
10. 验收

## 三、凭据管理

所有凭据在项目根目录 `.env`（**已 gitignore，权限 600**）：

```bash
# .env
SF_ADMIN_USER=admin
SF_ADMIN_PASSWORD=登录口令
SF_SECRET_KEY=随机64位hex

# MySQL（容器初始化 + 应用连接共用）
DB_ROOT_PASSWORD=...
MYSQL_DATABASE=zstock
MYSQL_USER=zstock
MYSQL_PASSWORD=...

# LLM 研判（可选）
#LLM_API_BASE=https://api.deepseek.com/v1
#LLM_API_KEY=sk-xxx
#LLM_MODEL=deepseek-chat
```

### 常用操作

```bash
# 查看当前口令
sudo cat /var/www/stock-forecast/.env

# 改口令
sudo vi /var/www/stock-forecast/.env     # 改 SF_ADMIN_PASSWORD
docker compose restart web

# 启用 LLM 研判
sudo vi /var/www/stock-forecast/.env     # 取消 LLM_* 注释并填入
docker compose restart web
```

> `SF_ADMIN_PASSWORD` 为空或为弱口令时应用**拒绝启动**。

## 四、数据持久化与备份

**结构化数据 + 报告 HTML 全部在 MySQL**，`mysqldump` 一条命令即完整备份：

```bash
# 备份
docker compose exec -T mysql sh -c \
  'exec mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" zstock' > zstock_$(date +%F).sql

# 恢复
docker compose exec -T mysql sh -c \
  'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" zstock' < zstock_YYYY-MM-DD.sql
```

数据卷：`zstock_mysql_data`（Docker named volume）。

### 表结构

| 表 | 内容 |
|---|---|
| `runs` | 每期运行元数据 |
| `reports` | 报告 HTML + JSON 全文 |
| `predictions` | 个股预测 + 回测结果 |
| `quotes_snap` | 行情快照 |
| `pool_items` | 热股池 |
| `news_items` | 消息面快讯 |

> 应用目录下的 `data/` 仅存规则配置、LLM 配置、SECRET_KEY 及报告文件副本，可一并备份：

```bash
tar czf zstock_files_$(date +%F).tar.gz /var/www/stock-forecast/data /var/www/stock-forecast/.env
```

## 五、Docker 常用命令

```bash
cd /var/www/stock-forecast

docker compose ps                 # 状态
docker compose logs -f web        # Web 日志
docker compose logs -f mysql      # MySQL 日志
docker compose restart web        # 重启 Web
docker compose down               # 停（保留数据卷）
docker compose down -v            # 停并删除数据卷（⚠️ 删库）
docker compose build web          # 改代码后重建镜像
docker compose up -d web          # 重建后启动

# 手动跑一期流水线
docker compose exec web python run_pipeline.py

# 进容器调试
docker compose exec web bash

# MySQL 命令行
docker compose exec mysql mysql -uroot -p"$MYSQL_ROOT_PASSWORD" zstock
```

## 六、nginx 反代（子路径 /forecast/）

见 `deploy/nginx-forecast.conf`。核心三点：

```nginx
location = /forecast { return 301 /forecast/; }

location ^~ /forecast/ {
    proxy_pass http://127.0.0.1:8501/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Prefix /forecast;
    proxy_redirect off;          # ← 必须 off
}
```

### 子路径反代三要素（踩过坑）

1. **Flask 侧**：`webapp.py` 的 `_PrefixMiddleware` 注入 `SCRIPT_NAME`（生产 `SF_URL_PREFIX=/forecast`，本地留空）
2. **nginx 侧**：必须 `proxy_redirect off`。写成 `proxy_redirect / /forecast/` 会二次拼接成 `/forecast/forecast/`
3. **`next` 白名单**：登录后只允许跳回本站前缀内路径

**验收**：用 curl 跟随重定向逐跳读 `Location`，不要手写目标 URL 直打。

## 七、定时任务

```cron
0 22 * * * cd /var/www/stock-forecast && /usr/bin/docker compose exec -T web python run_pipeline.py >> /var/log/stock-forecast-cron.log 2>&1
```

> `crontab -l` 空表时返回非零，合并时用临时文件 + `|| true`。

## 八、从旧版（systemd + SQLite）迁移

`install-docker.sh` 已内置自动迁移。若需手动：

```bash
# 1. 备份
cp /var/www/stock-forecast/data/forecast.db /tmp/forecast.db.bak

# 2. 在容器里迁移
docker compose exec web python deploy/migrate_sqlite_to_mysql.py --sqlite data/forecast.db

# 3. 校验
docker compose exec web python -c "import db as D; print(D.list_runs(5))"
```

迁移脚本可重复执行（`INSERT IGNORE`，已存在的行跳过）。

## 九、故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| web 容器起不来 `bind: address already in use` | 旧 systemd 服务占着 8501 | `systemctl disable --now stock-forecast && docker compose up -d web` |
| 登录后跳到同主机其它站点 | 前缀没注入 / nginx proxy_redirect 重写 | 见「子路径反代三要素」 |
| 启动报「未设置 SF_ADMIN_PASSWORD」 | `.env` 缺失 | 跑 `install-docker.sh` 或手动建 `.env` |
| `MySQL server has gone away` | 内存不足被 OOM | 调低 `deploy/mysql-tuning.cnf` 的 `innodb_buffer_pool_size`，或升级内存 |
| 报告页 502 | web 容器没起来 | `docker compose logs web` |
| 港股池为空 | 东财成交额榜接口偶发空响应 | 系统优雅降级，下期自动恢复 |
| 改了规则不生效 | 规则只影响之后的运行 | 属正常设计 |

## 十、内存调优（2G 主机）

当前实测：MySQL 145MB + web 40MB ≈ 185MB。若内存吃紧：

```ini
# deploy/mysql-tuning.cnf
innodb_buffer_pool_size = 96M     # 128M → 96M
max_connections = 20              # 30 → 20
```

改后 `docker compose restart mysql`。

## 十一、子路径挂载到其它前缀

```bash
# 1. nginx location 换前缀
vi /etc/nginx/conf.d/znote.conf

# 2. compose 里 SF_URL_PREFIX 同步
vi docker-compose.yml             # SF_URL_PREFIX: /你的前缀

# 3. 重启
docker compose up -d web
nginx -t && systemctl reload nginx
```
