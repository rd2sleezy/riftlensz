import { HealthSchema, type HealthPayload } from '../ipc/channels'

export class SidecarRequestError extends Error {
  public constructor(
    public readonly status: number,
    message: string
  ) {
    super(message)
    this.name = 'SidecarRequestError'
  }
}

export class SidecarClient {
  public constructor(
    private readonly baseUrl: string,
    private readonly token: string
  ) {}

  /** Fetch /health. Assumes the sidecar is bound at baseUrl. */
  public async health(timeoutMs = 2500): Promise<HealthPayload> {
    const response = await fetch(`${this.baseUrl}/health`, {
      signal: AbortSignal.timeout(timeoutMs)
    })
    if (!response.ok) {
      throw new Error(`health check failed: HTTP ${response.status}`)
    }
    return HealthSchema.parse(await response.json())
  }

  /** Authenticated JSON request. Assumes path starts with /. Never logs the token. */
  public async request(path: string, init: RequestInit = {}, timeoutMs = 120_000): Promise<unknown> {
    const headers = new Headers(init.headers)
    headers.set('Authorization', `Bearer ${this.token}`)
    if (init.body !== undefined && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json')
    }
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers,
      signal: init.signal ?? AbortSignal.timeout(timeoutMs)
    })
    const text = await response.text()
    let parsed: unknown = null
    if (text.length > 0) {
      try {
        parsed = JSON.parse(text) as unknown
      } catch {
        parsed = { detail: text }
      }
    }
    if (!response.ok) {
      throw new SidecarRequestError(response.status, detailMessage(parsed, response.status))
    }
    return parsed
  }

  /** Return the bearer header. Assumes token is the current launch secret. */
  public authHeaders(): Record<string, string> {
    return { Authorization: `Bearer ${this.token}` }
  }
}

function detailMessage(parsed: unknown, status: number): string {
  if (typeof parsed === 'object' && parsed !== null && 'detail' in parsed) {
    const detail = (parsed as { detail: unknown }).detail
    if (typeof detail === 'string' && detail.length > 0) {
      return detail
    }
  }
  return `sidecar request failed: HTTP ${status}`
}
