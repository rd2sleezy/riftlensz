import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { OverlayApp } from './features/overlay/OverlayApp'
import './styles/globals.css'
import './styles/overlay.css'

const rootEl = document.getElementById('root')
if (!rootEl) {
  throw new Error('overlay root element is missing')
}

createRoot(rootEl).render(
  <StrictMode>
    <OverlayApp />
  </StrictMode>
)
