import type { ReactElement } from 'react'

export function SplashScreen({ fading }: { fading: boolean }): ReactElement {
  return (
    <div
      className={`fixed inset-0 z-50 flex flex-col items-center justify-center bg-rift-bg transition-opacity duration-[420ms] ease-out ${
        fading ? 'pointer-events-none opacity-0' : 'opacity-100'
      }`}
    >
      <div className="relative flex h-20 w-20 items-center justify-center">
        <span className="absolute inset-0 rounded-full border border-rift-accent/40 animate-splash-ring" />
        <span
          className="absolute inset-0 rounded-full border border-rift-accent/40 animate-splash-ring"
          style={{ animationDelay: '450ms' }}
        />
        <span className="flex h-16 w-16 items-center justify-center rounded-2xl bg-rift-accent-soft text-rift-accent-strong animate-splash-mark">
          <svg viewBox="0 0 24 24" className="h-9 w-9" fill="none" aria-hidden="true">
            <path
              d="M12 2 3 7v6c0 5 4 8.5 9 9 5-.5 9-4 9-9V7l-9-5Z"
              stroke="currentColor"
              strokeWidth="1.4"
              strokeLinejoin="round"
            />
            <path d="M12 7v10M8 9.5l8 5M16 9.5l-8 5" stroke="currentColor" strokeWidth="1.1" />
          </svg>
        </span>
      </div>
      <p className="mt-4 font-display text-lg font-semibold tracking-tight text-slate-100 animate-splash-word">
        RiftLens
      </p>
    </div>
  )
}
