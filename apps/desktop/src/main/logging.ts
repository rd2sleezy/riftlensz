import pino from 'pino'

export const logger = pino({
  name: 'riftlens-desktop',
  level: process.env['RIFTLENS_LOG_LEVEL'] ?? 'info',
  redact: {
    paths: [
      'token',
      '*.token',
      'SIDECAR_TOKEN',
      'req.headers.authorization',
      'headers.authorization'
    ],
    censor: '[REDACTED]'
  }
})
