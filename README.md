# LLM Relay Desk

本地 LLM API 转发、提示词管理与独立实时响应监视工具。

它可以把 Ollama 或 OpenAI 兼容上游包装成本地 API，并在不阻塞调用方的前提下，将模型正文和推理内容复制到独立监视窗口。

## 功能

- OpenAI 兼容接口：`GET /v1/models`、`POST /v1/chat/completions`
- Ollama 原生接口：`/api/chat`、`/api/generate`、`/api/tags` 等
- 支持流式与非流式回复
- 系统提示词配置集、启用、导入和导出
- 上游地址、API Key、默认模型和超时在线配置
- 独立实时响应窗口：`/monitor/`
- 同时捕获正文和 `reasoning_content` / `reasoning` / `thinking`
- 多个并发请求按 `request_id` 分离显示
- 最近 60 条请求保存在进程内存中
- 监视窗口断开、刷新、最小化或处理过慢时，不会暂停 API 请求

## 数据流

```text
第三方程序
    │
    │ OpenAI / Ollama API
    ▼
LLM Relay Desk
    ├── 原样返回上游响应给第三方程序
    └── 非阻塞复制响应片段到 WebSocket
                         │
                         ▼
                  独立实时响应窗口
```

监视器使用有界内存队列。队列满时会丢弃旧的监视事件并发送最新快照，而不是等待监视窗口，因此不会对 API 调用方产生反向阻塞。

## 安装

Python 3.10 及以上版本：

```cmd
python -m pip install -r requirements.txt
copy .env.example .env
python app.py
```

已有名为 `ollama` 的 Conda 环境时，也可以双击：

```text
安装依赖.bat
启动WebUI.bat
```

## 页面地址

管理界面：

```text
http://127.0.0.1:11434/ui/
```

独立实时响应窗口：

```text
http://127.0.0.1:11434/monitor/
```

Windows 下可双击：

```text
打开实时响应窗口.bat
```

脚本优先使用 Edge 或 Chrome 的应用窗口模式；找不到浏览器命令时会使用默认浏览器打开页面。

## 第三方软件配置

OpenAI Compatible：

```text
Base URL: http://127.0.0.1:11434/v1
API Key: 在管理界面中配置的本地 API Key
Model: 在管理界面中配置的模型名
```

Ollama：

```text
URL: http://127.0.0.1:11434
```

只有经过本地代理的请求会出现在实时响应窗口中。直接访问上游 API 的请求无法被本地监视器看到。

## 上游示例

### Ollama OpenAI 兼容接口

```text
上游 Base URL: http://127.0.0.1:11435/v1
上游 API Key: ollama
```

### OpenAI 兼容云服务

填写服务商提供的 Base URL。程序会追加：

```text
/models
/chat/completions
```

例如服务商要求访问 `https://example.com/v1/chat/completions`，则 Base URL 应填写：

```text
https://example.com/v1
```

## 实时监视器捕获范围

OpenAI 流式 SSE：

```text
choices[].delta.content
choices[].delta.reasoning_content
choices[].delta.reasoning
choices[].delta.thinking
```

OpenAI 非流式响应：

```text
choices[].message.content
choices[].message.reasoning_content
choices[].message.reasoning
choices[].message.thinking
```

Ollama 原生响应：

```text
message.content
message.thinking
response
thinking
```

监视器不会修改上游响应内容。代理返回 `X-Relay-Request-ID` 响应头，可用于对应监视窗口中的请求。

## 思考参数

代理不会自动添加或删除以下字段：

```text
reasoning_effort
reasoning
thinking
think
tools
tool_choice
```

客户端发送的字段会原样转发，上游模型决定其实际行为。

## 配置文件

```text
data/config.json
```

提示词文件：

```text
data/prompts.json
```

监听地址和端口：

```text
.env
```

默认仅监听 `127.0.0.1`。不要在没有额外鉴权、防火墙和反向代理保护的情况下改为 `0.0.0.0`。

## GitHub 仓库建议

```text
llm-relay-desk
```

建议仓库描述：

```text
Local LLM API relay, prompt manager, and non-blocking live response monitor.
```
