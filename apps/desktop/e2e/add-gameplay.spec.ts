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

test('Add Gameplay menu explains native replay availability and keeps H.9 attach', async () => {
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
    await expect(window.getByTestId('gameplay-status-bar')).toContainText(/No gameplay attached/i)
    await expect(window.getByTestId('attach-vod').first()).toBeVisible()
    await window.getByTestId('add-gameplay').click()
    const native = window.getByTestId('import-league-replay')
    await expect(native).toBeVisible()
    await expect(window.getByTestId('attach-video-menu')).toBeVisible()
    if (process.platform === 'win32') {
      await expect(native).toBeEnabled()
      await expect(native).toHaveAttribute('data-native-replay', 'enabled')
    } else {
      await expect(native).toBeDisabled()
      await expect(native).toHaveAttribute('data-native-replay', 'disabled')
      await expect(native).toContainText(/Available on Windows/i)
    }
    await expect(window.getByTestId('focus-items')).toBeVisible()
    await expect(window.getByTestId('metric-summary')).toBeVisible()
    await expect(window.getByTestId('manual-vod-sync')).toBeVisible()
  } finally {
    await electronApp.close()
  }
})
