"""stock-forecast 配置中心

含：路径 / 鉴权 / 抓取参数 / 分析规则（可由 Web 配置页调整，落盘 JSON）
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = DATA_DIR / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# ---------- Web 鉴权 ----------
# 口令/密钥一律走环境变量，代码不落任何真实凭据。
# 生产用 /etc/stock-forecast.env（见 deploy/install.sh，权限 600）注入。
ADMIN_USER = os.environ.get("SF_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("SF_ADMIN_PASSWORD", "")
SECRET_KEY = os.environ.get("SF_SECRET_KEY", "")


def ensure_secret_key() -> str:
    """SECRET_KEY 未设置时生成随机值并持久化到 data/secret_key.txt（已 gitignore）"""
    global SECRET_KEY
    if SECRET_KEY:
        return SECRET_KEY
    key_file = DATA_DIR / "secret_key.txt"
    if key_file.exists():
        SECRET_KEY = key_file.read_text(encoding="utf-8").strip()
    if not SECRET_KEY:
        import secrets as _secrets
        SECRET_KEY = _secrets.token_hex(32)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        key_file.write_text(SECRET_KEY, encoding="utf-8")
        try:
            key_file.chmod(0o600)
        except OSError:
            pass
    return SECRET_KEY


def validate_security() -> None:
    """启动时校验安全配置，缺失则拒绝启动（避免用默认口令上线）"""
    if not ADMIN_PASSWORD or ADMIN_PASSWORD in ("CHANGE_ME", "changeme", "password"):
        raise SystemExit(
            "[安全] 未设置 SF_ADMIN_PASSWORD 环境变量。\n"
            "  生产：写入 /etc/stock-forecast.env（见 deploy/install.sh）\n"
            "  本地：export SF_ADMIN_PASSWORD=你的口令\n"
            "  代码不提供默认口令，拒绝以已知口令启动。"
        )

SESSION_LIFETIME_HOURS = 8
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 900

# ---------- 抓取 ----------
HTTP_TIMEOUT = 15
HTTP_RETRIES = 3
HTTP_BACKOFF = 1.2
REQUEST_INTERVAL = 0.12
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
TOP_N_A = 100
TOP_N_HK = 100

# ---------- 数据源标识 ----------
SRC_EASTMONEY = "东方财富"
SRC_THS = "同花顺"
SRC_TENCENT = "腾讯财经"
SRC_EM_NEWS = "东方财富7x24快讯"

# ---------- 分析参数 ----------
KLINE_DAYS = 250
MA_SHORT, MA_MID, MA_LONG = 20, 60, 120
MA_YEAR = 250

# ---------- 免责声明（固定文案，禁止改写） ----------
DISCLAIMER = (
    "免责声明：以上内容基于公开数据和量化分析，仅供参考，不构成投资建议。"
    "市场有风险，投资需谨慎。任何投资决策应结合个人风险承受能力、资金状况和投资目标独立判断，"
    "必要时咨询持牌专业机构。过往表现不预示未来收益。"
)

# ============================================================
# 分析规则（Web「规则与研判」页可改，落盘 data/rules_config.json）
# 默认值与首版代码一致，保证行为不变
# ============================================================

DEFAULT_RULES: dict = {
    # —— 三层权重与方向阈值 ——
    "w_fund": 0.35,
    "w_val": 0.30,
    "w_tech": 0.35,
    "dir_bull": 62.0,
    "dir_bear": 45.0,
    # —— 基本面 ——
    "fund_revenue_bands": [[20, 22], [5, 14], [0, 6], [-10, -6]],
    "fund_profit_bands": [[30, 22], [10, 14], [0, 6], [-1000, -10]],
    "fund_roe_bands": [[15, 22], [8, 14], [0, 6], [-1000, -10]],
    "fund_debt_ok": 50.0,
    "fund_debt_mid": 70.0,
    "fund_cf_pos": 0.05,
    "fund_verdict_good": 68.0,
    "fund_verdict_mid": 42.0,
    # —— 估值 ——
    "val_pe_cheap": 15.0,
    "val_pe_fair": 30.0,
    "val_pe_expensive": 60.0,
    "val_pe_cheap_score": 26.0,
    "val_pe_fair_score": 16.0,
    "val_pe_exp_score": 2.0,
    "val_pe_high_score": -12.0,
    "val_pb_cheap": 1.2,
    "val_pb_fair": 3.0,
    "val_pb_expensive": 6.0,
    "val_pos_low": 30.0,
    "val_pos_high": 70.0,
    "val_peg_good": 1.0,
    "val_peg_fair": 2.0,
    "val_verdict_cheap": 62.0,
    "val_verdict_mid": 38.0,
    # —— 技术面 ——
    "tech_ma20_w": 14.0,
    "tech_ma60_w": 13.0,
    "tech_ma120_w": 9.0,
    "tech_macd_w": 10.0,
    "tech_rsi_overbought": 70.0,
    "tech_rsi_oversold": 30.0,
    "tech_vol_confirm": 1.2,
    "tech_pos_low": 40.0,
    "tech_verdict_bull": 62.0,
    "tech_verdict_mid": 38.0,
    # —— 大盘 ——
    "breadth_healthy": 55.0,
    "breadth_weak": 42.0,
    "breadth_soft": 48.0,
    # —— 回测 ——
    "backtest_flat_pct": 1.0,
}

RULES_PATH = DATA_DIR / "rules_config.json"
APP_CONFIG_PATH = DATA_DIR / "app_config.json"


def load_rules() -> dict:
    merged = copy.deepcopy(DEFAULT_RULES)
    if RULES_PATH.exists():
        try:
            data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                merged.update(data)
        except (ValueError, OSError):
            pass
    return merged


def save_rules(rules: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RULES_PATH.write_text(
        json.dumps(rules, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def reset_rules() -> dict:
    if RULES_PATH.exists():
        RULES_PATH.unlink()
    return copy.deepcopy(DEFAULT_RULES)


# ---------- LLM 应用配置（Web 可改，落盘 JSON） ----------

DEFAULT_LLM = {
    "enabled": False,
    "api_base": "",
    "api_key": "",
    "model": "deepseek-chat",
}


def load_llm_config() -> dict:
    cfg = copy.deepcopy(DEFAULT_LLM)
    if APP_CONFIG_PATH.exists():
        try:
            data = json.loads(APP_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data.get("llm") or {})
        except (ValueError, OSError):
            pass
    if not cfg.get("api_base"):
        cfg["api_base"] = os.environ.get("LLM_API_BASE", "")
    if not cfg.get("api_key"):
        cfg["api_key"] = os.environ.get("LLM_API_KEY", "")
    if not cfg.get("model"):
        cfg["model"] = os.environ.get("LLM_MODEL", "deepseek-chat")
    cfg["api_base"] = (cfg.get("api_base") or "").rstrip("/")
    return cfg


def save_llm_config(llm: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg = {}
    if APP_CONFIG_PATH.exists():
        try:
            cfg = json.loads(APP_CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(cfg, dict):
                cfg = {}
        except (ValueError, OSError):
            cfg = {}
    cfg["llm"] = {
        "enabled": bool(llm.get("enabled")),
        "api_base": (llm.get("api_base") or "").rstrip("/"),
        "api_key": llm.get("api_key") or "",
        "model": llm.get("model") or "deepseek-chat",
    }
    APP_CONFIG_PATH.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
