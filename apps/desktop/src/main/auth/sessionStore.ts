import { app, safeStorage } from 'electron'
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import type { RsoIdentity, RsoTokens } from './rsoClient'

export type StoredSession = {
  tokens: RsoTokens
  identity: RsoIdentity
  signedInAt: number
}

function sessionFilePath(): string {
  return join(app.getPath('userData'), 'auth', 'session.enc')
}

/** Persist the session encrypted at rest via the OS keychain/DPAPI. Local-only, no server. */
export function saveSession(session: StoredSession): void {
  const path = sessionFilePath()
  mkdirSync(dirname(path), { recursive: true })
  const plaintext = JSON.stringify(session)
  const payload = safeStorage.isEncryptionAvailable()
    ? safeStorage.encryptString(plaintext)
    : Buffer.from(plaintext, 'utf8')
  writeFileSync(path, payload)
}

export function loadSession(): StoredSession | null {
  try {
    const payload = readFileSync(sessionFilePath())
    const plaintext = safeStorage.isEncryptionAvailable()
      ? safeStorage.decryptString(payload)
      : payload.toString('utf8')
    return JSON.parse(plaintext) as StoredSession
  } catch {
    return null
  }
}

export function clearSession(): void {
  try {
    rmSync(sessionFilePath(), { force: true })
  } catch {
    // nothing to clear
  }
}
