import { expect, test, _electron as electron, type ElectronApplication } from '@playwright/test'
import { execSync } from 'node:child_process'
import path from 'node:path'

const desktopRoot = path.resolve(__dirname, '..')
const mainEntry = path.join(desktopRoot, 'out', 'main', 'index.js')

function launchEnv(): Record<string, string> {
  const env: Record<string, string> = {}
  for (const [key, value] of Object.entries(process.env)) {
    // Inherited from some hosts; makes Electron treat argv as Node flags and reject
    // Playwright's --remote-debugging-port=0 (Electron 30+).
    if (key === 'ELECTRON_RUN_AS_NODE' || value === undefined) {
      continue
    }
    env[key] = value
  }
  env['RIFTLENS_E2E'] = '1'
  return env
}

async function launchApp(): Promise<ElectronApplication> {
  return electron.launch({
    args: [mainEntry],
    cwd: desktopRoot,
    env: launchEnv()
  })
}

function killPortListener(port: number): void {
  if (process.platform === 'win32') {
    const rows = execSync('netstat -ano').toString().split('\n')
    const match = rows.find((row) => row.includes(`:${port}`) && row.includes('LISTENING'))
    const pid = match?.trim().split(/\s+/).pop()
    if (pid) {
      execSync(`taskkill /PID ${pid} /F`)
    }
    return
  }
  const pids = execSync(`lsof -t -iTCP:${port} -sTCP:LISTEN`)
    .toString()
    .trim()
    .split('\n')
    .filter(Boolean)
  for (const pid of pids) {
    process.kill(Number(pid), 'SIGKILL')
  }
}

test('built app shows sidecar ready status within 20s', async () => {
  const electronApp = await launchApp()
  try {
    const window = await electronApp.firstWindow()
    await expect(window.getByTestId('sidecar-status')).toHaveText(
      /Sidecar: ready · v0\.1\.0 · port \d+/,
      { timeout: 20_000 }
    )
  } finally {
    await electronApp.close()
  }
})

test('killing the sidecar process shows restarting then ready within 10s', async () => {
  const electronApp = await launchApp()
  try {
    const window = await electronApp.firstWindow()
    const status = window.getByTestId('sidecar-status')
    await expect(status).toHaveText(/Sidecar: ready · v0\.1\.0 · port \d+/, { timeout: 20_000 })
    const text = await status.innerText()
    const portMatch = /port (\d+)/.exec(text)
    if (!portMatch?.[1]) {
      throw new Error(`could not parse sidecar port from: ${text}`)
    }
    killPortListener(Number(portMatch[1]))
    await expect(status).toHaveText(/Sidecar: restarting/, { timeout: 8_000 })
    await expect(status).toHaveText(/Sidecar: ready · v0\.1\.0 · port \d+/, { timeout: 10_000 })
  } finally {
    await electronApp.close()
  }
})
