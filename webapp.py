"""预测分析平台 Web：登录鉴权 + 报告中心 + 个股工作台 + 回测

安全措施：
- 口令以 PBKDF2-SHA256 哈希存储
- 服务端签名会话（HttpOnly + SameSite=Lax），有效期 8 小时
- 登录 CSRF token；失败 5 次锁定 15 分钟
- 安全响应头；路径穿越防护
- 反向代理子路径（/forecast/）修正
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, request, session, redirect, url_for, abort,
    render_template, render_template_string,
)
from werkzeug.security import generate_password_hash, check_password_hash

import config as C
import db as D

app = Flask(__name__)
C.validate_security()
app.secret_key = C.ensure_secret_key()

URL_PREFIX = os.environ.get("SF_URL_PREFIX", "/forecast").rstrip("/")

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # cookie 限定在本站子路径，避免与同主机 znote 会话串扰
    SESSION_COOKIE_PATH=(URL_PREFIX + "/") if URL_PREFIX else "/",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=C.SESSION_LIFETIME_HOURS),
    MAX_CONTENT_LENGTH=256 * 1024,
    TEMPLATES_AUTO_RELOAD=True,
)


class _PrefixMiddleware:
    """注入 SCRIPT_NAME，使 url_for 生成带 /forecast 前缀的路径"""

    def __init__(self, wsgi_app, prefix: str):
        self.wsgi_app = wsgi_app
        self.prefix = prefix

    def __call__(self, environ, start_response):
        if self.prefix and not environ.get("SCRIPT_NAME"):
            environ["SCRIPT_NAME"] = self.prefix
        return self.wsgi_app(environ, start_response)


if URL_PREFIX:
    app.wsgi_app = _PrefixMiddleware(app.wsgi_app, URL_PREFIX)
    app.config["APPLICATION_ROOT"] = URL_PREFIX

_PASSWORD_HASH = generate_password_hash(C.ADMIN_PASSWORD, method="pbkdf2:sha256")
_login_guard: dict = {}


@app.template_filter("from_json")
def _from_json(s):
    if not s:
        return []
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return []


def _client_ip() -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _is_locked(ip: str) -> bool:
    info = _login_guard.get(ip)
    return bool(info and info.get("locked_until", 0) > time.time())


def _record_fail(ip: str):
    info = _login_guard.setdefault(ip, {"fails": 0, "locked_until": 0.0})
    info["fails"] += 1
    if info["fails"] >= C.LOGIN_MAX_ATTEMPTS:
        info["locked_until"] = time.time() + C.LOGIN_LOCK_SECONDS
        info["fails"] = 0


def _record_ok(ip: str):
    _login_guard.pop(ip, None)


def _full_path() -> str:
    return (request.script_root or "") + request.path


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("sf_authed"):
            return redirect(url_for("login", next=_full_path()))
        exp = session.get("sf_exp", 0)
        if exp and time.time() > exp:
            session.clear()
            return redirect(url_for("login", next=_full_path()))
        return view(*args, **kwargs)
    return wrapped


@app.after_request
def _security_headers(resp):
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-XSS-Protection"] = "1; mode=block"
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; frame-ancestors 'none'"
    )
    return resp


# ---------- 登录页（独立模板，不走 base） ----------

LOGIN_PAGE = """
<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>登录 · 预测分析平台</title>
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:#f4f6f7;font-family:"Microsoft YaHei","PingFang SC",sans-serif;color:#1c2833}
.box{background:#fff;border:1px solid #e5e8e8;border-radius:12px;padding:36px 32px;width:360px;
box-shadow:0 4px 16px rgba(0,0,0,.06)}
h1{font-size:20px;margin:0 0 6px;color:#1a5276}
p.sub{color:#7f8c8d;font-size:13px;margin:0 0 22px}
label{display:block;font-size:13px;color:#5d6d7e;margin:12px 0 4px}
input{width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #d5dbdb;
border-radius:6px;font-size:14px}
button{width:100%;margin-top:20px;padding:11px;border:0;border-radius:6px;
background:#1a5276;color:#fff;font-size:15px;cursor:pointer}
button:hover{background:#154360}
.err{background:#fdedec;color:#c0392b;border-radius:6px;padding:9px 12px;font-size:13px;margin-bottom:10px}
.foot{margin-top:16px;font-size:11.5px;color:#aab7b8;text-align:center}
</style></head><body>
<div class="box">
  <h1>预测分析平台</h1>
  <p class="sub">热点股票池 · 三层分析 · 历史回测</p>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
  <form method="post" action="{{ url_for('login') }}">
    <input type="hidden" name="csrf_token" value="{{ csrf_token }}">
    <input type="hidden" name="next" value="{{ next }}">
    <label>账号</label><input type="text" name="username" autocomplete="username" required autofocus>
    <label>密码</label><input type="password" name="password" autocomplete="current-password" required>
    <button type="submit">登 录</button>
  </form>
  <div class="foot">仅供内部参考，不构成投资建议 · 市场有风险</div>
</div>
</body></html>
"""


@app.route("/login", methods=["GET", "POST"])
def login():
    ip = _client_ip()
    error = None
    if request.method == "POST":
        if _is_locked(ip):
            error = "登录尝试过于频繁，请 15 分钟后再试"
        else:
            token = request.form.get("csrf_token", "")
            if not session.get("csrf") or not hmac.compare_digest(session.get("csrf", ""), token):
                error = "会话校验失败，请刷新页面重试"
            else:
                username = (request.form.get("username") or "").strip()
                password = request.form.get("password") or ""
                if (
                    hmac.compare_digest(username, C.ADMIN_USER)
                    and check_password_hash(_PASSWORD_HASH, password)
                ):
                    _record_ok(ip)
                    session.clear()
                    session.permanent = True
                    session["sf_authed"] = True
                    session["sf_user"] = username
                    session["sf_exp"] = time.time() + C.SESSION_LIFETIME_HOURS * 3600
                    session["csrf"] = secrets.token_hex(16)
                    nxt = request.form.get("next") or ""
                    allowed = [p for p in (URL_PREFIX, request.script_root) if p]
                    if nxt.startswith("/") and not nxt.startswith("//"):
                        if not allowed or any(nxt == p or nxt.startswith(p + "/") for p in allowed):
                            return redirect(nxt)
                    return redirect(url_for("dashboard"))
                _record_fail(ip)
                error = "账号或密码错误"
    session["csrf"] = session.get("csrf") or secrets.token_hex(16)
    return render_template_string(
        LOGIN_PAGE, error=error, csrf_token=session["csrf"],
        next=request.args.get("next", ""),
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- 平台页面 ----------

@app.route("/")
@login_required
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    D.init_db()
    runs = D.list_runs(8)
    latest = runs[0] if runs else None
    dist, conf_dist = {}, {}
    if latest:
        preds = D.get_run_predictions(latest["run_id"])
        for p in preds:
            d = p.get("direction") or "—"
            dist[d] = dist.get(d, 0) + 1
            c = p.get("confidence") or "—"
            conf_dist[c] = conf_dist.get(c, 0) + 1
    llm_cfg = C.load_llm_config()
    if llm_cfg.get("enabled") and llm_cfg.get("api_base") and llm_cfg.get("api_key"):
        engine_label = f"LLM（{llm_cfg.get('model')}）+ 量化指标交叉验证"
        llm_state = f"已启用 · {llm_cfg.get('api_base')}"
    else:
        engine_label = "确定性规则（LLM 未启用）"
        llm_state = "未启用"
    return render_template(
        "dashboard.html",
        runs=runs, latest=latest,
        dist=dist, conf_dist=conf_dist,
        bt=D.backtest_summary(),
        engine_label=engine_label, llm_state=llm_state,
        active="dashboard", prefix=URL_PREFIX,
    )


@app.route("/runs")
@login_required
def runs():
    D.init_db()
    rows = D.list_runs(30)
    return render_template("runs.html", runs=rows, active="runs", prefix=URL_PREFIX)


@app.route("/backtest")
@login_required
def backtest():
    D.init_db()
    summary = D.backtest_summary()
    return render_template("backtest.html", summary=summary, active="backtest", prefix=URL_PREFIX)


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    saved = reset_done = False
    test_msg, test_ok = "", None
    rules = C.load_rules()
    llm_cfg = C.load_llm_config()

    if request.method == "POST":
        token = request.form.get("csrf_token", "")
        if not session.get("csrf") or not hmac.compare_digest(session.get("csrf", ""), token):
            test_msg, test_ok = "会话校验失败，请刷新页面重试", False
        else:
            action = request.form.get("action", "save")
            if action == "reset_rules":
                rules = C.reset_rules()
                reset_done = True
            elif action == "test_llm":
                # 用表单里的值临时测试（不保存）
                tmp = {
                    "enabled": True,
                    "api_base": (request.form.get("llm_api_base") or "").strip(),
                    "api_key": request.form.get("llm_api_key") or llm_cfg.get("api_key") or "",
                    "model": (request.form.get("llm_model") or "").strip() or "deepseek-chat",
                }
                test_ok, test_msg = _test_llm_connection(tmp)
            else:
                # 保存规则 + LLM
                def _f(name, default):
                    v = (request.form.get(name) or "").strip()
                    try:
                        return float(v)
                    except ValueError:
                        return default

                def _bands(name, default):
                    v = (request.form.get(name) or "").strip()
                    if not v:
                        return default
                    try:
                        import json as _j
                        arr = _j.loads(v)
                        if isinstance(arr, list) and arr and isinstance(arr[0], (list, tuple)) and len(arr[0]) >= 2:
                            return [[float(a), float(b)] for a, b in [(x[0], x[1]) for x in arr]]
                    except (ValueError, TypeError, IndexError):
                        pass
                    return default

                rules.update({
                    "w_fund": _f("w_fund", rules["w_fund"]),
                    "w_val": _f("w_val", rules["w_val"]),
                    "w_tech": _f("w_tech", rules["w_tech"]),
                    "dir_bull": _f("dir_bull", rules["dir_bull"]),
                    "dir_bear": _f("dir_bear", rules["dir_bear"]),
                    "fund_revenue_bands": _bands("fund_revenue_bands", rules["fund_revenue_bands"]),
                    "fund_profit_bands": _bands("fund_profit_bands", rules["fund_profit_bands"]),
                    "fund_roe_bands": _bands("fund_roe_bands", rules["fund_roe_bands"]),
                    "fund_debt_ok": _f("fund_debt_ok", rules["fund_debt_ok"]),
                    "fund_debt_mid": _f("fund_debt_mid", rules["fund_debt_mid"]),
                    "fund_cf_pos": _f("fund_cf_pos", rules["fund_cf_pos"]),
                    "fund_verdict_good": _f("fund_verdict_good", rules["fund_verdict_good"]),
                    "fund_verdict_mid": _f("fund_verdict_mid", rules["fund_verdict_mid"]),
                    "val_pe_cheap": _f("val_pe_cheap", rules["val_pe_cheap"]),
                    "val_pe_fair": _f("val_pe_fair", rules["val_pe_fair"]),
                    "val_pe_expensive": _f("val_pe_expensive", rules["val_pe_expensive"]),
                    "val_pb_cheap": _f("val_pb_cheap", rules["val_pb_cheap"]),
                    "val_pb_fair": _f("val_pb_fair", rules["val_pb_fair"]),
                    "val_pos_low": _f("val_pos_low", rules["val_pos_low"]),
                    "val_pos_high": _f("val_pos_high", rules["val_pos_high"]),
                    "val_peg_good": _f("val_peg_good", rules["val_peg_good"]),
                    "val_peg_fair": _f("val_peg_fair", rules["val_peg_fair"]),
                    "val_verdict_cheap": _f("val_verdict_cheap", rules["val_verdict_cheap"]),
                    "tech_ma20_w": _f("tech_ma20_w", rules["tech_ma20_w"]),
                    "tech_ma60_w": _f("tech_ma60_w", rules["tech_ma60_w"]),
                    "tech_ma120_w": _f("tech_ma120_w", rules["tech_ma120_w"]),
                    "tech_macd_w": _f("tech_macd_w", rules["tech_macd_w"]),
                    "tech_rsi_overbought": _f("tech_rsi_overbought", rules["tech_rsi_overbought"]),
                    "tech_rsi_oversold": _f("tech_rsi_oversold", rules["tech_rsi_oversold"]),
                    "tech_vol_confirm": _f("tech_vol_confirm", rules["tech_vol_confirm"]),
                    "tech_verdict_bull": _f("tech_verdict_bull", rules["tech_verdict_bull"]),
                    "breadth_healthy": _f("breadth_healthy", rules["breadth_healthy"]),
                    "breadth_weak": _f("breadth_weak", rules["breadth_weak"]),
                    "breadth_soft": _f("breadth_soft", rules["breadth_soft"]),
                    "backtest_flat_pct": _f("backtest_flat_pct", rules["backtest_flat_pct"]),
                })
                C.save_rules(rules)

                # LLM
                new_key = (request.form.get("llm_api_key") or "").strip()
                if not new_key:
                    new_key = llm_cfg.get("api_key") or ""
                llm_cfg = {
                    "enabled": request.form.get("llm_enabled") == "1",
                    "api_base": (request.form.get("llm_api_base") or "").strip(),
                    "api_key": new_key,
                    "model": (request.form.get("llm_model") or "").strip() or "deepseek-chat",
                }
                C.save_llm_config(llm_cfg)
                saved = True

    session["csrf"] = session.get("csrf") or secrets.token_hex(16)
    return render_template(
        "settings.html",
        rules=C.load_rules(),
        llm=C.load_llm_config(),
        saved=saved, reset_done=reset_done,
        test_msg=test_msg, test_ok=test_ok,
        csrf_token=session["csrf"],
        active="settings", prefix=URL_PREFIX,
    )


def _test_llm_connection(cfg: dict):
    """用给定配置做一次最小 LLM 调用，返回 (ok, message)"""
    if not cfg.get("api_base") or not cfg.get("api_key"):
        return False, "未填写 API Base 或 API Key，无法测试"
    try:
        import requests
        resp = requests.post(
            f"{cfg['api_base'].rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {cfg['api_key']}",
                     "Content-Type": "application/json"},
            json={"model": cfg.get("model") or "deepseek-chat",
                  "messages": [{"role": "user", "content": "ping"}],
                  "max_tokens": 5},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            model = (data.get("model") or cfg.get("model"))
            return True, f"LLM 连接成功（{model}）"
        return False, f"LLM 返回错误：HTTP {resp.status_code} — {resp.text[:160]}"
    except Exception as e:  # noqa: BLE001
        return False, f"LLM 连接失败：{e}"


@app.route("/stock/<market>/<code>")
@login_required
def stock(market: str, code: str):
    if market not in ("SH", "SZ", "HK") or not code.isalnum() or len(code) > 8:
        abort(404)
    D.init_db()
    history = D.get_stock_history(code, market, 12)
    if not history:
        abort(404)
    latest = history[0]
    pool = D.get_stock_pool_info(latest["run_id"], code, market)
    return render_template(
        "stock.html",
        code=code, market=market,
        name=latest.get("name") or "",
        latest=latest, history=history, pool=pool,
        active="runs", prefix=URL_PREFIX,
    )


@app.route("/report/<run_id>")
@login_required
def report(run_id: str):
    # run_id 只允许数字下划线
    if not run_id.replace("_", "").isdigit():
        abort(404)
    # 优先从数据库读（生产 MySQL），否则回退文件
    html_text = D.get_report_html(run_id)
    if not html_text:
        path = C.REPORTS_DIR / f"report_{run_id}.html"
        if not path.exists():
            abort(404)
        html_text = path.read_text(encoding="utf-8")
    bar = (
        f"<div style='position:sticky;top:0;z-index:99;background:#1a5276;color:#fff;"
        f"padding:10px 18px;font-family:sans-serif;font-size:13px;display:flex;"
        f"justify-content:space-between;align-items:center'>"
        f"<span><a href='{URL_PREFIX or ''}/runs' style='color:#d6eaf8'>← 报告中心</a>"
        f" &nbsp;|&nbsp; 期号 {run_id}</span>"
        f"<span><a href='{URL_PREFIX or ''}/backtest' style='color:#d6eaf8'>回测</a>"
        f" &nbsp;·&nbsp; <a href='{URL_PREFIX or ''}/logout' style='color:#d6eaf8'>退出</a></span>"
        f"</div>"
    )
    if "<body>" in html_text:
        html_text = html_text.replace("<body>", "<body>" + bar, 1)
    else:
        html_text = bar + html_text
    # 把个股代码链接到个股工作台（SH/SZ 6位、HK 5位）
    import re as _re

    def _link(m, mkt):
        code = m.group(1)
        return (f"<a style='color:#1a5276' href='{URL_PREFIX or ''}/stock/{mkt}/{code}'>"
                f"{code}.{mkt}</a>")

    html_text = _re.sub(
        r">(\d{6})\.(SH|SZ)<",
        lambda m: f">{_link(m, m.group(2))}<",
        html_text,
    )
    html_text = _re.sub(
        r">(\d{5})\.HK<",
        lambda m: f">{_link(m, 'HK')}<",
        html_text,
    )
    return html_text


@app.route("/healthz")
def healthz():
    return {"status": "ok", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


if __name__ == "__main__":
    D.init_db()
    app.run(host="127.0.0.1", port=8501, debug=False)
