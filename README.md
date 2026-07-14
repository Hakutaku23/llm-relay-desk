# LLM Relay Desk

本地 LLM API 转发、提示词管理、Web 实时监视与原生桌面字幕浮层工具。

它可以把 Ollama 或 OpenAI 兼容上游包装成本地 API，并在不阻塞调用方的前提下，把模型响应复制到 Web 监视器和桌面字幕浮层。

## 功能

- OpenAI 兼容接口：`GET /v1/models`、`POST /v1/chat/completions`
- Ollama 兼容接口：`/api/chat`、`/api/generate`、`/api/tags` 等
- Ollama 客户端可自动适配 DeepSeek 等 OpenAI 兼容上游
- 支持流式与非流式回复
- 可选代理强制思考：调用方未指定时自动补充思考参数
- 可选调试日志：完整记录转发前请求与上游原始响应流
- 系统提示词配置集、启用、导入和导出
- 上游地址、API Key、默认模型和超时在线配置
- Web 实时监视器：`/monitor/`
- 无标题栏、置顶且不主动抢焦点的原生字幕浮层
- 独立“字幕设置”页签，集中管理位置、尺寸、颜色和关闭策略
- 文字与背景透明度独立控制，背景可设为 0 实现真正无填充
- Windows 下使用每像素 Alpha 字幕渲染，支持平滑抗锯齿、柔化阴影与可选文字描边
- 支持本机字体选择和左/中/右文字对齐；字体不存在时自动回退
- 字幕可直接拖动，松开鼠标后自动保存绝对坐标
- 屏幕上始终只有一个字幕框，新请求会清空并复用现有窗口
- 响应完成后按设定秒数自动关闭，默认 30 秒
- UI API 测试页默认使用真实 SSE 流式请求
- 捕获正文和 `reasoning_content` / `reasoning` / `thinking`
- 最近 60 条 Web 监视记录保存在进程内存中
- 监视器或字幕进程异常不会暂停 API 请求

## v4 后端结构

`app.py` 已缩减为应用创建和命令行启动入口，业务实现全部迁移到 `llm_relay_desk/` 包中：

```text
llm_relay_desk/
├── application.py          FastAPI 应用装配与生命周期
├── settings.py             环境变量、路径、版本和默认配置
├── runtime.py              配置库、提示词、监视器和字幕控制器聚合
├── api/
│   ├── dependencies.py     路由依赖获取
│   └── routes/             system/admin/monitor/openai/native 路由
├── config/                 配置规范化与校验
├── storage/                JSON 原子读写
├── debug_logging.py        上游请求与完整响应调试记录
├── prompts/                提示词配置与请求注入
├── monitoring/             请求事件、内存历史和 WebSocket 广播
├── desktop/                原生字幕控制器、Tk 窗口与 Win32 Alpha 渲染器
└── proxy/                  OpenAI/Ollama 转发、内容提取和流解析
```

模块依赖方向、扩展规范和职责边界见 [`docs/architecture.md`](docs/architecture.md)。根目录 `popup_window.py` 仅作为旧导入路径的兼容层。


## 上游协议与 Ollama 适配

“转发配置”中可以选择：

- `自动识别`：本机或私网 Ollama 优先走原生 `/api/*`；公网 HTTPS 与 `/v1` 服务使用 OpenAI 兼容适配。
- `OpenAI 兼容`：强制将本地 Ollama 路由转换到 `/models`、`/chat/completions` 和 `/embeddings`。适用于 DeepSeek、OpenAI 兼容云服务和多数推理网关。
- `Ollama 原生`：保持原有 `/api/*` 原样转发。

当客户端只能请求：

```text
GET  /api/tags
POST /api/chat
POST /api/generate
```

而上游只提供 OpenAI 兼容接口时，代理执行：

```text
/api/tags      → /models
/api/chat      → /chat/completions
/api/generate  → /chat/completions
/api/embed     → /embeddings
/api/embeddings → /embeddings
```

流式 `/chat/completions` SSE 会转换为 Ollama NDJSON。`content` 映射到 `message.content` 或 `response`，`reasoning_content` / `reasoning` / `thinking` 映射到 Ollama 的 `thinking` 字段。工具调用会在最终消息中转换为 Ollama `tool_calls`。

