import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./src/renderer/**/*.{html,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        rift: {
          bg: '#0a0e17',
          surface: '#10151f',
          raised: '#161c29',
          border: '#232b3d',
          edge: '#2d3752',
          accent: {
            DEFAULT: '#4fd1c5',
            soft: '#4fd1c522',
            strong: '#7ee8de'
          },
          gold: {
            DEFAULT: '#e8b95c',
            soft: '#e8b95c1f'
          },
          danger: {
            DEFAULT: '#f2596b',
            soft: '#f2596b1f'
          },
          win: '#3fc98a',
          loss: '#e2596b'
        }
      },
      fontFamily: {
        display: ['"Segoe UI Semibold"', '"Segoe UI"', 'system-ui', 'sans-serif']
      },
      boxShadow: {
        glow: '0 0 0 1px rgb(79 209 197 / 0.15), 0 8px 30px -8px rgb(79 209 197 / 0.25)',
        card: '0 1px 0 0 rgb(255 255 255 / 0.03) inset, 0 12px 24px -12px rgb(0 0 0 / 0.5)'
      },
      keyframes: {
        'fade-in': {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' }
        }
      },
      animation: {
        'fade-in': 'fade-in 240ms ease-out both'
      }
    }
  },
  plugins: []
}

export default config
