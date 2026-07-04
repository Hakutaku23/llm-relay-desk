# 后端架构

## 分层

```text
app.py
└── llm_relay_desk.application.create_app
    ├── api/routes          HTTP 与 WebSocket 路由
    ├── proxy              OpenAI/Ollama 转发与流解析
    ├── monitoring         内存历史、事件广播、请求生命周期
    ├── desktop            原生字幕进程、窗口与 Win32 Alpha 渲染
    ├── prompts            提示词配置与注入
    ├── config             配置校验
    ├── storage            原子 JSON 持久化
    ├── runtime.py         运行期依赖聚合
    └── settings.py        路径、环境变量和默认值
```

## 依赖方向

路由层只负责协议适配，通过 `request.app.state.runtime` 获取运行期依赖。代理层不依赖具体路由；监视层通过事件接口接收增量；桌面字幕作为监视事件的旁路消费者，不参与 API 返回链路。

```text
routes → proxy/services → monitoring/storage
                     ↘ desktop（非阻塞旁路）
```

## 关键约束

- API 转发不能等待 WebSocket 或桌面字幕消费者。
- 配置与提示词继续使用原有 `data/*.json`，升级不迁移数据格式。
- OpenAI SSE 和 Ollama NDJSON 必须按原始字节流返回调用方。
- `app.py` 仅保留应用实例与命令行启动逻辑。
- 新增功能应优先放入已有领域目录，避免重新堆回入口文件。

## 字幕单实例与位置回写

桌面字幕进程只维护一个 `SubtitleOverlay`。当新的请求获得显示权时，窗口对象被复用，旧文本与关闭倒计时被清空；被替代请求的后续事件在桌面进程内丢弃，避免并发响应串台。

字幕事件仍通过主进程到桌面进程的有界队列单向发送。拖动位置使用第二条反向控制队列：

```text
API 主进程  ── response events ──▶  字幕进程
API 主进程  ◀─ saved position  ───  字幕进程
```

鼠标释放后，字幕进程发送绝对 X/Y 坐标；`NativePopupController` 的控制线程调用运行期回调，将 `native_popup_position=custom` 与坐标原子写入 `data/config.json`。位置回写失败不会阻塞 API 转发。


## 字幕交互模式

桌面字幕进程接收 `popup_interaction_mode` 控制事件。常态按配置应用鼠标穿透；定位模式临时关闭穿透，允许拖动并通过控制队列回写坐标。定位模式有超时保护，且不参与 API 响应链路。


## 穿透安全策略

字幕窗口先完成 Tk 首帧显示和子控件绘制，再延迟写入 `WS_EX_TRANSPARENT`。穿透切换不修改 layered/no-activate/tool-window 等基础样式；流式文本更新后主动请求 Win32 重绘。定位模式通过事件队列提前覆盖穿透配置，确保预览窗口从创建开始即可交互。


## 字幕每像素 Alpha 渲染

Windows 下 `desktop/layered_renderer.py` 使用 Pillow 生成 RGBA 位图，再通过 `UpdateLayeredWindow` 提交到无边框字幕窗口。背景和文字 Alpha 在位图中分别计算，因此背景可以完全透明，而文字仍保持独立透明度和抗锯齿边缘。

渲染器只负责视觉合成，不参与请求转发、事件排序或配置持久化；失败时 `SubtitleOverlay` 自动回退到普通 Tk 控件，API 链路不受影响。定位模式会给全透明位图增加临时低 Alpha 命中区域，保证拖动操作可用。


## 协议适配边界

`proxy/native.py` 只负责选择原生转发或协议适配。`proxy/protocol.py` 解析 `auto/openai/ollama` 上游模式；`proxy/ollama_openai_adapter.py` 负责 Ollama 请求到 OpenAI 请求、OpenAI SSE 到 Ollama NDJSON 以及模型/嵌入接口的格式转换。适配层仍通过统一监视事件发布正文和推理内容，不直接依赖桌面字幕实现。


## 字幕语义过滤与内部流式聚合

`MonitorHub` 始终保存原始模型正文和推理内容。桌面字幕不再直接订阅原始事件，而是经过 `desktop/subtitle_events.py`：

1. 普通文本按配置直接展示。
2. 结构化 JSON 只增量提取配置的顶层对话字段。
3. 没有对话字段的事件/控制响应不创建字幕窗口。
4. Web 监视器仍可查看完整原始输出，字幕过滤不会修改下游 API 响应。

当调用方请求 `stream:false` 且开启字幕内部流式时，代理将上游请求改为流式并实时发布监视事件，随后聚合为调用方原协议的非流式响应。该逻辑分别位于 OpenAI 转发、Ollama 原生转发和 Ollama→OpenAI 适配模块中。

- `proxy/reasoning.py`：统一处理调用方思考参数检测与代理默认思考注入。