对于 DeepSeek，可填写：

```text
上游 Base URL: https://api.deepseek.com
上游协议: 自动识别 或 OpenAI 兼容
默认模型: DeepSeek 实际可用的模型 ID
```

第三方程序仍可只配置 Ollama 地址：

```text
http://127.0.0.1:11434
```

代理会负责协议转换。

## 原生字幕浮层

字幕浮层由独立的 Python/Tk 进程运行：

1. 默认只在识别到可显示的对话文本后打开浮层，纯事件和控制数据不会触发字幕。
2. 流式请求按 SSE/NDJSON 片段实时追加文字；非流式调用可由代理在内部转为流式生成。
3. 屏幕上只保留一个字幕窗口；新聊天开始时立即清空并复用该窗口。
4. 被新聊天替代的旧请求后续分片不会再写入字幕，避免并发串台。
5. 默认只显示最终正文；推理正文可选显示。
6. 收到结束事件后开始倒计时，范围为 1～3600 秒。

管理入口：

```text
http://127.0.0.1:11434/ui/
字幕设置 → 原生字幕浮层
```

可设置：

- 九宫格预设位置和 X/Y 偏移
- 鼠标拖动后的自定义绝对坐标
- 浮层宽度和高度
- 字体、字号、左/中/右对齐、文字透明度和背景透明度（分别设置）
- 背景、正文、辅助文字、边框和错误提示颜色
- 背景透明度可设为 0；文字阴影和文字描边分别独立设置
- 字幕内容模式：仅提取对话字段，或显示模型全部文本
- 可配置顶层 JSON 对话字段名称，默认 `response`、`statement`、`dialogue`、`speech`
- 是否把普通自然语言输出作为对话字幕
- 是否将客户端非流式调用在内部转为上游流式生成
- 是否显示推理文本（“仅对话字段”模式不会把推理过程作为对话正文）
- 是否启用鼠标穿透（安全默认值为关闭）
- 完成后的自动关闭秒数

字体输入框通过 `GET /admin/subtitle-fonts` 读取服务所在电脑的已安装字体。也可以手动输入字体族名称；找不到对应字体文件时，桌面渲染器会使用安全回退字体，不会中断字幕显示。

颜色主题区域的高保真预览通过 `POST /admin/subtitle-preview.png` 调用与桌面字幕相同的 Pillow 合成器。预览不再只依赖浏览器 CSS 近似，因此正文颜色、字体、文字透明度、背景透明度、阴影和可选描边与实际字幕保持一致。该接口只渲染图片，不保存尚未提交的表单配置。

“进入定位模式”会发送流式预览并临时关闭鼠标穿透。拖动并松开后，桌面进程通过独立 IPC 把坐标写回 `data/config.json`，自动切换到 `custom` 位置并恢复配置状态；60 秒未完成时也会自动退出定位模式。

Windows 下使用无标题栏工具窗口和“显示但不激活”方式，不调用 `focus_force`，不会主动最小化、暂停或切换调用 API 的程序。字幕先完成首次绘制，再延迟启用鼠标穿透；流式正文和推理更新会触发原生重绘。鼠标穿透依赖 Windows 扩展窗口样式；其他系统会保留该配置，但不保证具备相同的系统级穿透效果。

4.4.0 起，Windows 字幕改用 `UpdateLayeredWindow` 每像素 Alpha 合成，不再使用颜色键透明。文字与背景拥有独立 Alpha：背景透明度设为 `0` 时只显示字幕，文字边缘仍保持平滑抗锯齿；无背景模式自动隐藏状态栏，默认采用左对齐，也可切换为居中或右对齐，并使用可选柔化阴影提高复杂画面下的可读性。文字描边默认关闭，可单独设置颜色和宽度。定位模式会临时显示一层淡色拖动区域，保存位置后立即恢复用户设置。非 Windows 平台会降级为普通 Tk 窗口，无法保证文字与背景 Alpha 完全独立。

## 非流式调用的实时字幕

字幕设置中的“非流式调用内部转为流式生成”默认开启。调用软件即使固定发送：

```json
{
  "stream": false
}
```

代理仍会对支持流式的上游发送 `stream:true`，逐片段更新监视器和字幕，完成后再聚合为调用方原本要求的非流式 JSON。调用软件看到的接口和响应形态不变。

