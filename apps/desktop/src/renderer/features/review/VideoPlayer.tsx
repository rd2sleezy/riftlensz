import { useEffect, useRef, type ReactElement } from 'react'
import { formatMmss } from '../../../main/sync/syncMap'

type Props = {
  src: string | null
  playheadMs: number
  onTimeMs: (tVideoMs: number) => void
  seekRequestMs: number | null
  error: string | null
  warning: string | null
  onAttach: () => void
  playbackRate: number
  onPlaybackRate: (rate: number) => void
}

export function VideoPlayer(props: Props): ReactElement {
  const videoRef = useRef<HTMLVideoElement | null>(null)

  useEffect(() => {
    const video = videoRef.current
    if (video === null || props.seekRequestMs === null) {
      return
    }
    video.currentTime = props.seekRequestMs / 1000
  }, [props.seekRequestMs])

  useEffect(() => {
    const video = videoRef.current
    if (video === null) {
      return
    }
    video.playbackRate = props.playbackRate
  }, [props.playbackRate])

  useEffect(() => {
    const video = videoRef.current
    if (video === null) {
      return
    }
    const onTimeMs = props.onTimeMs
    const rvfc = video as HTMLVideoElement & {
      requestVideoFrameCallback?: (cb: (_now: number, meta: { mediaTime: number }) => void) => number
      cancelVideoFrameCallback?: (handle: number) => void
    }
    let handle: number | null = null
    const onFrame = (_now: number, meta: { mediaTime: number }): void => {
      onTimeMs(Math.round(meta.mediaTime * 1000))
      if (rvfc.requestVideoFrameCallback !== undefined) {
        handle = rvfc.requestVideoFrameCallback(onFrame)
      }
    }
    const onTimeUpdate = (): void => {
      onTimeMs(Math.round(video.currentTime * 1000))
    }
    if (rvfc.requestVideoFrameCallback !== undefined) {
      handle = rvfc.requestVideoFrameCallback(onFrame)
    } else {
      video.addEventListener('timeupdate', onTimeUpdate)
    }
    return () => {
      if (handle !== null && rvfc.cancelVideoFrameCallback !== undefined) {
        rvfc.cancelVideoFrameCallback(handle)
      }
      video.removeEventListener('timeupdate', onTimeUpdate)
    }
  }, [props.onTimeMs, props.src])

  return (
    <section className="rounded-xl border border-rift-border bg-rift-surface p-3 shadow-card">
      {props.src === null ? (
        <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-lg bg-rift-raised/60 text-sm text-slate-400">
          <p>No VOD attached. Data-only review is still valid.</p>
          <button
            type="button"
            className="rounded-md bg-rift-accent px-3 py-1.5 font-medium text-rift-bg hover:bg-rift-accent-strong"
            onClick={props.onAttach}
          >
            Attach VOD
          </button>
        </div>
      ) : (
        <video
          ref={videoRef}
          className="aspect-video w-full rounded-lg bg-black"
          src={props.src}
          controls
          onError={() => {
            props.onTimeMs(0)
          }}
        />
      )}
      {props.error ? <p className="mt-2 text-sm text-rift-danger">{props.error}</p> : null}
      {props.warning ? <p className="mt-2 text-sm text-rift-gold">{props.warning}</p> : null}
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <button
          type="button"
          className="rounded-md bg-white/5 px-2 py-1 hover:bg-white/10"
          onClick={props.onAttach}
        >
          {props.src === null ? 'Attach VOD' : 'Replace VOD'}
        </button>
        {[0.5, 1, 2].map((rate) => (
          <button
            key={rate}
            type="button"
            className={`rounded-md px-2 py-1 transition ${
              props.playbackRate === rate
                ? 'bg-rift-accent text-rift-bg'
                : 'bg-white/5 hover:bg-white/10'
            }`}
            onClick={() => props.onPlaybackRate(rate)}
          >
            {rate}×
          </button>
        ))}
        <span className="font-mono">playhead {formatMmss(props.playheadMs)}</span>
      </div>
    </section>
  )
}
