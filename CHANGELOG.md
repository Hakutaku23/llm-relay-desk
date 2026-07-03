# Changelog

## 3.0.0

- 项目名称调整为 **LLM Relay Desk**。
- 新增独立实时响应页 `/monitor/`。
- 新增 WebSocket 事件通道 `/ws/monitor`。
- 新增 OpenAI SSE 正文与推理内容解析。
- 新增 Ollama NDJSON 正文与思考内容解析。
- 新增非流式响应捕获和前端平滑流式展示。
- 新增多请求分流、请求状态、耗时、来源及请求 ID 展示。
- 新增最近 60 条内存历史和清空接口。
- 监视事件采用非阻塞有界队列，慢客户端不会阻塞 API。
- API 响应新增 `X-Relay-Request-ID` 响应头。
- 新增 Windows 独立监视窗口启动脚本。
