"""Zstock 管理平台后端：JSON API + Ant Design SPA

职责：
- 会话登录鉴权（API 返回 401 JSON，页面由 SPA 处理）
- 提供 Dashboard / 报告 / 个股 / 回测 / 设置 的 JSON 数据接口
- 静态托管 Ant Design Vue 前端（static/）
- 安全：口令哈希、CSRF、限流、安全响应头、路径穿越防护
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
    Flask, request, session, jsonify, send_from_directory, abort,
)
from werkzeug.security import generate_password_hash, check_password_hash

import config as C
import db as D
import scrapers as S
import backtest as B
import indicators as ind

app = Flask(__name__, static_folder="static", static_url_path="/static")
C.validate_security()
app.secret_key = C.ensure_secret_key()

URL_PREFIX = os.environ.get("SF_URL_PREFIX", "/forecast").rstrip("/")

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_PATH=(URL_PREFIX + "/") if URL_PREFIX else "/",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=C.SESSION_LIFETIME_HOURS),
    MAX_CONTENT_LENGTH=512 * 1024,
)

_PASSWORD_HASH = generate_password_hash(C.ADMIN_PASSWORD, method="pbkdf2:sha256")
_login_guard: dict = {}


class _PrefixMiddleware:
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


# ---------- 工具 ----------

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


def _authed() -> bool:
    if not session.get("sf_authed"):
        return False
    exp = session.get("sf_exp", 0)
    if exp and time.time() > exp:
        session.clear()
        return False
    return True


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _authed():
            return jsonify({"error": "unauthorized", "message": "请先登录"}), 401
        return view(*args, **kwargs)
    return wrapped


def csrf_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token") or ""
        if not session.get("csrf") or not hmac.compare_digest(session.get("csrf", ""), token):
            return jsonify({"error": "csrf", "message": "会话校验失败，请刷新页面"}), 403
        return view(*args, **kwargs)
    return wrapped


@app.after_request
def _security_headers(resp):
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    # 前端用本地 vendor（Vue/antd），无外链脚本
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self' data:;"
    )
    return resp


# ============================================================
# 认证 API
# ============================================================

@app.route("/api/login", methods=["POST"])
def api_login():
    ip = _client_ip()
    if _is_locked(ip):
        return jsonify({"error": "locked", "message": "登录尝试过于频繁，请 15 分钟后再试"}), 429

    data = request.get_json(silent=True) or request.form
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not (hmac.compare_digest(username, C.ADMIN_USER)
            and check_password_hash(_PASSWORD_HASH, password)):
        _record_fail(ip)
        return jsonify({"error": "invalid", "message": "账号或密码错误"}), 401

    _record_ok(ip)
    session.clear()
    session.permanent = True
    session["sf_authed"] = True
    session["sf_user"] = username
    session["sf_exp"] = time.time() + C.SESSION_LIFETIME_HOURS * 3600
    session["csrf"] = secrets.token_hex(16)
    return jsonify({"ok": True, "username": username, "csrf_token": session["csrf"]})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
def api_me():
    if not _authed():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"username": session.get("sf_user"), "csrf_token": session.get("csrf")})


# ============================================================
# 数据 API
# ============================================================

def _safe_json(s):
    if not s:
        return []
    try:
        v = json.loads(s)
        return v if isinstance(v, (list, dict)) else []
    except (ValueError, TypeError):
        return []


@app.route("/api/dashboard")
@login_required
def api_dashboard():
    D.init_db()
    runs = D.list_runs(8)
    latest = runs[0] if runs else None
    dist, conf_dist = {}, {}
    if latest:
        for p in D.get_run_predictions(latest["run_id"]):
            d = p.get("direction") or "—"
            dist[d] = dist.get(d, 0) + 1
            c = p.get("confidence") or "—"
            conf_dist[c] = conf_dist.get(c, 0) + 1
    llm_cfg = C.load_llm_config()
    llm_on = bool(llm_cfg.get("enabled") and llm_cfg.get("api_base") and llm_cfg.get("api_key"))
    # 市场指数概览（A股/港股/全球），合并进 dashboard 一次拿全
    try:
        market = S.fetch_market_overview()
    except Exception:  # noqa: BLE001
        market = {}
    return jsonify({
        "latest": latest,
        "runs": runs,
        "distribution": dist,
        "confidence_dist": conf_dist,
        "backtest": D.backtest_summary(),
        "market": market,
        "engine": {
            "llm_enabled": llm_on,
            "model": llm_cfg.get("model") if llm_on else None,
            "label": f"LLM（{llm_cfg.get('model')}）+ 量化指标交叉验证" if llm_on
                     else "确定性规则（LLM 未启用）",
        },
    })


@app.route("/api/runs")
@login_required
def api_runs():
    D.init_db()
    return jsonify({"runs": D.list_runs(50)})


@app.route("/api/report/<run_id>")
@login_required
def api_report(run_id: str):
    if not run_id.replace("_", "").isdigit():
        return jsonify({"error": "bad_request", "message": "无效期号"}), 400
    run = D.get_run(run_id)
    if not run:
        return jsonify({"error": "not_found", "message": "期号不存在"}), 404
    return jsonify({
        "run": run,
        "stocks": D.get_run_predictions(run_id),
        "market_factors": _safe_json(run.get("market_factors")),
        "market_risks": _safe_json(run.get("market_risks")),
    })


@app.route("/api/report/<run_id>/html")
@login_required
def api_report_html(run_id: str):
    if not run_id.replace("_", "").isdigit():
        abort(404)
    html = D.get_report_html(run_id)
    if not html:
        abort(404)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/api/stock/<market>/<code>")
@login_required
def api_stock(market: str, code: str):
    if market not in ("SH", "SZ", "HK") or not code.isalnum() or len(code) > 8:
        return jsonify({"error": "bad_request"}), 400
    D.init_db()
    history = D.get_stock_history(code, market, 12)
    if not history:
        return jsonify({"error": "not_found", "message": "无该标的记录"}), 404
    return jsonify({
        "code": code, "market": market,
        "name": history[0].get("name") or "",
        "latest": history[0],
        "history": history,
        "pool": D.get_stock_pool_info(history[0]["run_id"], code, market),
    })


@app.route("/api/stock/<market>/<code>/klines")
@login_required
def api_stock_klines(market: str, code: str):
    """K 线数据（画图用）

    口径优先级：qfq 前复权（实时）→ hfq 后复权（klines 表兜底）。
    返回 fq 字段标注口径，前端展示用。
    """
    if market not in ("SH", "SZ", "HK") or not code.isalnum() or len(code) > 8:
        return jsonify({"error": "bad_request"}), 400
    days = min(max(request.args.get("days", 120, type=int), 10), 500)

    rows: List[dict] = []
    fq_used = "qfq"

    # 1. 优先实时抓取 qfq（前复权，历史价与现价可比）
    try:
        import scrapers as S
        rows = S.fetch_kline(market, code, days=days, fq="qfq")
    except Exception:
        rows = []

    # 2. 实时失败或数据太少 → klines 表（hfq 后复权，回补/每日落库）
    if len(rows) < 10:
        try:
            db_rows = D.get_klines(code, market, limit=days)
            if db_rows:
                rows = db_rows
                fq_used = "hfq"
        except Exception:
            pass

    out = []
    for r in rows:
        out.append({
            "date": r.get("date", ""),
            "open": r.get("open"),
            "close": r.get("close"),
            "low": r.get("low"),
            "high": r.get("high"),
            "volume": r.get("volume"),
        })

    # 指标序列（可选）：与 rows 逐行对齐，口径同分析层（Cutler RSI / RSV→SMA KDJ）
    if out and request.args.get("indicators", "0") in ("1", "true", "yes"):
        ser = ind.compute_series(rows)
        for i, o in enumerate(out):
            o["rsi14"] = ser["rsi14"][i]
            o["macd_dif"] = ser["dif"][i]
            o["macd_dea"] = ser["dea"][i]
            o["macd_hist"] = ser["hist"][i]
            o["kdj_k"] = ser["k"][i]
            o["kdj_d"] = ser["d"][i]
            o["kdj_j"] = ser["j"][i]

    fq_label = {"qfq": "前复权", "hfq": "后复权", "": "不复权"}.get(fq_used, fq_used)
    return jsonify({"code": code, "market": market, "fq": fq_used,
                    "fq_label": fq_label, "days": days,
                    "indicators": bool(out and "rsi14" in out[0]), "rows": out})


@app.route("/api/backtest")
@login_required
def api_backtest():
    D.init_db()
    return jsonify(D.backtest_summary())


_pool_cache: dict = {}      # {since: (ts, report)} 全池回测结果 60s 缓存


@app.route("/api/backtest/pool")
@login_required
def api_backtest_pool():
    """全池预测跟随批量回测：等权组合 + 分方向前瞻 + 分标的（60s 内存缓存）"""
    # 默认 2023-01-01 起，防止全量回测 OOM（2G 机器扛不住 2020 至今全部数据）
    since = (request.args.get("since") or "").strip() or "2023-01-01"
    stop_loss = min(max(request.args.get("stop_loss", 0.0, type=float), 0.0), 50.0)
    weighted = request.args.get("weighted", "1") in ("1", "true", "yes")
    cache_key = f"{since}|{stop_loss}|{int(weighted)}"
    now = time.time()
    hit = _pool_cache.get(cache_key)
    if hit and now - hit[0] < 300:  # 5 分钟缓存，防止重复回测 OOM
        return jsonify(hit[1])
    keys, preds_map = B.load_pool_from_db(since)
    if not preds_map:
        return jsonify({"error": "no_predictions",
                        "message": "predictions 表暂无记录，先跑几期 pipeline"}), 404
    rep = B.pred_pool_report(keys, preds_map, since=since, stop_loss_pct=stop_loss,
                             include_weighted=weighted)
    if not rep["meta"]["n_stocks"]:
        return jsonify({"error": "no_data",
                        "message": "无可回测标的（对应 klines 历史不足，先跑 deploy/backfill_klines.py）"}), 404
    if len(_pool_cache) > 8:
        _pool_cache.clear()
    _pool_cache[cache_key] = (now, rep)
    return jsonify(rep)


@app.route("/api/backtest/stock/<market>/<code>")
@login_required
def api_backtest_stock(market: str, code: str):
    """单标的策略回测（ma / rsi / pred）：绩效 + 交易明细 + 资金曲线"""
    if market not in ("SH", "SZ", "HK") or not code.isalnum() or len(code) > 8:
        return jsonify({"error": "bad_request"}), 400
    strategy = (request.args.get("strategy") or "ma").lower()
    if strategy not in ("ma", "rsi", "pred"):
        return jsonify({"error": "bad_request", "message": "strategy 需为 ma/rsi/pred"}), 400
    fast = min(max(request.args.get("fast", 5, type=int), 2), 250)
    slow = min(max(request.args.get("slow", 20, type=int), 3), 250)
    rsi_period = min(max(request.args.get("rsi_period", 14, type=int), 2), 100)
    rsi_low = min(max(request.args.get("rsi_low", 30.0, type=float), 1.0), 49.0)
    rsi_high = min(max(request.args.get("rsi_high", 70.0, type=float), 51.0), 99.0)
    stop_loss = min(max(request.args.get("stop_loss", 0.0, type=float), 0.0), 50.0)
    since = (request.args.get("since") or "").strip()

    D.init_db()
    klines = D.get_klines(code, market, start=since)
    if len(klines) < 30:
        return jsonify({"error": "no_data",
                        "message": f"klines 仅 {len(klines)} 根，先跑 deploy/backfill_klines.py 回补"}), 404

    if strategy == "ma":
        positions = B.ma_cross_positions(klines, fast, slow)
        label = f"ma_cross({fast},{slow})"
    elif strategy == "rsi":
        positions = B.rsi_positions(klines, rsi_period, rsi_low, rsi_high)
        label = f"rsi({rsi_period},{rsi_low:g},{rsi_high:g})"
    else:
        with D.get_conn() as conn:
            preds = D._rows(D._exec(conn, """
                SELECT p.created_at, p.direction FROM predictions p
                WHERE p.code=? AND p.market=? ORDER BY p.created_at""", (code, market)))
        if not preds:
            return jsonify({"error": "no_predictions",
                            "message": "该标的无预测记录，pred 策略无信号"}), 404
        positions = B.pred_positions(klines, preds)
        label = f"pred_follow({len(preds)} 条预测)"

    result = B.backtest(klines, positions, stop_loss_pct=stop_loss)
    return jsonify({"code": code, "market": market, "strategy": strategy,
                    "label": label, **result})


@app.route("/api/indices")
@login_required
def api_indices():
    """仪表盘三分区市场概览：A股 / 港股 / 全球指数"""
    try:
        data = S.fetch_market_overview()
        return jsonify(data)
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": "fetch_failed", "message": f"获取指数数据失败: {e}"}), 502


@app.route("/api/settings", methods=["GET"])
@login_required
def api_settings_get():
    rules = C.load_rules()
    llm = C.load_llm_config()
    masked = dict(llm)
    key = masked.get("api_key") or ""
    masked["api_key_set"] = bool(key)
    masked["api_key"] = (key[:8] + "…" + "*" * min(8, max(0, len(key) - 12))) if len(key) > 12 else ("已配置" if key else "")
    return jsonify({"rules": rules, "llm": masked, "defaults": C.DEFAULT_RULES})


@app.route("/api/settings", methods=["POST"])
@login_required
@csrf_required
def api_settings_save():
    data = request.get_json(silent=True) or {}
    action = data.get("action", "save")

    if action == "reset_rules":
        rules = C.reset_rules()
        return jsonify({"ok": True, "reset": True, "rules": rules})

    if action == "test_llm":
        cur = C.load_llm_config()
        cfg = {
            "enabled": True,
            "api_base": (data.get("llm_api_base") or "").strip(),
            "api_key": data.get("llm_api_key") or cur.get("api_key") or "",
            "model": (data.get("llm_model") or "").strip() or "deepseek-chat",
        }
        ok, msg = _test_llm_connection(cfg)
        return jsonify({"ok": ok, "message": msg})

    rules = C.load_rules()
    for k, v in (data.get("rules") or {}).items():
        if k in C.DEFAULT_RULES:
            rules[k] = v
    C.save_rules(rules)

    llm_in = data.get("llm") or {}
    cur = C.load_llm_config()
    new_key = llm_in.get("api_key") or cur.get("api_key") or ""
    C.save_llm_config({
        "enabled": bool(llm_in.get("enabled")),
        "api_base": (llm_in.get("api_base") or "").strip(),
        "api_key": new_key,
        "model": (llm_in.get("model") or "").strip() or "deepseek-chat",
    })
    return jsonify({"ok": True, "rules": C.load_rules()})


def _test_llm_connection(cfg: dict):
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
            model = (resp.json().get("model") or cfg.get("model"))
            return True, f"LLM 连接成功（{model}）"
        return False, f"LLM 返回错误：HTTP {resp.status_code} — {resp.text[:160]}"
    except Exception as e:  # noqa: BLE001
        return False, f"LLM 连接失败：{e}"


# ============================================================
# SPA 静态托管
# ============================================================

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def spa(path: str):
    if path.startswith("api/") or path.startswith("static/"):
        abort(404)
    return send_from_directory("static", "index.html")


if __name__ == "__main__":
    D.init_db()
    app.run(host="127.0.0.1", port=8501, debug=False)
