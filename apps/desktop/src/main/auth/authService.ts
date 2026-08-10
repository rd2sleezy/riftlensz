import { EventEmitter } from 'node:events'
import { shell } from 'electron'
import type { AuthSession, SignInResult } from '../ipc/channels'
import { logger } from '../logging'
import { loadRsoConfig } from './rsoConfig'
import {
  awaitAuthorizationCode,
  buildAuthorizeUrl,
  exchangeCodeForTokens,
  fetchIdentity,
  generateState,
  RsoAuthCancelledError
} from './rsoClient'
import { clearSession, loadSession, saveSession, type StoredSession } from './sessionStore'

export type AuthServiceEvents = {
  session: [AuthSession]
}

const SIGNED_OUT: AuthSession = {
  signedIn: false,
  puuid: null,
  gameName: null,
  tagLine: null,
  signedInAt: null
}

export class AuthService extends EventEmitter<AuthServiceEvents> {
  private stored: StoredSession | null = null
  private pendingCancel: (() => void) | null = null

  /** Load any persisted session from disk. Assumes app.getPath is available (post whenReady). */
  public start(): void {
    this.stored = loadSession()
  }

  public getSession(): AuthSession {
    return this.stored === null ? SIGNED_OUT : toPublicSession(this.stored)
  }

  public async signIn(): Promise<SignInResult> {
    const config = loadRsoConfig()
    if (config === null) {
      return {
        ok: false,
        code: 'AUTH_NOT_CONFIGURED',
        message:
          'Riot sign-in is not configured. Set RIFTLENS_RIOT_CLIENT_ID and RIFTLENS_RIOT_CLIENT_SECRET ' +
          '(from an approved RSO client on the Riot Developer Portal) to enable it.'
      }
    }

    this.pendingCancel?.()
    const state = generateState()
    const { promise, cancel } = awaitAuthorizationCode(config, state)
    this.pendingCancel = cancel

    try {
      void shell.openExternal(buildAuthorizeUrl(config, state))
      const code = await promise
      const tokens = await exchangeCodeForTokens(config, code)
      const identity = await fetchIdentity(tokens.accessToken)
      const session: StoredSession = { tokens, identity, signedInAt: Date.now() }
      this.stored = session
      saveSession(session)
      const publicSession = toPublicSession(session)
      this.emit('session', publicSession)
      return { ok: true, session: publicSession }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Sign-in failed'
      const code = error instanceof RsoAuthCancelledError ? 'AUTH_CANCELLED' : 'AUTH_FAILED'
      logger.warn({ err: message }, 'riot sign-in failed')
      return { ok: false, code, message }
    } finally {
      this.pendingCancel = null
    }
  }

  public signOut(): AuthSession {
    this.pendingCancel?.()
    this.pendingCancel = null
    this.stored = null
    clearSession()
    this.emit('session', SIGNED_OUT)
    return SIGNED_OUT
  }
}

function toPublicSession(stored: StoredSession): AuthSession {
  return {
    signedIn: true,
    puuid: stored.identity.puuid,
    gameName: stored.identity.gameName,
    tagLine: stored.identity.tagLine,
    signedInAt: stored.signedInAt
  }
}
