import { randomBytes } from 'node:crypto'
import { createServer, type Server } from 'node:http'
import { RSO_AUTHORIZE_URL, RSO_TOKEN_URL, RSO_USERINFO_URL, type RsoConfig } from './rsoConfig'

export class RsoAuthError extends Error {}
export class RsoAuthCancelledError extends RsoAuthError {}

export type RsoTokens = {
  accessToken: string
  refreshToken: string | null
  expiresAt: number
}

export type RsoIdentity = {
  puuid: string
  gameName: string | null
  tagLine: string | null
}

export function buildAuthorizeUrl(config: RsoConfig, state: string): string {
  const url = new URL(RSO_AUTHORIZE_URL)
  url.searchParams.set('client_id', config.clientId)
  url.searchParams.set('redirect_uri', config.redirectUri)
  url.searchParams.set('response_type', 'code')
  url.searchParams.set('scope', 'openid')
  url.searchParams.set('state', state)
  return url.toString()
}

export function generateState(): string {
  return randomBytes(16).toString('hex')
}

/**
 * Listens on the registered redirect_uri's loopback port for Riot's OAuth
 * callback, resolves with the authorization code. Assumes config.redirectUri
 * is a local http://127.0.0.1 URI (the pattern Riot documents for RSO
 * clients — no custom URI scheme).
 */
export function awaitAuthorizationCode(
  config: RsoConfig,
  expectedState: string,
  timeoutMs = 120_000
): { promise: Promise<string>; cancel: () => void } {
  let server: Server | null = null
  let timer: NodeJS.Timeout | null = null

  const promise = new Promise<string>((resolve, reject) => {
    const cleanup = (): void => {
      if (timer !== null) {
        clearTimeout(timer)
      }
      server?.close()
    }

    server = createServer((req, res) => {
      const url = new URL(req.url ?? '/', config.redirectUri)
      if (url.pathname !== config.callbackPath) {
        res.writeHead(404).end()
        return
      }
      const error = url.searchParams.get('error')
      const state = url.searchParams.get('state')
      const code = url.searchParams.get('code')

      if (error !== null) {
        res.writeHead(200, { 'content-type': 'text/html' }).end(callbackPage('Sign-in was cancelled.'))
        cleanup()
        reject(new RsoAuthCancelledError(error))
        return
      }
      if (state !== expectedState || code === null) {
        res.writeHead(400, { 'content-type': 'text/html' }).end(callbackPage('Sign-in request was invalid.'))
        cleanup()
        reject(new RsoAuthError('state mismatch or missing code'))
        return
      }
      res.writeHead(200, { 'content-type': 'text/html' }).end(
        callbackPage('Signed in — you can close this window and return to RiftLens.')
      )
      cleanup()
      resolve(code)
    })

    server.on('error', (err) => {
      cleanup()
      reject(err)
    })

    server.listen(config.callbackPort, '127.0.0.1')

    timer = setTimeout(() => {
      cleanup()
      reject(new RsoAuthError('timed out waiting for Riot sign-in'))
    }, timeoutMs)
  })

  return {
    promise,
    cancel: () => {
      if (timer !== null) {
        clearTimeout(timer)
      }
      server?.close()
    }
  }
}

export async function exchangeCodeForTokens(config: RsoConfig, code: string): Promise<RsoTokens> {
  const basic = Buffer.from(`${config.clientId}:${config.clientSecret}`).toString('base64')
  const response = await fetch(RSO_TOKEN_URL, {
    method: 'POST',
    headers: {
      Authorization: `Basic ${basic}`,
      'content-type': 'application/x-www-form-urlencoded'
    },
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      code,
      redirect_uri: config.redirectUri
    }).toString()
  })
  if (!response.ok) {
    throw new RsoAuthError(`token exchange failed (${response.status})`)
  }
  const body = (await response.json()) as {
    access_token?: string
    refresh_token?: string
    expires_in?: number
  }
  if (!body.access_token) {
    throw new RsoAuthError('token response missing access_token')
  }
  return {
    accessToken: body.access_token,
    refreshToken: body.refresh_token ?? null,
    expiresAt: Date.now() + (body.expires_in ?? 3600) * 1000
  }
}

export async function fetchIdentity(accessToken: string): Promise<RsoIdentity> {
  const response = await fetch(RSO_USERINFO_URL, {
    headers: { Authorization: `Bearer ${accessToken}` }
  })
  if (!response.ok) {
    throw new RsoAuthError(`userinfo request failed (${response.status})`)
  }
  const body = (await response.json()) as {
    sub?: string
    game_name?: string
    tag_line?: string
  }
  if (!body.sub) {
    throw new RsoAuthError('userinfo response missing sub (puuid)')
  }
  return {
    puuid: body.sub,
    gameName: body.game_name ?? null,
    tagLine: body.tag_line ?? null
  }
}

function callbackPage(message: string): string {
  return `<!doctype html><html><body style="font-family:sans-serif;background:#0a0e17;color:#e2e8f0;display:flex;align-items:center;justify-content:center;height:100vh;margin:0"><p>${message}</p></body></html>`
}
