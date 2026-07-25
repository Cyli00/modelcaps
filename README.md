# modelcaps

OtterPad 的模型能力规则集——按 **geosite 模式**维护：上游聚合一个权威预处理好的
能力表，App 后台订阅更新，不靠发版。

## 解决什么

OtterPad 原先用打包进 app 的 `model_capabilities.json`（正则从 model id 推断能力），
发版才更新，粒度粗（按家族），分不清同家族不同版本的能力差异。

本仓库提供一个 **per-model 精确能力表**（纯 model id 为 key），App 订阅它，配合
正则兜底，无需发版即可跟进新模型。

## 订阅 URL（jsdelivr CDN）

```
https://cdn.jsdelivr.net/gh/Cyli00/modelcaps@main/model_capabilities.json
https://cdn.jsdelivr.net/gh/Cyli00/modelcaps@main/regex_fallback.json
```

## 数据源

| 源 | 提供字段 |
|---|---|
| [LiteLLM](https://github.com/BerriAI/litellm) `model_prices_and_context_window.json` | vision / function_calling / reasoning / web_search / embedding / image_generation |
| [OpenRouter](https://openrouter.ai/api/v1/models) `architecture` + `supported_parameters` | input/output modalities / tools / reasoning / web_search_options |

合并策略：同纯 id 多条 → 能力 **OR 并集**。

## OtterPad provider class 映射

OtterPad `AgentApiProvider` 仅 4 类。`scripts/build.py` 把上游 provider 归一：

| 上游 | OtterPad class |
|---|---|
| `openai` / `azure` / model 名 `gpt-*`/`o1`/`o3`/`o4`/`omni`/`chatgpt` | `openai` |
| `anthropic` / `bedrock`+claude / `vertex_ai`+claude / model 名 `claude-*` | `anthropic` |
| `gemini` / `vertex_ai`+gemini / model 名 `gemini-*` | `gemini` |
| 其余（deepseek/dashscope/qwen/moonshot/volcengine/doubao/xiaomi/mimo/grok/openai_like/openrouter/...） | `openAICompatible` |

> `openai_like`/`openrouter`/`custom_openai` 等**兼容层一律 `openAICompatible`**——
> 否则被误标 `openai` 后走 `/v1/responses` 触发 404。xAI（grok）在 OtterPad App
> 侧 `wireProtocol` 升格走 Responses，数据层仍归 `openAICompatible`。

## 字段

| 字段 | 含义 |
|---|---|
| `imageInput` | 图片输入（vision） |
| `imageOutput` | 图片生成输出 |
| `tool` | 函数/工具调用 |
| `reasoning` | 推理/思考 |
| `embedding` | 嵌入模型 |
| `webSearch` | 联网搜索 |
| `providers` | 该 model 适用的 OtterPad provider class（参考用，跨 provider 取并集） |

## 本地构建

```bash
python scripts/build.py   # 纯标准库，无需安装依赖
```

读 `model_prices_and_context_window.json`(LiteLLM raw) + OpenRouter `/api/v1/models`，
写出 `model_capabilities.json`。

## 自动更新

`.github/workflows/update.yml` 每日 UTC 00:00 跑 `build.py`，有变化自动提交推送。
也可在 GitHub Actions 页手动触发（`workflow_dispatch`）。

## 正则兜底（regex_fallback.json）

per-model 表查不到的未知 model，回退正则推断（与 OtterPad 现状结构一致）。
手工维护，发版兜底。