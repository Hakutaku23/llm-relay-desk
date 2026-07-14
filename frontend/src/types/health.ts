export interface HealthSummary {
  service: string
  version: string
  status: 'ok'
  model: string | null
  upstreamProtocol: string
}

export class MalformedHealthResponseError extends Error {
  constructor() {
    super('The relay returned an invalid health response.')
    this.name = 'MalformedHealthResponseError'
  }
}