该机制覆盖：

- OpenAI `/v1/chat/completions`
- Ollama 原生 `/api/chat`、`/api/generate`
- Ollama 客户端到 DeepSeek/OpenAI 上游的协议适配链路

该选项本身只改变代理与上游之间的传输方式。需要在调用方未指定时自动开启思考，可同时启用“转发配置”中的“代理强制思考”。上游不支持流式时会自动回退为普通非流式响应。

`/ui/` 中的 API 测试页仍可直接使用真实 SSE 流式请求。

## 结构化输出的字幕提取

在“仅提取对话字段”模式下，模型返回 JSON 时只显示指定顶层字段。例如：

```json
{
  "statement": "愿商队蹄声不绝。",
  "action": "accept_trade_agreement",
  "reason": "通商可丰盈国库"
}
```

字幕只显示 `statement`，不会显示 action、reason 或其他控制参数。若 JSON 中没有任何配置的对话字段，则该请求不会创建字幕窗口。模型直接返回普通自然语言时，可通过“普通文本作为对话显示”继续正常展示。



## 4.9.1 完整响应调试日志

“转发配置”中的调试日志默认关闭。开启后，每个实际上游请求生成一个独立的格式化 `.json` 文件，默认目录为：

```text
DATA_DIR/debug_logs
```

相对路径以 `DATA_DIR` 为基准，也可以配置本机绝对路径。日志结构为：

```json
{
  "client_request": {},
  "upstream_request": {},
  "upstream_response": {
    "status_code": 200,
    "format": "openai-sse",
    "body": {},
    "stream_events": 225,
    "response_bytes": 12345,
    "response_sha256": "..."
  }
}
```

`client_request` 保存调用软件发给后端的原始请求；`upstream_request` 保存提示词注入、强制思考、内部流式切换和协议适配完成后，真正发送给模型的请求。

上游流式响应不会再按分片写成数百条 JSONL 事件。代理会在请求期间使用临时缓冲区累计响应，超过 1 MiB 时自动回落到磁盘，并在完成后统一写入 `upstream_response.body`：

- OpenAI SSE 合并为一个完整 `chat.completion`，正文、推理内容、工具调用、finish reason 和 usage 保留在最终对象中。
- Ollama NDJSON 合并为一个完整 Ollama 响应，分片正文与 thinking 字段按顺序拼接。
- 普通 JSON 直接保存为完整响应对象。
- 无法识别的媒体类型保存为完整原始文本。

`stream_events` 仅记录解析到的流事件数量，`transport_chunks` 记录网络传输分片数量，不再把每个分片写入独立日志行。日志还保留响应状态、响应头、总字节数和 SHA-256，便于确认内容完整性。

为了避免密钥直接写入磁盘，以下内容固定替换为 `<redacted>`：

- Authorization、Proxy-Authorization
- X-API-Key、API-Key
- Cookie、Set-Cookie
- 请求 JSON 中的 api_key、access_token、password、secret 等字段

提示词、用户消息、模型正文、推理过程、工具调用和结构化输出不会被裁剪。调试日志因此可能包含隐私或业务数据，只应在排障期间开启，并使用“清空调试日志”及时清理。

管理接口：

```text
GET    /admin/debug-logs
DELETE /admin/debug-logs
```

旧版 `.jsonl` 日志不会被转换，但状态统计、保留数量清理和一键清空仍会兼容处理。

## 4.8.0 代理强制思考

“转发配置”新增：

- 代理强制思考开关
- 默认思考强度：由模型决定、低、中、高、最高

开关开启后，仅在调用方没有提供任何思考参数时注入默认值：

```text
Ollama 原生上游     → think
通用 OpenAI 兼容上游 → reasoning_effort
DeepSeek 上游        → thinking: {type: enabled}
```

调用方显式传入 `think: false`、`thinking: {type: disabled}` 或 `reasoning_effort: none` 时，代理尊重调用方选择，不会覆盖。该开关默认关闭，升级后不会自动改变已有请求行为。

## 4.7.1 推理字幕修复

开启“字幕中显示推理内容”后，推理分片会在默认的“仅提取对话字段”模式下立即显示，不再等待最终正文或 JSON 对话字段被识别。

