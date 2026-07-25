#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""聚合 LiteLLM + OpenRouter → OtterPad 专用模型能力表。

产出 model_capabilities.json：纯 model id 为 key（用户在 OtterPad 填的形态），
能力取两源 OR 并集，每个 model 标注适用的 OtterPad provider class。

OtterPad AgentApiProvider 仅 4 类：openai / anthropic / gemini / openAICompatible。
xAI（grok）虽在 OtterPad 内部升格走 OpenAI Responses，但此处仍归 openAICompatible
（App 侧 wireProtocol 再升格），与上游分类解耦。

仅用标准库，CI 无需安装依赖。
"""

import json
import sys
import urllib.request
from datetime import datetime, timezone

LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
OPENROUTER_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_PAGE_SIZE = 1000

# OtterPad 4 类 provider
OTTERPAD_PROVIDERS = ("openai", "anthropic", "gemini", "openAICompatible")

# ── 上游 provider → OtterPad provider class ──────────────────────────────
# litellm 的 litellm_provider 字段 / openrouter 的 author 前缀，归一到 4 类。
# OtterPad 的 openai class 专指「原生 OpenAI Responses 端点」；azure 同协议归 openai。
# openai_like/openrouter/custom_openai/text-completion-openai 等兼容层一律
# openAICompatible——避免 deepseek 等被误标 openai 后走 /v1/responses 触发 404。
_OPENAI_NATIVE = {"openai", "azure", "azure_ai", "azure_openai"}
_ANTHROPIC_LIKE = {"anthropic", "anthropic_text", "bedrock", "vertex_ai"}
# 注：bedrock/vertex_ai 同时承载 anthropic 与 gemini，下面按 model 名二次判定


def _otterpad_provider(litellm_provider: str | None, openrouter_id: str | None,
                       model_id: str | None) -> str:
    """把上游 provider 归一到 OtterPad 4 类。综合 litellm_provider、openrouter
    author（取 raw id 首段）与 model 名三方信号。"""
    p = (litellm_provider or "").lower().strip()
    author = (openrouter_id or "").split("/")[0].lower().strip()
    mid = (model_id or "").lower()
    # gemini
    if p == "gemini" or "gemini" in p or author == "gemini" or mid.startswith("gemini"):
        return "gemini"
    # anthropic：provider/author 含 anthropic，或 bedrock/vertex_ai 下 claude，或 model 名 claude
    if p in ("anthropic", "anthropic_text") or "anthropic" in p or author == "anthropic":
        return "anthropic"
    if p in _ANTHROPIC_LIKE and mid.startswith("claude"):
        return "anthropic"
    if mid.startswith("claude"):
        return "anthropic"
    # openai：原生 openai/azure，或 author=openai，或 model 名 gpt/o\d/omni/chatgpt
    if p in _OPENAI_NATIVE or author == "openai":
        return "openai"
    if mid.startswith(("gpt-", "o1", "o3", "o4", "omni", "chatgpt")):
        return "openai"
    # 其余（deepseek/dashscope/qwen/moonshot/volcengine/doubao/xiaomi/mimo/grok/
    # openai_like/openrouter/custom_openai/together/fireworks/groq/mistral/...）一律 openAICompatible
    return "openAICompatible"


def _pure_id(raw_id: str) -> str:
    """剥上游 provider 前缀，取最后一段作为纯 model id。

    litellm/openrouter 的 key 形如 'openrouter/xiaomi/mimo-v2.5-pro'、
    'vertex_ai/gemini-2.5-pro'、'bedrock/anthropic/claude-3-...'、'gpt-4o'。
    取最后一个 '/' 之后的部分。
    """
    return raw_id.rsplit("/", 1)[-1]


def _http_get_json(url: str, timeout: int = 60, headers: dict | None = None) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "modelcaps-builder/1.0",
                                                **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# ── LiteLLM ────────────────────────────────────────────────────────────────
def _pull_litellm() -> dict:
    print("[1/3] 拉取 LiteLLM model_prices_and_context_window.json ...", flush=True)
    data = _http_get_json(LITELLM_URL, timeout=120)
    if not isinstance(data, dict):
        raise RuntimeError("LiteLLM 返回非 object")
    out: dict[str, dict] = {}
    for raw_id, info in data.items():
        if raw_id.startswith("$"):  # $schema 等元字段
            continue
        if not isinstance(info, dict):
            continue
        pid = _pure_id(raw_id)
        if not pid:
            continue
        provider = _otterpad_provider(
            info.get("litellm_provider"), raw_id, pid)
        mode = info.get("mode")
        entry = {
            "imageInput": bool(info.get("supports_vision")),
            "imageOutput": mode == "image_generation",
            "tool": bool(info.get("supports_function_calling")),
            "reasoning": bool(info.get("supports_reasoning")),
            "embedding": mode == "embedding",
            "webSearch": bool(info.get("supports_web_search")),
            "providers": [provider],
        }
        _merge(out, pid, entry)
    print(f"      LiteLLM 条目: {len(out)} 纯 id", flush=True)
    return out


# ── OpenRouter ─────────────────────────────────────────────────────────────
def _pull_openrouter() -> dict:
    print("[2/3] 拉取 OpenRouter /api/v1/models ...", flush=True)
    out: dict[str, dict] = {}
    offset = 0
    total = None
    while True:
        url = f"{OPENROUTER_URL}?limit={OPENROUTER_PAGE_SIZE}&offset={offset}"
        data = _http_get_json(url, timeout=120)
        models = data.get("data", []) if isinstance(data, dict) else []
        if total is None:
            total = data.get("total_count") if isinstance(data, dict) else len(models)
        for m in models:
            raw_id = m.get("id") or ""
            pid = _pure_id(raw_id)
            if not pid:
                continue
            arch = m.get("architecture") or {}
            in_mod = arch.get("input_modalities") or []
            out_mod = arch.get("output_modalities") or []
            sp = m.get("supported_parameters") or []
            reasoning = m.get("reasoning")
            author = raw_id.split("/", 1)[0] if "/" in raw_id else None
            provider = _otterpad_provider(None, author, pid)
            entry = {
                "imageInput": "image" in in_mod,
                "imageOutput": "image" in out_mod,
                "tool": "tools" in sp,
                "reasoning": ("reasoning" in sp) or ("reasoning_effort" in sp)
                              or (reasoning is not None),
                "embedding": False,  # OpenRouter 不标 embedding
                "webSearch": "web_search_options" in sp,
                "providers": [provider],
            }
            _merge(out, pid, entry)
        if len(models) < OPENROUTER_PAGE_SIZE:
            break
        offset += OPENROUTER_PAGE_SIZE
        if total and offset >= total:
            break
    print(f"      OpenRouter 条目: {len(out)} 纯 id", flush=True)
    return out


def _merge(target: dict, pid: str, entry: dict) -> None:
    """同纯 id 多条 → 能力 OR 并集，providers 取并集去重保序。"""
    if pid not in target:
        target[pid] = {k: v for k, v in entry.items() if k != "providers"}
        target[pid]["providers"] = list(entry["providers"])
        return
    cur = target[pid]
    for k in ("imageInput", "imageOutput", "tool", "reasoning", "embedding", "webSearch"):
        cur[k] = cur.get(k, False) or entry.get(k, False)
    for p in entry["providers"]:
        if p not in cur["providers"]:
            cur["providers"].append(p)


# ── main ───────────────────────────────────────────────────────────────────
def main() -> int:
    models = _pull_litellm()
    or_models = _pull_openrouter()
    for pid, entry in or_models.items():
        _merge(models, pid, entry)
    print(f"[3/3] 合并去重后: {len(models)} 纯 id", flush=True)

    ordered = {k: models[k] for k in sorted(models)}
    doc = {
        "$schema": "https://cdn.jsdelivr.net/gh/Cyli00/modelcaps@main/"
                   "model_capabilities.schema.json",
        "version": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": ["litellm", "openrouter"],
        "providers": list(OTTERPAD_PROVIDERS),
        "models": ordered,
    }
    with open("model_capabilities.json", "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"写出 model_capabilities.json ({len(ordered)} 模型)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())