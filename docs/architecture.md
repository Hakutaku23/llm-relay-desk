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