对于先输出大量推理、最后只输出一个短答案的模型，字幕行为为：

```text
推理分片到达 → 实时显示推理内容
最终正文到达 → 清空推理并显示最终正文
```

`stream_events` 数量大只表示上游确实分片返回；如果最终正文很短，模型仍可能只用一个正文分片返回。这种情况下不会人为拆字模拟流式。

## Web 实时监视器

```text
http://127.0.0.1:11434/monitor/
```

Web 监视器用于查看最近请求、并发请求和内存历史。Windows 下也可以双击：

```text
打开实时响应窗口.bat
```

该脚本打开 Web 监视器，不是桌面字幕浮层。

## 数据流

```text
第三方程序 / UI 测试页
    │
    │ OpenAI SSE / Ollama NDJSON
    ▼
LLM Relay Desk
    ├── 流式请求原样返回；内部强制流式时聚合为调用方要求的非流式响应
    ├── 非阻塞复制事件到 WebSocket 监视器
    └── 非阻塞复制事件到原生字幕进程
```

WebSocket 队列和字幕进程队列均为有界队列。队列满、窗口关闭、桌面会话不可用或字幕进程异常时，会丢弃观察事件，而不是阻塞 API 调用方。

## 运行条件

- Python 3.10 及以上版本
- 原生字幕需要 Python 自带 `tkinter`
- 原生字幕需要运行在已登录的图形桌面会话中
- Windows 服务、无桌面远程会话和无图形界面的 Linux 服务器通常不能显示字幕
- 字幕不可用时，API、管理页和 Web 监视器仍可正常运行

## 安装

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

## 从 3.x 覆盖升级

1. 先关闭正在运行的 `app.py`。
2. 将 v4 压缩包内容直接覆盖到原项目根目录。
3. 保留原有 `data/config.json`、`data/prompts.json` 和 `.env`。
4. 重新运行 `安装依赖.bat` 或 `python -m pip install -r requirements.txt`。
5. 启动后访问 `/health`，确认版本为 `4.8.0`。

压缩包不包含运行期配置文件，因此不会覆盖 API Key、上游地址或提示词。旧的根目录 `popup_window.py` 会被替换为兼容层。

### 从 4.2.0 回退后升级

4.7.0 继续兼容 4.2.1 的安全迁移逻辑，并会识别没有配置架构版本的旧配置，并执行一次安全迁移：`native_popup_click_through` 自动设为 `false`，保证字幕先恢复可见。确认显示正常后，可在“字幕设置”中重新开启鼠标穿透。

## 开发与测试

```cmd
python -m pip install -r requirements-dev.txt
pytest
```

当前测试覆盖结构化对话字段提取、非对话控制 JSON 抑制、非流式请求内部流式聚合、上游协议识别、Ollama→OpenAI 请求/流式响应转换、配置校验、字体解析与回退、左/中/右文字对齐、文字/背景独立透明度、每像素 Alpha 图像合成、纯色保持、阴影/描边解耦、高保真 PNG 预览、中文换行、字幕独立 API、拖动坐标持久化、单字幕窗口复用、提示词注入、路由契约、静态页面、OpenAI SSE 和 Ollama NDJSON 转发。

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

只有经过本地代理的请求会出现在监视界面和字幕浮层中。直接访问上游 API 的请求无法被本地服务捕获。

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

原生同协议转发不会修改上游响应；启用 Ollama→OpenAI 适配时会按目标协议转换请求和响应。返回头 `X-Relay-Request-ID` 可用于对应 Web 监视器中的请求。

## 数据保存

```text
data/config.json
data/prompts.json
```

模型响应只保存在服务内存和窗口内存中，不写入硬盘。重启服务后 Web 监视历史消失。

默认仅监听 `127.0.0.1`。不要在没有额外鉴权、防火墙和反向代理保护的情况下改为 `0.0.0.0`。

## 发布构建

发布前必须在 `frontend/` 中运行 `npm ci` 和 `npm run build`。发布产物必须包含生成的
`frontend/dist/` 目录，FastAPI 才能在 `/ui/` 提供 Vue 管理界面。源代码仓库可以忽略该目录；
未包含生产构建时，后端和旧版界面仍可运行，而 `/ui/` 会返回明确的未构建诊断响应。
