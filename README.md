# Zstock · A股/港股预测分析平台

每日自动抓取 **TOP100 热点 A 股 / 港股**，用三层框架（基本面 → 估值 → 技术面）交叉验证，输出**次一交易日**市场预测，支持回测对账与规则可视化调参。

> **免责声明**：本项目输出内容基于公开数据和量化分析，仅供参考，不构成投资建议。市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力、资金状况和投资目标独立判断，必要时咨询持牌专业机构。过往表现不预示未来收益。

## 功能总览

| 模块 | 说明 |
|---|---|
| **热股池** | A股：东财人气榜 TOP100 ∪ 同花顺热股榜 TOP100；港股：东财成交额榜 TOP100 ∪ 涨幅榜 TOP50（热度代理口径，已如实标注）。按代码去重、合并来源、标注抓取时间 |
| **消息面** | 东财 7x24 快讯，窗口 = 当日 00:00 至执行时点；关键词规则打情绪分（透明可复核） |
| **大盘预测** | 指数趋势（MA20/60、5/20 日涨幅）+ 市场广度（涨跌家数）+ 消息面情绪 → 偏多 / 震荡 / 偏空，附影响因素与风险提示 |
| **个股预测** | 三层框架逐级交叉验证：基本面（值不值得买）→ 估值（贵不贵）→ 技术面（相对时机）。输出方向、置信度、依据；数据缺失只标缺口，**不估算填充** |
| **回测对账** | 预测结果落库，下次运行自动回填实际涨跌与命中率（按方向 / 置信度 / 市场统计） |
| **规则配置** | 43 项阈值可视化可调，Web 保存即生效（历史报告不变） |
| **LLM 研判** | 可插拔（OpenAI 兼容：DeepSeek / Mimo 等），未配置自动降级为规则叙事 |
| **Web 平台** | 总览 / 报告中心 / 个股工作台 / 回测与准确率 / 规则与研判 |

## 快速开始

```bash
# 1. 安装
python3.11 -m venv venv
./venv/bin/pip install -r requirements.txt

# 2. 设置凭据（代码不含默认口令）
export SF_ADMIN_PASSWORD=你的登录口令

# 3. 生成首期报告
./venv/bin/python run_pipeline.py

# 4. 启动 Web（本地调试设空前缀）
SF_URL_PREFIX= ./venv/bin/python webapp.py
# 打开 http://127.0.0.1:8501
```

生产部署见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

## 系统架构

```
┌────────────────────────────────────────────────────────┐
│  cron 每日 22:00（Asia/Shanghai）                       │
│    run_pipeline.py                                     │
│      ① 热股池   东财人气 + 同花顺热股 + 港股代理         │
│      ② 行情     腾讯批量快照（价/PE/PB）                 │
│      ③ 明细     K线(前复权250根) + 东财F10财务           │
│      ④ 消息面   东财7x24 + 关键词情绪分                  │
│      ⑤ 大盘     指数趋势+广度+情绪 → 规则/LLM 研判       │
│      ⑥ 回测     往期预测 vs 当前价 → 命中率回填          │
│      ⑦ 产出     HTML 报告 + SQLite 落库                 │
└────────────────────────────────────────────────────────┘
                         ↓
┌────────────────────────────────────────────────────────┐
│  Flask Web（gunicorn 127.0.0.1:8501）                   │
│    /dashboard  总览        /runs       报告中心          │
│    /stock/..   个股工作台   /backtest   回测与准确率      │
│    /settings   规则与研判（43 项阈值 + LLM 开关）        │
│    登录鉴权 · 会话管理 · CSRF · 限流 · 安全响应头        │
└────────────────────────────────────────────────────────┘
```

## 目录结构

```
Zstock/
├── config.py          # 配置：路径/鉴权/抓取参数/43 项规则默认值/凭据校验
├── scrapers.py        # 热股池、行情、K线、财务、消息面、指数广度
├── indicators.py      # MA / MACD / RSI / KDJ
├── analysis.py        # 三层打分 + 交叉验证 + 大盘预测 + 消息情绪
├── llm.py             # LLM 研判（OpenAI 兼容，可降级）
├── db.py              # SQLite 持久化 + 回测统计
├── report_gen.py      # HTML 报告生成（无 JS、内联样式、涨红跌绿）
├── webapp.py          # Flask 平台（登录鉴权 + 多页）
├── run_pipeline.py    # cron 主入口
├── templates/         # Jinja2 页面模板
├── deploy/            # systemd / nginx / crontab / 一键部署
├── docs/              # 部署指南 / 规则调参指南
└── data/              # 运行时数据（报告、SQLite、规则配置，不入库）
```

## 配置

### 环境变量（凭据，**代码不落任何真实密钥**）

