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
    status: string
    settings: string
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
    status: string
    settings: string
    notFound: string
  }
  common: Record<string, string>
  status: Record<string, string>
  settings: Record<string, LocaleMessageValue>
  secrets: { title: string; upstream: string; local: string; configured: string; notConfigured: string; source: string; writable: string; readOnly: string; preservePlaceholder: string; enterPlaceholder: string; reveal: string; clear: string; confirmClear: string; sources: Record<string, string> }
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
    status: 'System Status',
    settings: 'Relay Settings',
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
    status: 'System Status - LLM Relay Desk',
    settings: 'Relay Settings - LLM Relay Desk',
    notFound: 'Page not found - LLM Relay Desk',
  },
  common: { enabled: 'Enabled', disabled: 'Disabled', retry: 'Retry' },
  status: { eyebrow: 'Relay health', title: 'System Status', refresh: 'Refresh', loading: 'Loading system status', malformed: 'Malformed status response', malformedBody: 'The relay returned invalid status data.', error: 'Status request failed', errorBody: 'The local relay could not be reached.', healthy: 'Relay service is operational', service: 'Service', version: 'Version', upstream: 'Upstream address', protocol: 'Configured / active protocol', model: 'Default model', debug: 'Debug logging' },
  settings: { eyebrow: 'Relay administration', title: 'Relay Settings', loading: 'Loading relay configuration', loadError: 'Configuration could not be loaded', relay: 'Relay configuration', upstream: 'Upstream address', protocol: 'Upstream protocol', model: 'Default model', timeout: 'Request timeout (seconds)', forceStream: 'Force upstream streaming', forceReasoning: 'Force reasoning / thinking', effort: 'Default reasoning effort', modelDefault: 'Model default', promptInjection: 'Enable prompt injection', debug: 'Enable debug logging', debugDirectory: 'Debug log directory', retention: 'Debug log retention files', save: 'Save configuration', saving: 'Saving...', saved: 'Configuration saved.', saveError: 'Configuration could not be saved.', unsavedConfirm: 'Discard unsaved configuration changes?', protocols: { auto: 'Automatic', openai: 'OpenAI compatible', ollama: 'Ollama native', vllm: 'vLLM' }, efforts: { none: 'None', low: 'Low', medium: 'Medium', high: 'High', max: 'Maximum' }, errors: { upstream: 'Enter an HTTP or HTTPS URL.', model: 'Default model is required.', timeout: 'Timeout must be between 30 and 7200.', retention: 'Retention must be between 1 and 10000.' } },
  secrets: { title: 'API keys and secret status', upstream: 'Upstream API key', local: 'Local relay API key', configured: 'Configured', notConfigured: 'Not configured', source: 'Source', writable: 'Writable from this UI', readOnly: 'Read-only', preservePlaceholder: 'Leave blank to preserve stored value', enterPlaceholder: 'Enter a new value', reveal: 'Reveal local key', clear: 'Clear', confirmClear: 'Clear this secret? This cannot be undone.', sources: { environment: 'Environment', os_keyring: 'OS keyring', encrypted_file: 'Encrypted file', missing: 'Missing' } },
}

export default enUS
