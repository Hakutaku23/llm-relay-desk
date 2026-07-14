import type { LocaleMessages } from './en-US'

const zhCN: LocaleMessages = {
  app: {
    name: 'LLM Relay Desk',
    tagline: '本地中继控制台',
  },
  header: {
    eyebrow: '管理界面',
    title: '中继运行状态',
    environment: '本机',
  },
  navigation: {
    label: '主导航',
    dashboard: '仪表盘',
    status: '系统状态',
    settings: '中继设置',
    apiTest: 'API 测试',
    legacy: '旧版管理界面',
    monitor: '实时监视器',
  },
  language: {
    label: '语言',
    zhCN: '中文',
    enUS: '英文',
  },
  dashboard: {
    eyebrow: '系统概览',
    title: '仪表盘',
    refresh: '刷新',
    loadingTitle: '正在检查中继',
    loadingBody: '正在读取本地服务状态。',
    healthyTitle: '中继运行正常',
    malformedTitle: '健康响应格式错误',
    malformedBody: '中继返回了无效的健康状态响应。',
    errorTitle: '健康检查请求失败',
    errorBody: '无法连接到本地中继服务。',
    model: '模型',
    protocol: '协议',
    serviceState: '服务状态',
    operational: '运行正常',
    notConfigured: '未配置',
  },
  notFound: {
    code: '404',
    title: '页面不存在',
    body: '请求的管理页面不存在。',
    returnToDashboard: '返回仪表盘',
  },
  routes: {
    dashboard: '仪表盘 - LLM Relay Desk',
    status: '系统状态 - LLM Relay Desk',
    settings: '中继设置 - LLM Relay Desk',
    apiTest: 'API 测试 - LLM Relay Desk',
    notFound: '页面不存在 - LLM Relay Desk',
  },
  common: { enabled: '已启用', disabled: '已停用', retry: '重试' },
  status: { eyebrow: '中继健康状态', title: '系统状态', refresh: '刷新', loading: '正在加载系统状态', malformed: '状态响应格式错误', malformedBody: '中继返回了无效的状态数据。', error: '状态请求失败', errorBody: '无法连接到本地中继服务。', healthy: '中继服务运行正常', service: '服务', version: '版本', upstream: '上游地址', protocol: '配置协议 / 当前协议', model: '默认模型', debug: '调试日志' },
  settings: { eyebrow: '中继管理', title: '中继设置', loading: '正在加载中继配置', loadError: '无法加载配置', relay: '中继配置', upstream: '上游地址', protocol: '上游协议', model: '默认模型', timeout: '请求超时（秒）', forceStream: '强制上游流式传输', forceReasoning: '强制推理 / 思考', effort: '默认思考强度', modelDefault: '由模型决定', promptInjection: '启用提示词注入', debug: '启用调试日志', debugDirectory: '调试日志目录', retention: '调试日志保留文件数', save: '保存配置', saving: '正在保存…', saved: '配置已保存。', saveError: '无法保存配置。', unsavedConfirm: '放弃尚未保存的配置更改？', protocols: { auto: '自动识别', openai: 'OpenAI 兼容', ollama: 'Ollama 原生', vllm: 'vLLM' }, efforts: { none: '无', low: '低', medium: '中', high: '高', max: '最高' }, errors: { upstream: '请输入 HTTP 或 HTTPS 地址。', model: '默认模型不能为空。', timeout: '超时范围为 30 至 7200。', retention: '保留数量范围为 1 至 10000。' } },
  secrets: { title: 'API Key 与密钥状态', upstream: '上游 API Key', local: '本地中继 API Key', configured: '已配置', notConfigured: '未配置', source: '来源', writable: '可在此界面修改', readOnly: '只读', preservePlaceholder: '留空以保留已存储值', enterPlaceholder: '输入新值', reveal: '显示本地 Key', clear: '清除', confirmClear: '确定清除此密钥？此操作无法撤销。', sources: { environment: '环境变量', os_keyring: '系统密钥环', encrypted_file: '加密文件', missing: '未配置' } },
  apiTest: { eyebrow: '本地中继验证', title: 'API 测试', loading: '正在加载已保存的中继配置', connectivity: '上游连接与模型列表', check: '检查连接', checking: '正在检查…', models: '个模型', protocol: '测试协议', model: '模型', temperature: '温度', maxTokens: '最大输出 Token', streaming: '流式响应', reasoningEnabled: '启用推理 / 思考', effort: '思考强度', defaultEffort: '由模型决定', task: '模拟任务类型', npcTask: 'NPC 对话', systemTask: '系统 / 世界事件', message: '用户消息', promptMode: '已保存的提示词注入模式', mode_normal: '普通模式', mode_bannerlord: '霸主任务隔离', send: '发送测试', cancel: '取消请求', idle: '就绪', running: '请求进行中', completeStatus: '请求完成', results: '测试响应', copy: '复制完整响应', clear: '清除结果', elapsed: '耗时', interrupted: '流在终止事件前中断', reasoning: '推理 / 思考', content: '最终内容', complete: '完整响应', usage: '用量', unknown: '未知', empty: '未返回内容' },
}

export default zhCN
