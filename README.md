# LLM Relay Desk

本地 LLM API 转发、提示词管理、Web 实时监视与原生桌面字幕浮层工具。

它可以把 Ollama 或 OpenAI 兼容上游包装成本地 API，并在不阻塞调用方的前提下，把模型响应复制到 Web 监视器和桌面字幕浮层。

## 功能

- OpenAI 兼容接口：`GET /v1/models`、`POST /v1/chat/completions`
- Ollama 原生接口：`/api/chat`、`/api/generate`、`/api/tags` 等
- 支持流式与非流式回复
- 系统提示词配置集、启用、导入和导出
- 上游地址、API Key、默认模型和超时在线配置
- Web 实时监视器：`/monitor/`
- 无标题栏、置顶且不主动抢焦点的原生字幕浮层
- 独立“字幕设置”页签，集中管理位置、尺寸、颜色和关闭策略
- 文字与背景透明度独立控制，背景可设为 0 实现真正无填充
- Windows 下使用每像素 Alpha 字幕渲染，支持平滑抗锯齿、柔化阴影与轻描边
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
├── prompts/                提示词配置与请求注入
├── monitoring/             请求事件、内存历史和 WebSocket 广播
├── desktop/                原生字幕控制器、Tk 窗口与 Win32 Alpha 渲染器
└── proxy/                  OpenAI/Ollama 转发、内容提取和流解析
```

模块依赖方向、扩展规范和职责边界见 [`docs/architecture.md`](docs/architecture.md)。根目录 `popup_window.py` 仅作为旧导入路径的兼容层。

## 原生字幕浮层

字幕浮层由独立的 Python/Tk 进程运行：

1. 第一个正文或推理片段到达时显示浮层。
2. `stream: true` 请求会按 SSE/NDJSON 片段实时追加文字。
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
- 背景透明度可设为 0；文字阴影开关、颜色和偏移可独立设置
- 是否显示推理文本
- 是否启用鼠标穿透（安全默认值为关闭）
- 完成后的自动关闭秒数

字体输入框通过 `GET /admin/subtitle-fonts` 读取服务所在电脑的已安装字体。也可以手动输入字体族名称；找不到对应字体文件时，桌面渲染器会使用安全回退字体，不会中断字幕显示。

“进入定位模式”会发送流式预览并临时关闭鼠标穿透。拖动并松开后，桌面进程通过独立 IPC 把坐标写回 `data/config.json`，自动切换到 `custom` 位置并恢复配置状态；60 秒未完成时也会自动退出定位模式。

Windows 下使用无标题栏工具窗口和“显示但不激活”方式，不调用 `focus_force`，不会主动最小化、暂停或切换调用 API 的程序。字幕先完成首次绘制，再延迟启用鼠标穿透；流式正文和推理更新会触发原生重绘。鼠标穿透依赖 Windows 扩展窗口样式；其他系统会保留该配置，但不保证具备相同的系统级穿透效果。

4.4.0 起，Windows 字幕改用 `UpdateLayeredWindow` 每像素 Alpha 合成，不再使用颜色键透明。文字与背景拥有独立 Alpha：背景透明度设为 `0` 时只显示字幕，文字边缘仍保持平滑抗锯齿；无背景模式自动隐藏状态栏，默认采用左对齐，也可切换为居中或右对齐，并使用可选柔化阴影和轻描边提高复杂画面下的可读性。定位模式会临时显示一层淡色拖动区域，保存位置后立即恢复用户设置。非 Windows 平台会降级为普通 Tk 窗口，无法保证文字与背景 Alpha 完全独立。

## 真正的流式显示

字幕是否逐段更新取决于调用方是否请求流式响应：

```json
{
  "stream": true
}
```

`/ui/` 中的 API 测试页在 3.2.0 起默认开启“使用真实流式响应”，通过 `ReadableStream` 逐块解析 SSE，不再等待完整 JSON 后一次性显示。

外部程序若发送 `stream: false`，上游只会在生成结束后返回完整响应，字幕也只能一次性收到完整正文。这属于调用协议行为，不是字幕进程缓冲。

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
    ├── 原样返回上游响应给调用方
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
5. 启动后访问 `/health`，确认版本为 `4.5.0`。

压缩包不包含运行期配置文件，因此不会覆盖 API Key、上游地址或提示词。旧的根目录 `popup_window.py` 会被替换为兼容层。

### 从 4.2.0 回退后升级

4.5.0 继续兼容 4.2.1 的安全迁移逻辑，并会识别没有配置架构版本的旧配置，并执行一次安全迁移：`native_popup_click_through` 自动设为 `false`，保证字幕先恢复可见。确认显示正常后，可在“字幕设置”中重新开启鼠标穿透。

## 开发与测试

```cmd
python -m pip install -r requirements-dev.txt
pytest
```

当前测试覆盖配置校验、字体解析与回退、左/中/右文字对齐、文字/背景独立透明度、每像素 Alpha 图像合成、中文换行、字幕独立 API、颜色与阴影参数、拖动坐标持久化、单字幕窗口复用、提示词注入、路由契约、静态页面、OpenAI SSE 和 Ollama NDJSON 转发。

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

代理不会修改上游响应内容。返回头 `X-Relay-Request-ID` 可用于对应 Web 监视器中的请求。

## 数据保存

```text
data/config.json
data/prompts.json
```

模型响应只保存在服务内存和窗口内存中，不写入硬盘。重启服务后 Web 监视历史消失。

默认仅监听 `127.0.0.1`。不要在没有额外鉴权、防火墙和反向代理保护的情况下改为 `0.0.0.0`。
