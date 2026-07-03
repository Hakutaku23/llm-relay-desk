# 后端架构

## 分层

```text
app.py
└── llm_relay_desk.application.create_app
    ├── api/routes          HTTP 与 WebSocket 路由
    ├── proxy              OpenAI/Ollama 转发与流解析
    ├── monitoring         内存历史、事件广播、请求生命周期
    ├── desktop            原生字幕进程与窗口
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
