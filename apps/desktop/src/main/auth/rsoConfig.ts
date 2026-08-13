const AUTH_HOST = 'https://auth.riotgames.com'

export const RSO_AUTHORIZE_URL = `${AUTH_HOST}/authorize`
export const RSO_TOKEN_URL = `${AUTH_HOST}/token`
export const RSO_USERINFO_URL = `${AUTH_HOST}/userinfo`

export type RsoConfig = {
  clientId: string
  clientSecret: string
  redirectUri: string
  callbackPort: number
  callbackPath: string
}

/**
 * RSO is a restricted Riot product — client_id/client_secret only exist once
 * Riot approves a request via https://developer.riotgames.com (RSO Client
 * Request Form) for the exact redirect_uri configured here. There is no
 * self-serve way to obtain these; sign-in stays disabled until they're set.
 */
export function loadRsoConfig(): RsoConfig | null {
  const clientId = process.env['RIFTLENS_RIOT_CLIENT_ID']
  const clientSecret = process.env['RIFTLENS_RIOT_CLIENT_SECRET']
  const redirectUri =
    process.env['RIFTLENS_RIOT_REDIRECT_URI'] ?? 'http://127.0.0.1:53681/oauth2-callback'

  if (!clientId || !clientSecret) {
    return null
  }

  const parsed = new URL(redirectUri)
  return {
    clientId,
    clientSecret,
    redirectUri,
    callbackPort: Number(parsed.port || 80),
    callbackPath: parsed.pathname
  }
}
