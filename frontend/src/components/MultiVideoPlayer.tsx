import { useRef, useState, useCallback, useEffect } from 'react'

export interface VideoEntry {
  videoId: string
  src: string
  title?: string
}

interface MultiVideoPlayerProps {
  videos: VideoEntry[]
}

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || isNaN(seconds)) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function MultiVideoPlayer({ videos }: MultiVideoPlayerProps) {
  const videoRefs = useRef<(HTMLVideoElement | null)[]>([])
  const [playing, setPlaying] = useState(false)
  const [currentTimes, setCurrentTimes] = useState<number[]>(() => videos.map(() => 0))
  const [durations, setDurations] = useState<number[]>(() => videos.map(() => 0))
  const [seekPct, setSeekPct] = useState(0)
  const isSeeking = useRef(false)

  useEffect(() => {
    videoRefs.current = videoRefs.current.slice(0, videos.length)
    setCurrentTimes(videos.map(() => 0))
    setDurations(videos.map(() => 0))
    setSeekPct(0)
    setPlaying(false)
  }, [videos.map((v) => v.videoId).join(',')])

  const allDurationsLoaded = durations.every((d) => d > 0)
  const hasDurationMismatch = allDurationsLoaded && new Set(durations.map((d) => Math.round(d))).size > 1

  const handleTimeUpdate = useCallback((index: number) => {
    const video = videoRefs.current[index]
    if (!video) return
    setCurrentTimes((prev) => { const next = [...prev]; next[index] = video.currentTime; return next })
    if (index === 0 && !isSeeking.current) {
      const dur = durations[0]
      if (dur > 0) setSeekPct((video.currentTime / dur) * 100)
    }
  }, [durations])

  const handleLoadedMetadata = useCallback((index: number) => {
    const video = videoRefs.current[index]
    if (!video) return
    setDurations((prev) => { const next = [...prev]; next[index] = video.duration; return next })
  }, [])

  const handlePlayPause = useCallback(() => {
    const refs = videoRefs.current.filter(Boolean) as HTMLVideoElement[]
    if (playing) { refs.forEach((v) => v.pause()); setPlaying(false) }
    else { refs.forEach((v) => v.play().catch(() => {})); setPlaying(true) }
  }, [playing])

  const seekAllToPct = useCallback((pct: number) => {
    videoRefs.current.forEach((video, i) => {
      if (!video) return
      const dur = durations[i]
      if (dur > 0) video.currentTime = (pct / 100) * dur
    })
    setSeekPct(pct)
  }, [durations])

  const handleSeekChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    isSeeking.current = true
    seekAllToPct(parseFloat(e.target.value))
  }, [seekAllToPct])

  if (videos.length < 2) return (
    <div className="flex items-center justify-center h-32 text-sm text-gray-500 dark:text-gray-400">Select at least 2 videos to enable synchronized playback.</div>
  )

  return (
    <div className="space-y-4">
      {hasDurationMismatch && (
        <div className="flex items-start gap-2 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 p-3 text-sm text-amber-800 dark:text-amber-300">
          <svg className="w-4 h-4 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" /></svg>
          <span>Videos have different durations. Seek position is normalized to percentage.</span>
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        {videos.map((video, i) => (
          <div key={video.videoId} className="flex flex-col gap-1">
            {video.title && <p className="text-xs font-medium text-gray-600 dark:text-gray-400 truncate px-1">{video.title}</p>}
            <div className="relative bg-black rounded-lg overflow-hidden aspect-video">
              <video ref={(el) => { videoRefs.current[i] = el }} src={video.src} controls={false} className="w-full h-full object-contain"
                onTimeUpdate={() => handleTimeUpdate(i)} onLoadedMetadata={() => handleLoadedMetadata(i)} onEnded={() => setPlaying(false)} />
            </div>
          </div>
        ))}
      </div>
      <div className="bg-white dark:bg-gray-900 rounded-xl shadow p-4 space-y-3">
        <input type="range" min={0} max={100} step={0.1} value={seekPct} onChange={handleSeekChange}
          onMouseUp={() => { isSeeking.current = false }} onTouchEnd={() => { isSeeking.current = false }}
          className="w-full h-2 appearance-none rounded-full cursor-pointer bg-gray-200 dark:bg-gray-700 accent-indigo-500" aria-label="Seek all videos" />
        <div className="flex items-center gap-4">
          <button onClick={handlePlayPause}
            className="flex items-center justify-center w-10 h-10 rounded-full bg-indigo-600 hover:bg-indigo-700 text-white transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-400"
            aria-label={playing ? 'Pause all' : 'Play all'}>
            {playing ? <PauseIcon /> : <PlayIcon />}
          </button>
          <span className="text-xs text-gray-500 dark:text-gray-400">{playing ? 'Playing all' : 'Paused'} · {seekPct.toFixed(1)}%</span>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        {videos.map((video, i) => (
          <div key={video.videoId} className="bg-white dark:bg-gray-900 rounded-xl shadow p-3 space-y-1">
            <p className="text-xs font-semibold text-gray-700 dark:text-gray-300 truncate">{video.title ?? video.videoId}</p>
            <div className="flex items-center gap-3 text-xs text-gray-600 dark:text-gray-400">
              <span><span className="font-medium text-indigo-600 dark:text-indigo-400">Time: </span>{formatTime(currentTimes[i])}</span>
              <span>/ {formatTime(durations[i])}</span>
            </div>
            {durations[i] > 0 && <div className="w-full bg-gray-100 dark:bg-gray-800 rounded-full h-1"><div className="bg-indigo-500 h-1 rounded-full transition-all" style={{ width: `${(currentTimes[i] / durations[i]) * 100}%` }} /></div>}
          </div>
        ))}
      </div>
    </div>
  )
}

function PlayIcon() { return <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5 ml-0.5"><path d="M8 5v14l11-7z" /></svg> }
function PauseIcon() { return <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" /></svg> }
