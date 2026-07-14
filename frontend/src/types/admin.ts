export type UpstreamProtocol = 'auto' | 'openai' | 'ollama' | 'vllm'

export interface RelayConfig {
  upstreamBaseUrl: string
  upstreamProtocol: UpstreamProtocol
  defaultModel: string
  requestTimeoutSeconds: number
  forceUpstreamStream: boolean
  forceReasoningEnabled: boolean
  defaultReasoningEffort: '' | 'none' | 'low' | 'medium' | 'high' | 'max'
  promptEnabled: boolean
  debugLoggingEnabled: boolean
  debugLogDirectory: string
  debugLogRetentionFiles: number
}

export type SecretName = 'upstream_api_key' | 'local_api_key'
export interface SecretInfo { configured: boolean; source: string; environmentVariable: string | null; webuiWritable: boolean }
export type SecretStatus = Record<SecretName, SecretInfo>

export class MalformedAdminResponseError extends Error {}
