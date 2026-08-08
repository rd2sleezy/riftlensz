import { type ChildProcess, spawn } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { EventEmitter } from 'node:events'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { createInterface } from 'node:readline'
import { setTimeout as delay } from 'node:timers/promises'
import { app } from 'electron'
import { z } from 'zod'
import type { HealthPayload, SidecarStatus } from '../ipc/channels'
import { logger } from '../logging'
import { SidecarClient } from './client'

const ReadyLineSchema = z.object({
  port: z.number().int().positive(),
  pid: z.number().int().positive(),
  version: z.string()
})

const READY_PREFIX = 'RIFTLENS_READY '
const READY_TIMEOUT_MS = 30_000
const HEALTH_POLL_MS = 5_000
const MAX_HEALTH_FAILURES = 3
const MAX_RESTART_ATTEMPTS = 10
const KILL_GRACE_MS = 5_000
const BACKOFF_CAP_MS = 30_000

export type SupervisorEvents = {
  status: [SidecarStatus]
}

export class SidecarSupervisor extends EventEmitter<SupervisorEvents> {
  private child: ChildProcess | null = null
  private client: SidecarClient | null = null
  private status: SidecarStatus = { state: 'starting' }
  private token = ''
  private pollTimer: NodeJS.Timeout | null = null
  private consecutiveHealthFailures = 0
  private restartAttempts = 0
  private shuttingDown = false
  private ignoreExit = false
  private quitHookInstalled = false
  private runGeneration = 0
  private failureInFlight = false

  /** Return the last emitted status snapshot. Assumes start() has been called. */
  public getStatus(): SidecarStatus {
    return this.status
  }

  /** Proxy GET /health. Assumes the sidecar is ready. */
  public async health(): Promise<HealthPayload> {
    if (!this.client) {
      throw new Error('sidecar is not ready')
    }
    return this.client.health()
  }

  /** Spawn the sidecar and begin health polling. Assumes Electron app is ready. */
  public start(): void {
    this.installQuitHook()
    void this.spawnSidecar()
  }

  /** Kill and respawn, resetting the backoff counter. Assumes start() already ran. */
  public async restart(): Promise<void> {
    this.restartAttempts = 0
    this.consecutiveHealthFailures = 0
    this.setStatus({ state: 'restarting' })
    await this.killChild()
    await this.spawnSidecar()
  }

  /** Stop polling and terminate the child. Assumes the app is quitting. */
  public async stop(): Promise<void> {
    this.shuttingDown = true
    this.clearPoll()
    await this.killChild()
  }

  private installQuitHook(): void {
    if (this.quitHookInstalled) {
      return
    }
    this.quitHookInstalled = true
    app.on('before-quit', (event) => {
      if (this.shuttingDown) {
        return
      }
      event.preventDefault()
      void this.stop().finally(() => {
        app.quit()
      })
    })
  }

  private async spawnSidecar(): Promise<void> {
    if (this.shuttingDown) {
      return
    }
    const generation = ++this.runGeneration
    this.setStatus({ state: this.restartAttempts > 0 ? 'restarting' : 'starting' })
    this.token = randomBytes(32).toString('hex')
    const launch = resolveSidecarLaunch()
    logger.info({ command: launch.command, args: launch.args.slice(0, 3) }, 'spawning sidecar')

    const child = spawn(
      launch.command,
      [...launch.args, '--host', '127.0.0.1', '--port', '0', '--token', this.token],
      {
        cwd: launch.cwd,
        env: {
          ...process.env,
          PYTHONUNBUFFERED: '1',
          PYTHONWARNINGS: 'default'
        },
        stdio: ['ignore', 'pipe', 'pipe']
      }
    )
    this.child = child

    child.stderr?.on('data', (chunk: Buffer) => {
      logger.info({ sidecar: chunk.toString('utf8').trimEnd() }, 'sidecar stderr')
    })

    child.on('exit', (code, signal) => {
      logger.warn({ code, signal, generation }, 'sidecar exited')
      if (this.shuttingDown || this.ignoreExit || generation !== this.runGeneration) {
        return
      }
      void this.handleFailure('sidecar process exited')
    })

    try {
      const ready = await this.readReadyLine(child, READY_TIMEOUT_MS)
      if (generation !== this.runGeneration) {
        return
      }
      this.client = new SidecarClient(`http://127.0.0.1:${ready.port}`, this.token)
      const health = await this.client.health()
      this.consecutiveHealthFailures = 0
      this.restartAttempts = 0
      this.setStatus({
        state: 'ready',
        version: health.version,
        port: ready.port,
        pid: ready.pid,
        dbPath: health.db_path
      })
      this.beginHealthPoll()
    } catch (error) {
      logger.error({ err: error }, 'sidecar failed to become ready')
      if (generation !== this.runGeneration) {
        return
      }
      await this.handleFailure(error instanceof Error ? error.message : 'sidecar start failed')
    }
  }

  private beginHealthPoll(): void {
    this.clearPoll()
    this.pollTimer = setInterval(() => {
      void this.pollHealth()
    }, HEALTH_POLL_MS)
    this.pollTimer.unref?.()
  }

