import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./src/renderer/**/*.{html,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        rift: {
          bg: '#0a0a0b',
          surface: '#141415',
          raised: '#1c1c1e',
          border: '#2a2a2c',
          edge: '#3a3a3d',
          accent: {
            DEFAULT: '#F0313D',
            soft: '#F0313D22',
            strong: '#FF6B74'
          },
          gold: {
            DEFAULT: '#e8b95c',
            soft: '#e8b95c1f'
          },
          danger: {
            DEFAULT: '#EF705D',
            soft: '#EF705D1f'
          },
          win: '#3fc98a',
          loss: '#e2596b'
        }
      },
      fontFamily: {
        display: ['"Segoe UI Semibold"', '"Segoe UI"', 'system-ui', 'sans-serif']
      },
      boxShadow: {
        glow: '0 0 0 1px rgb(240 49 61 / 0.18), 0 8px 30px -8px rgb(240 49 61 / 0.28)',
        card: '0 1px 0 0 rgb(255 255 255 / 0.03) inset, 0 12px 24px -12px rgb(0 0 0 / 0.5)'
      },
      keyframes: {
        'fade-in': {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' }
        },
        'splash-mark': {
          '0%': { opacity: '0', transform: 'scale(0.82)' },
          '60%': { opacity: '1', transform: 'scale(1.03)' },
          '100%': { opacity: '1', transform: 'scale(1)' }
        },
        'splash-word': {
          '0%': { opacity: '0', transform: 'translateY(3px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' }
        },
        'splash-ring': {
          '0%': { opacity: '0', transform: 'scale(0.9)' },
          '50%': { opacity: '0.5' },
          '100%': { opacity: '0', transform: 'scale(1.35)' }
        }
      },
      animation: {
        'fade-in': 'fade-in 240ms ease-out both',
        'splash-mark': 'splash-mark 700ms cubic-bezier(0.16, 1, 0.3, 1) both',
        'splash-word': 'splash-word 500ms ease-out 260ms both',
        'splash-ring': 'splash-ring 1600ms cubic-bezier(0.16, 1, 0.3, 1) infinite'
      }
    }
  },
  plugins: []
}

export default config
