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
    apiTest: string
    prompts: string
    taskIsolation: string
    subtitles: string
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
    apiTest: string
    prompts: string
    taskIsolation: string
    subtitles: string
    notFound: string
  }
  common: Record<string, string>
  status: Record<string, string>
  settings: Record<string, LocaleMessageValue>
  secrets: { title: string; upstream: string; local: string; configured: string; notConfigured: string; source: string; writable: string; readOnly: string; preservePlaceholder: string; enterPlaceholder: string; reveal: string; clear: string; confirmClear: string; sources: Record<string, string> }
  apiTest: Record<string, string>
  prompts: Record<string, string>
  taskIsolation: Record<string, string>
  subtitles: Record<string, LocaleMessageValue>
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
    apiTest: 'API Test',
    prompts: 'Prompt Profiles',
    taskIsolation: 'Task Isolation',
    subtitles: 'Subtitles',
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
    apiTest: 'API Test - LLM Relay Desk',
    prompts: 'Prompt Profiles - LLM Relay Desk',
    taskIsolation: 'Task Isolation - LLM Relay Desk',
    subtitles: 'Subtitles - LLM Relay Desk',
    notFound: 'Page not found - LLM Relay Desk',
  },
  common: { enabled: 'Enabled', disabled: 'Disabled', retry: 'Retry' },
  status: { eyebrow: 'Relay health', title: 'System Status', refresh: 'Refresh', loading: 'Loading system status', malformed: 'Malformed status response', malformedBody: 'The relay returned invalid status data.', error: 'Status request failed', errorBody: 'The local relay could not be reached.', healthy: 'Relay service is operational', service: 'Service', version: 'Version', upstream: 'Upstream address', protocol: 'Configured / active protocol', model: 'Default model', debug: 'Debug logging' },
  settings: { eyebrow: 'Relay administration', title: 'Relay Settings', loading: 'Loading relay configuration', loadError: 'Configuration could not be loaded', relay: 'Relay configuration', upstream: 'Upstream address', protocol: 'Upstream protocol', model: 'Default model', timeout: 'Request timeout (seconds)', forceStream: 'Force upstream streaming', forceReasoning: 'Force reasoning / thinking', effort: 'Default reasoning effort', modelDefault: 'Model default', promptInjection: 'Enable prompt injection', debug: 'Enable debug logging', debugDirectory: 'Debug log directory', retention: 'Debug log retention files', save: 'Save configuration', saving: 'Saving...', saved: 'Configuration saved.', saveError: 'Configuration could not be saved.', unsavedConfirm: 'Discard unsaved configuration changes?', protocols: { auto: 'Automatic', openai: 'OpenAI compatible', ollama: 'Ollama native', vllm: 'vLLM' }, efforts: { none: 'None', low: 'Low', medium: 'Medium', high: 'High', max: 'Maximum' }, errors: { upstream: 'Enter an HTTP or HTTPS URL.', model: 'Default model is required.', timeout: 'Timeout must be between 30 and 7200.', retention: 'Retention must be between 1 and 10000.' } },
  secrets: { title: 'API keys and secret status', upstream: 'Upstream API key', local: 'Local relay API key', configured: 'Configured', notConfigured: 'Not configured', source: 'Source', writable: 'Writable from this UI', readOnly: 'Read-only', preservePlaceholder: 'Leave blank to preserve stored value', enterPlaceholder: 'Enter a new value', reveal: 'Reveal local key', clear: 'Clear', confirmClear: 'Clear this secret? This cannot be undone.', sources: { environment: 'Environment', os_keyring: 'OS keyring', encrypted_file: 'Encrypted file', missing: 'Missing' } },
  apiTest: { eyebrow: 'Local relay validation', title: 'API Test', loading: 'Loading saved relay configuration', connectivity: 'Upstream connectivity and models', check: 'Check connectivity', checking: 'Checking...', models: 'models', protocol: 'Test protocol', model: 'Model', temperature: 'Temperature', maxTokens: 'Maximum output tokens', streaming: 'Streaming response', reasoningEnabled: 'Enable reasoning / thinking', effort: 'Reasoning effort', defaultEffort: 'Model default', task: 'Simulated task type', npcTask: 'NPC dialogue', systemTask: 'System / world event', message: 'User message', promptMode: 'Saved prompt injection mode', mode_normal: 'Normal', mode_bannerlord: 'Bannerlord task isolation', send: 'Send test', cancel: 'Cancel request', idle: 'Ready', running: 'Request running', completeStatus: 'Request complete', results: 'Test response', copy: 'Copy complete response', clear: 'Clear results', elapsed: 'Elapsed', interrupted: 'Stream interrupted before terminal event', reasoning: 'Reasoning / thinking', content: 'Final content', complete: 'Complete response', usage: 'Usage', unknown: 'Unknown', empty: 'No content returned' },
  prompts: { eyebrow: 'Prompt injection', title: 'Prompt Profiles', create: 'New profile', import: 'Import', export: 'Export all', name: 'Profile name', content: 'System prompt content', characters: 'characters', save: 'Save profile', saved: 'Profile saved.', active: 'Active', activate: 'Set active', activated: 'Active profile updated.', delete: 'Delete profile', deleted: 'Profile deleted.', imported: 'Profiles imported.', deleteConfirm: 'Delete this prompt profile?', unsavedConfirm: 'Discard unsaved prompt changes?' },
  taskIsolation: { eyebrow: 'Prompt routing', title: 'Task Isolation', save: 'Save settings', saved: 'Task-isolation settings saved.', unsavedConfirm: 'Discard unsaved task-isolation changes?', mode: 'Prompt and injection mode', promptEnabled: 'Enable prompt injection globally', injectionMode: 'Injection mode', normal: 'Normal conversation', bannerlord: 'Bannerlord task isolation', master: 'Enable player-friendly injection', playerDialogue: 'Player initiated NPC dialogue', actionDialogue: 'Player trade, command, and request', npcDialogue: 'NPC initiated player dialogue', rules: 'Supported task rules', allowed: 'Prompt injection allowed', passthrough: 'Forced passthrough', passthroughDetail: 'Diplomacy, war, alliances, system events, world state, NPC-to-NPC dialogue, structured control tasks, routing, image prompts, and unknown tasks.', fallback: 'Unknown or unsupported tasks pass through without prompt injection. Explicit relay_task_type metadata takes precedence.' },
  subtitles: { eyebrow:'Desktop overlay',title:'Subtitle Settings',loading:'Loading subtitle settings',save:'Save settings',saving:'Saving…',reset:'Reset changes',saved:'Subtitle settings saved.',unsavedConfirm:'Discard unsaved subtitle changes?',windowsNote:'Click-through and layered-window behavior is Windows-specific.',native:{title:'Native subtitle status',enabled:'Configured as enabled',disabled:'Configured as disabled',position:'Enter positioning mode',active:'Positioning mode is active for up to 60 seconds. Drag the desktop subtitle to save its position.'},preview:{title:'High-fidelity preview',generate:'Generate preview',loading:'Rendering preview…',alt:'Rendered subtitle preview'},position:{title:'Position and size',preset:'Preset position',width:'Width',height:'Height',offsetX:'Preset X offset',offsetY:'Preset Y offset',customX:'Custom absolute X',customY:'Custom absolute Y',top_left:'Top left',top_center:'Top center',top_right:'Top right',center_left:'Center left',center:'Center',center_right:'Center right',bottom_left:'Bottom left',bottom_center:'Bottom center',bottom_right:'Bottom right',custom:'Custom absolute'},typography:{title:'Typography',refreshFonts:'Refresh installed fonts',font:'Font family',size:'Font size',align:'Text alignment',left:'Left',center:'Center',right:'Right'},appearance:{title:'Colors and effects',textOpacity:'Text opacity',backgroundOpacity:'Background opacity',backgroundColor:'Background color',textColor:'Text color',mutedColor:'Secondary text color',borderColor:'Border color',shadowColor:'Shadow color',outlineColor:'Outline color',errorColor:'Error color',shadow:'Enable text shadow',shadowOffset:'Shadow offset',outline:'Enable text outline',outlineWidth:'Outline width'},behavior:{title:'Content and behavior',enabled:'Enable native subtitles',close:'Auto-close timeout (seconds)',mode:'Subtitle content mode',dialogue:'Configured dialogue only',all:'All response text',fields:'Dialogue field names (comma separated)',fallback:'Use plain-text fallback',reasoning:'Show reasoning text',clickThrough:'Mouse click-through',forceStream:'Force upstream streaming for subtitle updates'} },
}

export default enUS
