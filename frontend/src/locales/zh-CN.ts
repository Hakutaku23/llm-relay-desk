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
    notFound: '页面不存在 - LLM Relay Desk',
  },
}

export default zhCN