  private async pollHealth(): Promise<void> {
    if (!this.client || this.shuttingDown) {
      return
    }
    try {
      const health = await this.client.health()
      this.consecutiveHealthFailures = 0
      this.setStatus({
        ...this.status,
        state: 'ready',
        version: health.version,
        dbPath: health.db_path
      })
    } catch (error) {
      this.consecutiveHealthFailures += 1
      logger.warn(
        { failures: this.consecutiveHealthFailures, err: error },
        'sidecar health check failed'
      )
      this.setStatus({
        ...this.status,
        state: 'unhealthy',
        error: error instanceof Error ? error.message : 'health check failed'
      })
      if (this.consecutiveHealthFailures >= MAX_HEALTH_FAILURES) {
        await this.handleFailure('health check failed 3 times')
      }
    }
  }

  private async handleFailure(reason: string): Promise<void> {
    if (this.shuttingDown || this.failureInFlight) {
      return
    }
    this.failureInFlight = true
    this.clearPoll()
    await this.killChild()
    try {
      this.restartAttempts += 1
      if (this.restartAttempts > MAX_RESTART_ATTEMPTS) {
        this.setStatus({ state: 'failed', error: reason })
        return
      }
      const backoffMs = Math.min(1000 * 2 ** (this.restartAttempts - 1), BACKOFF_CAP_MS)
      this.setStatus({ state: 'restarting', error: reason })
      logger.info({ backoffMs, attempt: this.restartAttempts }, 'restarting sidecar')
      await delay(backoffMs)
      await this.spawnSidecar()
    } finally {
      this.failureInFlight = false
    }
  }

  private async readReadyLine(
    child: ChildProcess,
    timeoutMs: number
  ): Promise<z.infer<typeof ReadyLineSchema>> {
    const stdout = child.stdout
    if (!stdout) {
      throw new Error('sidecar stdout is not piped')
    }
    const rl = createInterface({ input: stdout })
    try {
      return await new Promise((resolveReady, rejectReady) => {
        const timer = setTimeout(() => {
          rejectReady(new Error(`timed out waiting for ${READY_PREFIX.trim()} after ${timeoutMs}ms`))
        }, timeoutMs)

        const onLine = (line: string): void => {
          if (!line.startsWith(READY_PREFIX)) {
            return
          }
          try {
            const parsed = ReadyLineSchema.parse(JSON.parse(line.slice(READY_PREFIX.length)))
            clearTimeout(timer)
            rl.off('line', onLine)
            resolveReady(parsed)
          } catch (error) {
            clearTimeout(timer)
            rl.off('line', onLine)
            rejectReady(error)
          }
        }

        rl.on('line', onLine)
        child.once('error', (error) => {
          clearTimeout(timer)
          rejectReady(error)
        })
      })
    } finally {
      rl.close()
    }
  }

  private async killChild(): Promise<void> {
    const child = this.child
    this.child = null
    this.client = null
    if (!child || child.exitCode !== null || child.signalCode) {
      return
    }
    this.ignoreExit = true
    try {
      await terminateProcess(child, KILL_GRACE_MS)
    } finally {
      this.ignoreExit = false
    }
  }

  private clearPoll(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer)
      this.pollTimer = null
    }
  }

  private setStatus(next: SidecarStatus): void {
    this.status = next
    this.emit('status', next)
  }
}

type SidecarLaunch = {
  command: string
  args: string[]
  cwd?: string
}

/** Resolve python -m riftlens.main in dev, or the packaged binary in production. */
export function resolveSidecarLaunch(): SidecarLaunch {
  if (app.isPackaged) {
    const binary = process.platform === 'win32' ? 'riftlens-sidecar.exe' : 'riftlens-sidecar'
    return {
      command: path.join(process.resourcesPath, binary),
      args: []
    }
  }
  const repoRoot = findRepoRoot(__dirname)
  const analysisRoot = path.join(repoRoot, 'services', 'analysis')
  const venvPython =
    process.platform === 'win32'
      ? path.join(analysisRoot, '.venv', 'Scripts', 'python.exe')
      : path.join(analysisRoot, '.venv', 'bin', 'python')
  const command = existsSync(venvPython)
    ? venvPython
    : (process.env['RIFTLENS_PYTHON'] ?? 'python')
  return {
    command,
    args: ['-m', 'riftlens.main'],
    cwd: analysisRoot
  }
}

function findRepoRoot(startDir: string): string {
  let dir = startDir
  for (let i = 0; i < 10; i += 1) {
    if (existsSync(path.join(dir, 'pnpm-workspace.yaml'))) {
      return dir
    }
    const parent = path.dirname(dir)
    if (parent === dir) {
      break
    }
    dir = parent
  }
  throw new Error(`could not find repo root from ${startDir}`)
}

async function terminateProcess(child: ChildProcess, graceMs: number): Promise<void> {
  if (!child.pid) {
    return
  }
  if (process.platform === 'win32') {
    spawn('taskkill', ['/pid', String(child.pid), '/t', '/f'], { stdio: 'ignore' })
    await delay(200)
    return
  }
  child.kill('SIGTERM')
  const exited = await Promise.race([
    new Promise<boolean>((resolve) => {
      child.once('exit', () => resolve(true))
    }),
    delay(graceMs).then(() => false)
  ])
  if (!exited && child.pid) {
    child.kill('SIGKILL')
  }
}
