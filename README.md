# stock-forecast · 下周市场预测定时任务系统

每周六、周日 22:00 自动执行：热点股票池抓取 → 消息面采集 → 三层分析交叉验证 → HTML 报告 → 鉴权站点展示。
部署于京东云 36.151.142.130，访问入口 `http://36.151.142.130/forecast/`。

## 功能

| 模块 | 说明 |
|---|---|
| 热股池 | 东方财富人气榜 TOP100 ∪ 同花顺热股榜 TOP100（A股）；东财成交额榜 TOP100 ∪ 涨幅榜 TOP50（港股，热度代理口径，接口已如实标注）；按代码去重、合并来源、标注抓取时间 |
| 消息面 | 东方财富 7x24 快讯。**周六采集当日、周日合并周六+周日**；关键词规则打情绪分（透明可复核） |
| 大盘预测 | 指数趋势（MA20/60、5/20 日涨幅）+ 市场广度（涨跌家数）+ 消息面情绪 → 偏多/震荡/偏空，附影响因素与风险提示 |
| 个股预测 | 三层框架逐级交叉验证：基本面（值不值得买）→ 估值（贵不贵）→ 技术面（相对时机），输出方向、置信度、依据；数据缺失标记缺口，不估算填充 |
| 报告页面 | 结构化 HTML：大盘预测、个股预测表（代码/名称/方向/置信度/理由）、数据来源与抓取时间、数据缺口、固定免责声明 |
| Web 鉴权 | 账号 `admin` / 密码 `Xiaoqing@123`；PBKDF2 口令哈希、服务端签名会话（8 小时）、登录 CSRF、失败 5 次锁定 15 分钟、安全响应头、路径穿越防护 |

## 目录

```
stock-forecast/
├── config.py          # 配置（账号、抓取参数、免责声明固定文案）
├── scrapers.py        # 热股池/行情/K线/财务/消息面/指数广度
├── indicators.py      # MA / MACD / RSI / KDJ
├── analysis.py        # 三层打分 + 交叉验证 + 大盘预测 + 情绪
├── report_gen.py      # HTML 报告生成（无 JS、内联样式、涨红跌绿）
├── webapp.py          # Flask 登录鉴权
├── run_pipeline.py    # cron 主入口
├── deploy/
│   ├── stock-forecast.service   # systemd（gunicorn, 127.0.0.1:8501）
│   ├── nginx-forecast.conf      # /forecast/ 反向代理片段
│   ├── crontab.txt              # 周六日 22:00
│   └── install.sh               # 一键部署
└── data/reports/                # 报告落盘（report_*.html / *.json）
```

## 定时任务

```
0 22 * * 6,0 TZ=Asia/Shanghai /var/www/stock-forecast/venv/bin/python /var/www/stock-forecast/run_pipeline.py
```

- 周六 22:00：消息面窗口 = 周六当日
- 周日 22:00：消息面窗口 = 周六+周日（近两日）
- 手动执行：`/var/www/stock-forecast/venv/bin/python /var/www/stock-forecast/run_pipeline.py`（窗口退化为近 48 小时）

## 数据源（均已实测）

| 数据 | 接口 | 口径 |
|---|---|---|
| A股人气 | emappdata.eastmoney.com/stockrank/getAllCurrentList | 人气榜 TOP100 |
| A股热股 | dq.10jqka.com.cn/fuyao/hot_list_data/.../stock?stock_type=a | 热股榜 TOP100 |
| 港股热点 | push2.eastmoney.com/api/qt/clist/get (fid=f6/f3) | 成交额/涨幅代理（东财人气榜不覆盖港股，同花顺港股接口 Param Error，已如实标注） |
| 行情/PE/PB | qt.gtimg.cn/q= | 批量快照，GBK |
| 日线 | web.ifzq.gtimg.cn/appstock/app/fqkline/get（A） / hkfqkline（港） | 前复权 250 根 |
| 财务 | datacenter.eastmoney.com RPT_F10_FINANCE_MAINFINADATA | ROE/增速/负债率/现金流 |
| 快讯 | np-listapi.eastmoney.com getNewsByColumns | 7x24 |
| 指数广度 | push2.eastmoney.com ulist.np f104/f105/f106 | 涨跌家数 |

## 分析口径说明（防幻觉约束）

1. **所有结论由显式规则推导**，每条依据在报告中展示加减分过程，可逐条复核。
2. **数据缺失只标"数据缺口"**，绝不估算填充——港股 F10 财务接口未覆盖的 148 只已标注缺口并降低置信度。
3. **不预测具体股价点位，不提供买卖/仓位指令**；"方向"是相对强弱倾向。
4. 估值层未使用"历史 PE 分位"（公开接口不稳定），改用 PE 绝对水平 + 52 周股价位置 + PEG，且已写入数据缺口说明。
5. 52 周高低为**收盘口径**；区间涨跌幅用原始收盘价重算。

## 运维

```bash
# 服务状态
systemctl status stock-forecast.service
# 手动生成报告
/var/www/stock-forecast/venv/bin/python /var/www/stock-forecast/run_pipeline.py
# 日志
tail -f /var/log/stock-forecast-cron.log /var/log/stock-forecast-error.log
# nginx 改动前必备份
cp -a /etc/nginx/conf.d/znote.conf /etc/nginx/conf.d/znote.conf.bak_$(date +%Y%m%d%H%M%S)
nginx -t && systemctl reload nginx
```

### 子路径反代注意事项（踩过的坑）

本应用挂在 `http://<host>/forecast/` 子路径，必须同时满足三点，否则登录会跑到同主机的 znote 站点：

1. **Flask 侧**：`webapp.py` 的 `_PrefixMiddleware` 注入 `SCRIPT_NAME`，让 `url_for` 生成 `/forecast/...`。生产由 systemd 的 `SF_URL_PREFIX=/forecast` 提供；本地直连调试设 `SF_URL_PREFIX=`（空）。
2. **nginx 侧**：必须 `proxy_redirect off`。若写成 `proxy_redirect / /forecast/`，会把已带前缀的 Location 二次拼接成 `/forecast/forecast/`。
3. **`next` 跳转白名单**：登录后只允许跳回 `/forecast` 前缀内路径，防止 open redirect 到 znote 根路径。

验收方式：用 curl 跟随重定向逐跳读 `Location`，不能手写目标 URL 直打接口。

## 已知限制

- 服务器仅 IP 直连（无域名无 SSL），登录凭据以明文 HTTP 传输；内网/受信网络使用，公网建议后续加 HTTPS。
- 港股基本面缺失导致大量个股置信度为"低"，属数据可得性限制，非模型问题。
- 消息面情绪为关键词规则匹配，反映词频倾向，不构成语义理解或观点判断。

---

**免责声明**：以上内容基于公开数据和量化分析，仅供参考，不构成投资建议。市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力、资金状况和投资目标独立判断，必要时咨询持牌专业机构。过往表现不预示未来收益。
