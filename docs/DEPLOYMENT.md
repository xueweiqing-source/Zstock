# 部署指南

目标环境：Linux + nginx + Python 3.11（已在京东云 CentOS 7 验证）。其它发行版路径可能需微调。

## 一、系统要求

| 项 | 要求 |
|---|---|
| Python | 3.11+（推荐 `/usr/local/bin/python3.11`） |
| 内存 | ≥ 512MB 可用（systemd 已加 `MemoryMax=400M` 护栏） |
| nginx | 1.20+（反代子路径用） |
| 出网 | 需访问东财/同花顺/腾讯行情接口 |

## 二、一键部署

```bash
# 1. 代码放到 /var/www/stock-forecast
mkdir -p /var/www/stock-forecast
# （git clone 或 scp 上传）

# 2. 执行部署脚本
cd /var/www/stock-forecast
bash deploy/install.sh
```

脚本会依次完成：

1. 备份 nginx 配置（`znote.conf.bak_<时间戳>`）
2. 创建 venv 并安装依赖
3. **生成 `/etc/stock-forecast.env`（权限 600）**，首次安装时随机生成登录口令并打印
4. 安装并启动 systemd 服务 `stock-forecast`
5. 写入 nginx 的 `/forecast/` 反代 location
6. `nginx -t` 校验后 reload
7. 写入 crontab（每日 22:00）
8. 跑一次流水线生成首期报告
9. 验收（healthz / 登录跳转）

## 三、凭据管理（重要）

**代码不含任何真实凭据**。口令、SECRET_KEY、LLM Key 通过 `/etc/stock-forecast.env` 注入：

```bash
# /etc/stock-forecast.env（权限 600）
SF_ADMIN_USER=admin
SF_ADMIN_PASSWORD=你的登录口令
SF_SECRET_KEY=随机64位hex
# LLM 研判（可选）
#LLM_API_BASE=https://api.deepseek.com/v1
#LLM_API_KEY=sk-xxx
#LLM_MODEL=deepseek-chat
```

### 常用操作

```bash
# 查看当前口令
sudo cat /etc/stock-forecast.env

# 改口令
sudo vi /etc/stock-forecast.env     # 改 SF_ADMIN_PASSWORD
sudo systemctl restart stock-forecast

# 启用 LLM 研判
sudo vi /etc/stock-forecast.env     # 取消 LLM_* 注释并填入
sudo systemctl restart stock-forecast
```

> `SF_ADMIN_PASSWORD` 为空或为 `CHANGE_ME` 时应用**拒绝启动**，防止用已知口令上线。
> `SF_SECRET_KEY` 可省略，应用会自动生成并持久化到 `/var/www/stock-forecast/data/secret_key.txt`。

## 四、nginx 反代（子路径 /forecast/）

片段见 `deploy/nginx-forecast.conf`，核心三点：

```nginx
# 无尾斜杠时补上
location = /forecast {
    return 301 /forecast/;
}

location ^~ /forecast/ {
    proxy_pass http://127.0.0.1:8501/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Prefix /forecast;
    proxy_redirect off;          # ← 必须 off，前缀由 Flask 负责
}
```

### 子路径反代三要素（踩过坑）

1. **Flask 侧**：`webapp.py` 的 `_PrefixMiddleware` 注入 `SCRIPT_NAME`，让 `url_for` 生成 `/forecast/...`
   - 生产：`SF_URL_PREFIX=/forecast`（systemd 已设）
   - 本地调试：`SF_URL_PREFIX=`（空）
2. **nginx 侧**：必须 `proxy_redirect off`。若写成 `proxy_redirect / /forecast/`，会把已带前缀的 Location 二次拼接成 `/forecast/forecast/`
3. **`next` 白名单**：登录后只允许跳回 `/forecast` 前缀内路径，防止 open redirect 到同主机其它站点

**验收方式**：用 curl 跟随重定向逐跳读 `Location`，不要手写目标 URL 直打接口。

## 五、定时任务

```cron
0 22 * * * TZ=Asia/Shanghai /var/www/stock-forecast/venv/bin/python /var/www/stock-forecast/run_pipeline.py >> /var/log/stock-forecast-cron.log 2>&1
```

- 每日 22:00（Asia/Shanghai）执行
- 消息面窗口 = 当日 00:00 至执行时点
- 预测目标 = 次一交易日

> `crontab -l` 在空表时返回非零，合并 crontab 时务必用临时文件 + `|| true`，避免 `set -e` 中断脚本。

## 六、运维命令

```bash
# 服务
systemctl status stock-forecast
systemctl restart stock-forecast
systemctl stop stock-forecast

# 手动跑一期
/var/www/stock-forecast/venv/bin/python /var/www/stock-forecast/run_pipeline.py

# 日志
tail -f /var/log/stock-forecast-cron.log      # 流水线
tail -f /var/log/stock-forecast-error.log     # Web 错误
tail -f /var/log/stock-forecast-access.log    # Web 访问

# 健康检查
curl -sS http://127.0.0.1/forecast/healthz

# 数据库
sqlite3 /var/www/stock-forecast/data/forecast.db
> .tables
> SELECT run_id, market_trend, stock_count FROM runs ORDER BY generated_at DESC;
```

## 七、故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| 登录后跳到同主机其它站点 | `url_for` 没带前缀 / nginx `proxy_redirect` 重写 | 见「子路径反代三要素」 |
| 启动报「未设置 SF_ADMIN_PASSWORD」 | 环境文件缺失 | 创建 `/etc/stock-forecast.env` 后 restart |
| 报告页 502 | 后端没起来 | `systemctl status`，看 `/var/log/stock-forecast-error.log` |
| 港股池为空 | 东财成交额榜接口偶发空响应 | 系统会优雅降级，报告中标注；下期自动恢复 |
| 改了规则不生效 | 规则只影响之后的运行 | 属正常设计，历史报告不变 |
| 内存告警 | 流水线抓 280+ 只股票 | systemd 已限 400M，必要时调大 `MemoryMax` |

## 八、备份与恢复

```bash
# 备份（代码 + 数据 + 凭据）
tar czf zstock_backup_$(date +%F).tar.gz \
  /var/www/stock-forecast \
  /etc/stock-forecast.env

# 恢复
tar xzf zstock_backup_YYYY-MM-DD.tar.gz -C /
systemctl daemon-reload && systemctl restart stock-forecast
```

关键数据：
- `/var/www/stock-forecast/data/forecast.db` — 预测与回测记录（**核心资产**）
- `/var/www/stock-forecast/data/reports/` — 历史 HTML 报告
- `/var/www/stock-forecast/data/rules_config.json` — 自定义规则
- `/etc/stock-forecast.env` — 凭据

## 九、子路径挂载到其它前缀

如不想用 `/forecast/`：

```bash
# 1. 改 nginx location
vi /etc/nginx/conf.d/znote.conf     # 把 /forecast/ 换成你的前缀

# 2. 改环境变量
vi /etc/stock-forecast.env          # 或 systemd 里 SF_URL_PREFIX
#   SF_URL_PREFIX=/你的前缀

# 3. 重启
nginx -t && systemctl reload nginx
systemctl restart stock-forecast
```