| 变量 | 必填 | 说明 |
|---|---|---|
| `SF_ADMIN_PASSWORD` | **必填** | 登录口令。缺失时拒绝启动（避免用已知口令上线） |
| `SF_ADMIN_USER` | 可选 | 登录账号，默认 `admin` |
| `SF_SECRET_KEY` | 可选 | 会话签名密钥。缺省时自动生成并持久化到 `data/secret_key.txt` |
| `SF_URL_PREFIX` | 可选 | 反代子路径前缀，生产 `/forecast`，本地调试留空 |
| `LLM_API_BASE` | 可选 | OpenAI 兼容接口地址，如 `https://api.deepseek.com/v1` |
| `LLM_API_KEY` | 可选 | LLM 密钥。不配置则降级为规则叙事 |
| `LLM_MODEL` | 可选 | 模型名，默认 `deepseek-chat` |

生产环境通过 `/etc/stock-forecast.env`（权限 600，不入库）注入，见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

### 可调规则（43 项）

三层权重、方向阈值、基本面分档、估值阈值、技术面权重、大盘广度线、回测震荡阈值等，均可在 **Web「规则与研判」页**调整，保存即生效。参数含义与调参思路见 [docs/RULES.md](docs/RULES.md)。

### 分析口径（防幻觉硬约束）

1. **所有结论由显式规则推导**，每条依据在报告中展示加减分过程，可逐条复核。
2. **数据缺失只标「数据缺口」**，绝不估算填充、不编造数字。
3. **不预测具体股价点位，不提供买卖/仓位指令**；「方向」是相对次一交易日的强弱倾向。
4. 估值层未使用「历史 PE 分位」（公开接口不稳定），改用 PE 绝对水平 + 52 周股价位置 + PEG。
5. 52 周高低为**收盘口径**；区间涨跌幅用原始收盘价重算。
6. LLM 研判被硬约束：只允许基于传入数据推演，输出强制 JSON，调用失败自动回退规则。

## 数据源（均已实测）

| 数据 | 接口 | 口径 |
|---|---|---|
| A股人气 | `emappdata.eastmoney.com/stockrank/getAllCurrentList` | 人气榜 TOP100 |
| A股热股 | `dq.10jqka.com.cn/fuyao/hot_list_data/.../stock?stock_type=a` | 热股榜 TOP100 |
| 港股热点 | `push2.eastmoney.com/api/qt/clist/get`（fid=f6/f3） | 成交额/涨幅代理（东财人气榜不覆盖港股） |
| 行情/PE/PB | `qt.gtimg.cn/q=` | 批量快照（GBK） |
| 日线 | `web.ifzq.gtimg.cn/appstock/app/fqkline/get`（A）/ `hkfqkline`（港） | 前复权 250 根 |
| 财务 | `datacenter.eastmoney.com` `RPT_F10_FINANCE_MAINFINADATA` | ROE / 增速 / 负债率 / 现金流 |
| 快讯 | `np-listapi.eastmoney.com` `getNewsByColumns` | 7x24 |
| 指数广度 | `push2.eastmoney.com` `ulist.np` f104/f105/f106 | 涨跌家数 |

> 港股热点采用成交额/涨幅榜作为**热度代理口径**（东财人气榜接口不覆盖港股、同花顺港股接口 Param Error），报告中已如实标注。该接口偶发空响应，当期港股池为空时系统优雅降级。

## 安全

- 口令以 **PBKDF2-SHA256** 哈希存储，服务端签名会话（HttpOnly + SameSite=Lax，8 小时）
- 登录 CSRF、失败 5 次锁定 15 分钟、安全响应头（CSP / X-Frame-Options / nosniff）、路径穿越防护
- **代码不包含任何真实凭据**；口令、SECRET_KEY、LLM Key 全部走环境变量或 `data/`（已 gitignore）
- 仅 IP 直连无 SSL，建议受信网络使用；公网部署请加 HTTPS（需备案域名）

## 定时任务

```cron
0 22 * * * TZ=Asia/Shanghai /var/www/stock-forecast/venv/bin/python /var/www/stock-forecast/run_pipeline.py
```

每日 22:00 执行，消息面窗口 = 当日 00:00 至执行时点，预测**次一交易日**。

## 已知限制

- 港股基本面缺失（东财 F10 不覆盖）导致置信度偏低，属数据可得性限制，非模型问题
- 消息面情绪为关键词规则匹配，反映词频倾向，不构成语义理解或观点判断
- 东财港股成交额榜接口偶发空响应，当期港股池为空时系统优雅降级

## 文档

- [部署指南](docs/DEPLOYMENT.md) — 服务器部署、nginx 反代、cron、凭据管理
- [规则调参指南](docs/RULES.md) — 43 项参数含义与调参思路
- [变更日志](CHANGELOG.md)
