type LocaleMessageValue = string | { [key: string]: LocaleMessageValue }

export interface LocaleMessages {
  [key: string]: LocaleMessageValue
  app: {
    name: string
    tagline: string
  }
  header: {
    eyebrow: string
    title: string
    environment: string
  }
  navigation: {
    label: string
    dashboard: string
    legacy: string
    monitor: string
  }
  language: {
    label: string
    zhCN: string
    enUS: string
  }
  dashboard: {
    eyebrow: string
    title: string
    refresh: string
    loadingTitle: string
    loadingBody: string
    healthyTitle: string
    malformedTitle: string
    malformedBody: string
    errorTitle: string
    errorBody: string
    model: string
    protocol: string
    serviceState: string
    operational: string
    notConfigured: string
  }
  notFound: {
    code: string
    title: string
    body: string
    returnToDashboard: string
  }
  routes: {
    dashboard: string
    notFound: string
  }
}

const enUS: LocaleMessages = {
  app: {
    name: 'LLM Relay Desk',
    tagline: 'Local relay console',
  },
  header: {
    eyebrow: 'Management UI',
    title: 'Relay operations',
    environment: 'Local',
  },
  navigation: {
    label: 'Primary navigation',
    dashboard: 'Dashboard',
    legacy: 'Legacy Management UI',
    monitor: 'Realtime Monitor',
  },
  language: {
    label: 'Language',
    zhCN: 'Chinese',
    enUS: 'English',
  },
  dashboard: {
    eyebrow: 'System overview',
    title: 'Dashboard',
    refresh: 'Refresh',
    loadingTitle: 'Checking relay',
    loadingBody: 'Reading the local service status.',
    healthyTitle: 'Relay healthy',
    malformedTitle: 'Malformed health response',
    malformedBody: 'The relay returned an invalid health response.',
    errorTitle: 'Health request failed',
    errorBody: 'The local relay could not be reached.',
    model: 'Model',
    protocol: 'Protocol',
    serviceState: 'Service state',
    operational: 'Operational',
    notConfigured: 'Not configured',
  },
  notFound: {
    code: '404',
    title: 'Page not found',
    body: 'The requested management view does not exist.',
    returnToDashboard: 'Return to dashboard',
  },
  routes: {
    dashboard: 'Dashboard - LLM Relay Desk',
    notFound: 'Page not found - LLM Relay Desk',
  },
}

export default enUS
