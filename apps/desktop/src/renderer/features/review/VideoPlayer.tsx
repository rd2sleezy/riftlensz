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
    <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      {props.src === null ? (
        <div className="flex h-64 flex-col items-center justify-center gap-3 text-sm text-slate-300">
          <p>No VOD attached. Data-only review is still valid.</p>
          <button
            type="button"
            className="rounded-md bg-slate-700 px-3 py-1.5 hover:bg-slate-600"
            onClick={props.onAttach}
          >
            Attach VOD
          </button>
        </div>
      ) : (
        <video
          ref={videoRef}
          className="aspect-video w-full bg-black"
          src={props.src}
          controls
          onError={() => {
            props.onTimeMs(0)
          }}
        />
      )}
      {props.error ? <p className="mt-2 text-sm text-rose-400">{props.error}</p> : null}
      {props.warning ? <p className="mt-2 text-sm text-amber-300">{props.warning}</p> : null}
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <button type="button" className="rounded bg-slate-800 px-2 py-1" onClick={props.onAttach}>
          {props.src === null ? 'Attach VOD' : 'Replace VOD'}
        </button>
        {[0.5, 1, 2].map((rate) => (
          <button
            key={rate}
            type="button"
            className={`rounded px-2 py-1 ${props.playbackRate === rate ? 'bg-sky-700 text-white' : 'bg-slate-800'}`}
            onClick={() => props.onPlaybackRate(rate)}
          >
            {rate}×
          </button>
        ))}
        <span>playhead {formatMmss(props.playheadMs)}</span>
      </div>
    </section>
  )
}
