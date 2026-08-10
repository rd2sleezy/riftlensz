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

  const response = await fetch(url, { headers: { 'X-Riot-Token': apiKey } })

  if (response.status === 401 || response.status === 403) {
    throw new RiotApiKeyError(
      'That API key was rejected. Personal keys expire roughly every 24h — get a fresh one from the Riot Developer Portal.',
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
    throw new RiotApiKeyError(`Riot API returned ${response.status}.`, 'UNKNOWN')
  }

  const body = (await response.json()) as { puuid?: string; gameName?: string; tagLine?: string }
  if (!body.puuid) {
    throw new RiotApiKeyError('Riot API response was missing a puuid.', 'UNKNOWN')
  }
  return { puuid: body.puuid, gameName: body.gameName ?? gameName, tagLine: body.tagLine ?? tagLine }
}
