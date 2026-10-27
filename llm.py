"""LLM 研判模块：大盘叙事 + 个股观点（OpenAI 兼容接口）

设计：
- 通过环境变量接入 DeepSeek / Mimo / 任意 OpenAI 兼容服务
  LLM_API_BASE  例：https://api.deepseek.com/v1
  LLM_API_KEY   sk-xxx
  LLM_MODEL     例：deepseek-chat
- **未配置 key 时自动降级为规则叙事**（analysis.py 现有规则），系统照常运行
- LLM 输出被强制约束在 JSON 结构内，且只允许基于传入的数据；
  要求标注依据字段，禁止编造数据点位——与"防幻觉"红线一致
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import config as _cfg

log = logging.getLogger("llm")


def _llm_cfg() -> Dict:
    """取当前生效的 LLM 配置（优先 data/app_config.json，Web 可改）"""
    return _cfg.load_llm_config()


def llm_enabled() -> bool:
    c = _llm_cfg()
    return bool(c.get("enabled") and c.get("api_base") and c.get("api_key"))


def _api_base() -> str:
    return (_llm_cfg().get("api_base") or "").rstrip("/")


def _api_key() -> str:
    return _llm_cfg().get("api_key") or ""


def _model() -> str:
    return _llm_cfg().get("model") or "deepseek-chat"


def _chat(messages: List[dict], temperature: float = 0.3, max_tokens: int = 1600) -> Optional[str]:
    """调用 OpenAI 兼容 chat/completions"""
    if not llm_enabled():
        return None
    try:
        import requests
        resp = requests.post(
            f"{_api_base()}/chat/completions",
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "Content-Type": "application/json",
            },
            json={
                "model": _model(),
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=90,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        log.warning("LLM 调用失败，降级为规则叙事: %s", e)
        return None


def _extract_json(text: str) -> Optional[dict]:
    """从模型输出里提取 JSON 对象（容忍 ```json 围栏与前后杂文）"""
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


# ============================================================
# 大盘研判
# ============================================================

_MARKET_SYS = (
    "你是一名严谨的A股/港股市场分析师。你只能基于用户提供的数据写研判，"
    "禁止编造任何未给出的数据点位、事件或数字。允许做逻辑推演，但依据必须能追溯到给定数据。"
    "不预测具体点位，不给买卖/仓位指令。"
)

_MARKET_TMPL = (
    "请基于以下数据，对下周市场做研判，输出严格 JSON（不要其他文字）：\n"
    "{{\n"
    '  "trend": "偏多|震荡|偏空",\n'
    '  "confidence": "高|中|低",\n'
    '  "summary": "80-150字的核心判断",\n'
    '  "factors": ["影响因素1", "影响因素2", "影响因素3"],\n'
    '  "risks": ["风险提示1", "风险提示2"],\n'
    '  "key_watch": ["下周需跟踪的可验证信号1", "信号2"]\n'
    "}}\n\n"
    "=== 指数与广度 ===\n{market_data}\n\n"
    "=== 消息面情绪 ===\n{sentiment}\n\n"
    "=== 量化指标层结论（供交叉验证） ===\n{quant_view}\n"
)


def market_narrative(market_data: str, sentiment: str, quant_view: str) -> Optional[Dict]:
    """LLM 大盘研判。返回 dict 或 None（降级）"""
    prompt = _MARKET_TMPL.format(
        market_data=market_data, sentiment=sentiment, quant_view=quant_view
    )
    raw = _chat(
        [
            {"role": "system", "content": _MARKET_SYS},
            {"role": "user", "content": prompt},
        ],
        max_tokens=1200,
    )
    obj = _extract_json(raw)
    if not obj or "trend" not in obj:
        return None
    # 字段清洗，只接受合法枚举
    trend = obj.get("trend")
    if trend not in ("偏多", "震荡", "偏空"):
        return None
    conf = obj.get("confidence")
    if conf not in ("高", "中", "低"):
        conf = "中"
    return {
        "trend": trend,
        "confidence": conf,
        "summary": str(obj.get("summary") or "")[:300],
        "factors": [str(x) for x in (obj.get("factors") or [])][:6],
        "risks": [str(x) for x in (obj.get("risks") or [])][:6],
        "key_watch": [str(x) for x in (obj.get("key_watch") or [])][:6],
        "engine": f"llm:{_model()}",
    }


# ============================================================
# 个股研判（批量摘要，控制 token）
# ============================================================

_STOCK_SYS = (
    "你是一名严谨的股票分析师。只能基于给定数据判断相对下周的强弱倾向，"
    "禁止编造数据。不预测具体点位，不给买卖指令。"
    "输出严格 JSON 数组。"
)


def stock_narratives(stocks_data: str) -> Optional[List[Dict]]:
    """批量个股观点。stocks_data 为已格式化的指标摘要。返回 None 表示降级。"""
    prompt = (
        "以下是若干股票的量化指标（含基本面/估值/技术面三层评分）。"
        "请为每只股票给出下周相对强弱观点，输出严格 JSON 数组：\n"
        '[{"code":"...","direction":"看涨|看跌|震荡","confidence":"高|中|低","reason":"40-80字依据"}]\n'
        "只输出数组，不要其他文字。\n\n" + stocks_data
    )
    raw = _chat(
        [{"role": "system", "content": _STOCK_SYS}, {"role": "user", "content": prompt}],
        max_tokens=2400,
    )
    arr = None
    if raw:
        m = re.search(r"\[[\s\S]*\]", raw)
        if m:
            try:
                arr = json.loads(m.group(0))
            except json.JSONDecodeError:
                arr = None
    if not isinstance(arr, list):
        return None
    out = []
    for it in arr[:200]:
        if not isinstance(it, dict) or "code" not in it:
            continue
        d = it.get("direction")
        if d not in ("看涨", "看跌", "震荡"):
            continue
        c = it.get("confidence")
        if c not in ("高", "中", "低"):
            c = "中"
        out.append({
            "code": str(it.get("code")),
            "direction": d,
            "confidence": c,
            "reason": str(it.get("reason") or "")[:120],
        })
    return out or None
