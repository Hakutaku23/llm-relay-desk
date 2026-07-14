import { MalformedHealthResponseError, type HealthSummary } from '@/types/health'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export async function getHealth(signal?: AbortSignal): Promise<HealthSummary> {
  const response = await fetch('/health', { headers: { Accept: 'application/json' }, signal })
  if (!response.ok) throw new Error(`Health request failed with status ${response.status}.`)

  const value: unknown = await response.json()
  if (
    !isRecord(value) ||
    typeof value.service !== 'string' ||
    typeof value.version !== 'string' ||
    value.status !== 'ok' ||
    (value.model !== null && typeof value.model !== 'string') ||
    typeof value.resolved_upstream_protocol !== 'string'
  ) {
    throw new MalformedHealthResponseError()
  }

  return {
    service: value.service,
    version: value.version,
    status: value.status,
    model: value.model,
    upstreamProtocol: value.resolved_upstream_protocol,
  }
}
