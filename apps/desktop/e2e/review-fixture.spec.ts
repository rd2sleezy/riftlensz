import { expect, test, _electron as electron, type ElectronApplication } from '@playwright/test'
import path from 'node:path'

const desktopRoot = path.resolve(__dirname, '..')
const mainEntry = path.join(desktopRoot, 'out', 'main', 'index.js')

function launchEnv(): Record<string, string> {
  const env: Record<string, string> = {}
  for (const [key, value] of Object.entries(process.env)) {
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

test('fixture B review shows H.8 focus items, metrics, and unpaired warning', async () => {
  test.setTimeout(90_000)
  const electronApp = await launchApp()
  try {
    const window = await electronApp.firstWindow()
    await expect(window.getByTestId('sidecar-status')).toHaveText(
      /Sidecar: ready · v0\.1\.0 · port \d+/,
      { timeout: 20_000 }
    )
    await window.getByTestId('open-fixture-b').click()
    await expect(window.getByTestId('review-identity')).toBeVisible({ timeout: 70_000 })
    await expect(window.getByTestId('focus-items')).toBeVisible()
    await expect(window.getByTestId('metric-summary')).toBeVisible()
    await expect(window.getByTestId('fixture-warning')).toContainText(/not the same real game/i)
  } finally {
    await electronApp.close()
  }
})
