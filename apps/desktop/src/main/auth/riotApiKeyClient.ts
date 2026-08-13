export type RiotAccountRegion = 'americas' | 'asia' | 'europe'

export class RiotApiKeyError extends Error {
  constructor(
    message: string,
    public readonly code: 'INVALID_KEY' | 'NOT_FOUND' | 'RATE_LIMITED' | 'UNKNOWN'
  ) {
    super(message)
  }
}

export type RiotAccount = {
  puuid: string
  gameName: string
  tagLine: string
}

/**
 * Verifies a Riot ID against the real Account-V1 API using a personal
 * developer key (https://developer.riotgames.com — instant, no RSO
 * approval needed, but expires ~24h and must be regenerated). This is a
 * genuine authenticated call against Riot's servers, not a stub.
 */
export async function fetchRiotAccount(
  apiKey: string,
  gameName: string,
  tagLine: string,
  region: RiotAccountRegion
): Promise<RiotAccount> {
  const url = `https://${region}.api.riotgames.com/riot/account/v1/accounts/by-riot-id/${encodeURIComponent(
    gameName
  )}/${encodeURIComponent(tagLine)}`

  let response: Response
  try {
    response = await fetch(url, { headers: { 'X-Riot-Token': apiKey } })
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error)
    throw new RiotApiKeyError(`Couldn't reach Riot's servers (${detail}). Check your internet connection.`, 'UNKNOWN')
  }

  if (response.status === 401 || response.status === 403) {
    const detail = await riotErrorDetail(response)
    throw new RiotApiKeyError(
      `That API key was rejected by Riot (HTTP ${response.status}${detail ? `, ${detail}` : ''}). ` +
        'Personal keys expire roughly every 24h — regenerate one on the Riot Developer Portal and make sure ' +
        'you copied the whole RGAPI-… value with no extra spaces.',
      'INVALID_KEY'
    )
  }
  if (response.status === 404) {
    throw new RiotApiKeyError(`No Riot account found for ${gameName}#${tagLine} in that region.`, 'NOT_FOUND')
  }
  if (response.status === 429) {
    throw new RiotApiKeyError('Rate limited by Riot — wait a moment and try again.', 'RATE_LIMITED')
  }
  if (!response.ok) {
    const detail = await riotErrorDetail(response)
    throw new RiotApiKeyError(`Riot API returned HTTP ${response.status}${detail ? `: ${detail}` : ''}.`, 'UNKNOWN')
  }

  const body = (await response.json()) as { puuid?: string; gameName?: string; tagLine?: string }
  if (!body.puuid) {
    throw new RiotApiKeyError('Riot API response was missing a puuid.', 'UNKNOWN')
  }
  return { puuid: body.puuid, gameName: body.gameName ?? gameName, tagLine: body.tagLine ?? tagLine }
}

/** Best-effort extraction of Riot's { status: { message } } error body for diagnostics. */
async function riotErrorDetail(response: Response): Promise<string | null> {
  try {
    const body = (await response.clone().json()) as { status?: { message?: string } }
    return body.status?.message ?? null
  } catch {
    return null
  }
}
