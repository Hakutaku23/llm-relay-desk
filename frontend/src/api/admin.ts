import { MalformedAdminResponseError, type RelayConfig, type SecretName, type SecretStatus, type UpstreamProtocol } from '@/types/admin'

const protocols = new Set(['auto', 'openai', 'ollama', 'vllm'])
const efforts = new Set(['', 'none', 'low', 'medium', 'high', 'max'])
const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value)

async function jsonRequest(path: string, init?: RequestInit): Promise<unknown> {
  const response = await fetch(path, { ...init, headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...init?.headers } })
  const value: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = record(value) && typeof value.detail === 'string' ? value.detail : `Request failed with status ${response.status}.`
    throw new Error(detail)
  }
  return value
}

export function parseConfig(value: unknown): RelayConfig {
  if (!record(value)) throw new MalformedAdminResponseError('Invalid configuration response')
  const protocol = value.upstream_protocol
  const effort = value.default_reasoning_effort ?? ''
  if (typeof value.upstream_base_url !== 'string' || typeof protocol !== 'string' || !protocols.has(protocol) || typeof value.default_model !== 'string' || typeof value.request_timeout_seconds !== 'number' || typeof effort !== 'string' || !efforts.has(effort)) throw new MalformedAdminResponseError('Invalid configuration response')
  return {
    upstreamBaseUrl: value.upstream_base_url,
    upstreamProtocol: protocol as UpstreamProtocol,
    defaultModel: value.default_model,
    requestTimeoutSeconds: value.request_timeout_seconds,
    forceUpstreamStream: value.native_popup_force_upstream_stream !== false,
    forceReasoningEnabled: value.force_reasoning_enabled === true,
    defaultReasoningEffort: effort as RelayConfig['defaultReasoningEffort'],
    promptEnabled: value.prompt_enabled !== false,
    debugLoggingEnabled: value.debug_logging_enabled === true,
    debugLogDirectory: typeof value.debug_log_directory === 'string' ? value.debug_log_directory : 'debug_logs',
    debugLogRetentionFiles: typeof value.debug_log_retention_files === 'number' ? value.debug_log_retention_files : 100,
  }
}

function toPayload(config: RelayConfig, secrets?: Partial<Record<SecretName, string>>) {
  return {
    upstream_base_url: config.upstreamBaseUrl,
    upstream_protocol: config.upstreamProtocol,
    default_model: config.defaultModel,
    request_timeout_seconds: config.requestTimeoutSeconds,
    native_popup_force_upstream_stream: config.forceUpstreamStream,
    force_reasoning_enabled: config.forceReasoningEnabled,
    default_reasoning_effort: config.defaultReasoningEffort,
    prompt_enabled: config.promptEnabled,
    debug_logging_enabled: config.debugLoggingEnabled,
    debug_log_directory: config.debugLogDirectory,
    debug_log_retention_files: config.debugLogRetentionFiles,
    ...secrets,
  }
}

export async function getConfig(): Promise<RelayConfig> { return parseConfig(await jsonRequest('/admin/config')) }
export async function saveConfig(config: RelayConfig, secrets: Partial<Record<SecretName, string>>): Promise<RelayConfig> {
  const value = await jsonRequest('/admin/config', { method: 'PUT', body: JSON.stringify(toPayload(config, secrets)) })
  if (!record(value) || value.ok !== true) throw new MalformedAdminResponseError('Invalid configuration save response')
  return parseConfig(value.config)
}

function parseSecretInfo(value: unknown) {
  if (!record(value) || typeof value.configured !== 'boolean' || typeof value.source !== 'string' || typeof value.webui_writable !== 'boolean') throw new MalformedAdminResponseError('Invalid secret status response')
  return { configured: value.configured, source: value.source, environmentVariable: typeof value.environment_variable === 'string' ? value.environment_variable : null, webuiWritable: value.webui_writable }
}
export async function getSecretStatus(): Promise<SecretStatus> {
  const value = await jsonRequest('/admin/secrets/status')
  if (!record(value)) throw new MalformedAdminResponseError('Invalid secret status response')
  return { upstream_api_key: parseSecretInfo(value.upstream_api_key), local_api_key: parseSecretInfo(value.local_api_key) }
}
export async function clearSecret(name: SecretName): Promise<SecretStatus> {
  const value = await jsonRequest(`/admin/secrets/${name}`, { method: 'DELETE' })
  if (!record(value) || !record(value.status)) throw new MalformedAdminResponseError('Invalid secret clear response')
  return { upstream_api_key: parseSecretInfo(value.status.upstream_api_key), local_api_key: parseSecretInfo(value.status.local_api_key) }
}
export async function revealLocalKey(): Promise<string> {
  const value = await jsonRequest('/admin/secrets/local_api_key/reveal', { method: 'POST' })
  if (!record(value) || typeof value.value !== 'string') throw new MalformedAdminResponseError('Invalid reveal response')
  return value.value
}
