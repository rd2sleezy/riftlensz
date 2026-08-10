import { useEffect, useRef, useState, type ReactElement } from 'react'

type Props = {
  nativeReplaySupported: boolean
  onImportReplay: () => void
  onAttachVideo: () => void
}

export function AddGameplayMenu(props: Props): ReactElement {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!open) {
      return
    }
    const onDoc = (event: MouseEvent): void => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        data-testid="add-gameplay"
        className="rounded bg-slate-800 px-3 py-1.5 text-sm hover:bg-slate-700"
        onClick={() => setOpen((value) => !value)}
      >
        Add Gameplay ▾
      </button>
      {open ? (
        <div
          className="absolute right-0 z-20 mt-1 w-72 rounded border border-slate-700 bg-slate-900 py-1 shadow-lg"
          data-testid="add-gameplay-menu"
        >
          <button
            type="button"
            data-testid="import-league-replay"
            data-native-replay={props.nativeReplaySupported ? 'enabled' : 'disabled'}
            disabled={!props.nativeReplaySupported}
            title={props.nativeReplaySupported ? undefined : 'Available on Windows'}
            className="block w-full px-3 py-2 text-left text-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:text-slate-500"
            onClick={() => {
              setOpen(false)
              props.onImportReplay()
            }}
          >
            Import League Replay (.rofl)
            {!props.nativeReplaySupported ? (
              <span className="mt-0.5 block text-xs text-slate-400">Available on Windows</span>
            ) : null}
          </button>
          <button
            type="button"
            data-testid="attach-video-menu"
            className="block w-full px-3 py-2 text-left text-sm hover:bg-slate-800"
            onClick={() => {
              setOpen(false)
              props.onAttachVideo()
            }}
          >
            Attach Video
          </button>
        </div>
      ) : null}
    </div>
  )
}
