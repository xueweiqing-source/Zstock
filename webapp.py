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
    return jsonify({
        "latest": latest,
        "runs": runs,
        "distribution": dist,
        "confidence_dist": conf_dist,
        "backtest": D.backtest_summary(),
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


@app.route("/api/backtest")
@login_required
def api_backtest():
    D.init_db()
    return jsonify(D.backtest_summary())


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
