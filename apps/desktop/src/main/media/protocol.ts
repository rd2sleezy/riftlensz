import { existsSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { net, protocol } from 'electron'

export const MEDIA_SCHEME = 'riftmedia'

/** Register the privileged scheme. Must run before ``app.ready``. */
export function registerMediaScheme(): void {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: MEDIA_SCHEME,
      privileges: {
        standard: true,
        secure: true,
        supportFetchAPI: true,
        stream: true,
        corsEnabled: true
      }
    }
  ])
}

/** Serve local files to ``<video>`` after path validation. */
export function handleMediaProtocol(): void {
  protocol.handle(MEDIA_SCHEME, (request) => {
    const parsed = new URL(request.url)
    const filePath = decodeURIComponent(parsed.searchParams.get('p') ?? '')
    if (filePath.length === 0 || !existsSync(filePath)) {
      return new Response('Video file not found', { status: 404 })
    }
    return net.fetch(pathToFileURL(filePath).href)
  })
}

/** Return a renderer-safe URL for a validated local video path. */
export function mediaUrlForPath(filePath: string): string {
  return `${MEDIA_SCHEME}://local/vod?p=${encodeURIComponent(filePath)}`
}
