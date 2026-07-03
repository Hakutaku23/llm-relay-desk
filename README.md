# LLM Relay Desk

本地 LLM API 转发、提示词管理、Web 实时监视与原生桌面响应弹窗工具。

它可以把 Ollama 或 OpenAI 兼容上游包装成本地 API，并在不阻塞调用方的前提下，把模型正文和推理内容复制到监视界面。

## 功能

- OpenAI 兼容接口：`GET /v1/models`、`POST /v1/chat/completions`
- Ollama 原生接口：`/api/chat`、`/api/generate`、`/api/tags` 等
- 支持流式与非流式回复
- 系统提示词配置集、启用、导入和导出
- 上游地址、API Key、默认模型和超时在线配置
- Web 实时监视器：`/monitor/`
- 原生桌面响应弹窗，不打开浏览器页面
- 原生弹窗可从 `/ui/` 开启或关闭
- 响应完成后按设定秒数自动关闭，默认 30 秒
- 同时捕获正文和 `reasoning_content` / `reasoning` / `thinking`
- 多个并发请求分别显示，不混合内容
- 最近 60 条 Web 监视记录保存在进程内存中
- 监视器或弹窗异常不会暂停 API 请求

## 两种响应界面

### 原生桌面弹窗

原生弹窗由独立的 Python/Tk 进程负责：

1. API 收到聊天请求后创建独立窗口。
2. 流式片段到达时即时追加到窗口。
3. 正文和推理内容分别显示在两个页签。
4. 收到完整结束事件后开始倒计时。
5. 默认 30 秒后关闭，可在管理界面修改为 1～3600 秒。

管理入口：

```text
http://127.0.0.1:11434/ui/
转发配置 → 原生响应弹窗
```

关闭该开关后，当前原生弹窗会关闭，后续请求不再弹窗。API 转发和 Web 实时监视器继续工作。

原生弹窗不会调用 `focus_force`，也不会把其他程序最小化或暂停。Windows 下使用“显示但不激活”的方式尽量避免抢占输入焦点。

### Web 实时监视器

```text
http://127.0.0.1:11434/monitor/
```

Web 监视器适合查看最近请求、并发请求和内存历史。Windows 下也可以双击：

```text
打开实时响应窗口.bat
```

该脚本打开的是 Web 监视器，不是原生自动弹窗。

## 数据流

```text
第三方程序
    │
    │ OpenAI / Ollama API
    ▼
LLM Relay Desk
    ├── 原样返回上游响应给第三方程序
    ├── 非阻塞复制事件到 WebSocket 监视器
    └── 非阻塞复制事件到原生弹窗进程
```

WebSocket 队列和原生弹窗进程队列均为有界队列。队列满、窗口关闭、桌面会话不可用或弹窗进程异常时，会丢弃监视事件，而不是阻塞 API 调用方。

## 原生弹窗运行条件

- 需要 Python 自带 `tkinter`。
- 需要在已登录的图形桌面会话中运行。
- Windows 服务、远程无桌面会话、无图形界面的 Linux 服务器通常不能显示原生窗口。
- 原生窗口不可用时，API、管理页和 Web 监视器仍可正常运行。

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

`启动WebUI.bat` 只自动打开管理页。原生响应窗口平时隐藏，在收到 API 响应时自动出现。

## 页面地址

管理界面：

```text
http://127.0.0.1:11434/ui/
```

Web 实时监视器：

```text
http://127.0.0.1:11434/monitor/
```

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

只有经过本地代理的请求会出现在监视界面中。直接访问上游 API 的请求无法被本地服务捕获。

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

## 实时捕获范围

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

监视功能不会修改上游响应内容。代理返回 `X-Relay-Request-ID` 响应头，可用于对应 Web 监视器中的请求。

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

## 数据保存

```text
data/config.json
data/prompts.json
```

模型响应只保存在服务内存和窗口内存中，不写入硬盘。重启服务后 Web 监视历史消失。

监听地址和端口：

```text
.env
```

默认仅监听 `127.0.0.1`。不要在没有额外鉴权、防火墙和反向代理保护的情况下改为 `0.0.0.0`。
