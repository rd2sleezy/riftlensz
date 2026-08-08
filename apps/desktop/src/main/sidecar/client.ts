import { HealthSchema, type HealthPayload } from '../ipc/channels'

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

  /** Return the bearer header. Assumes token is the current launch secret. */
  public authHeaders(): Record<string, string> {
    return { Authorization: `Bearer ${this.token}` }
  }
}
