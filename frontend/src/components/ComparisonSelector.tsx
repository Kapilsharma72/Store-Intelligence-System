import { useState, useEffect } from 'react'
import api from '../api/axios'

interface VideoItem {
  id: string
  filename: string
  duration_seconds: number
  resolution: string
  upload_timestamp: string
  status: string
  store_config: string
}

interface ComparisonSelectorProps {
  selectedVideoIds: string[]
  onSelectionChange: (videoIds: string[]) => void
}

export default function ComparisonSelector({ selectedVideoIds, onSelectionChange }: ComparisonSelectorProps) {
  const [videos, setVideos] = useState<VideoItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    api.get('/api/v1/videos')
      .then((res) => { setVideos(res.data.videos ?? res.data ?? []) })
      .catch(() => setError('Failed to load videos.'))
      .finally(() => setLoading(false))
  }, [])

  const selectedVideos = videos.filter((v) => selectedVideoIds.includes(v.id))
  const storeConfigs = new Set(selectedVideos.map((v) => v.store_config).filter(Boolean))
  const hasMixedConfigs = storeConfigs.size > 1

  function toggle(id: string) {
    if (selectedVideoIds.includes(id)) onSelectionChange(selectedVideoIds.filter((x) => x !== id))
    else if (selectedVideoIds.length < 4) onSelectionChange([...selectedVideoIds, id])
  }

  if (loading) return <div className="flex items-center justify-center h-32 text-gray-500 dark:text-gray-400 text-sm">Loading videos…</div>
  if (error) return <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4 text-sm text-red-700 dark:text-red-300">{error}</div>

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300">Select Videos to Compare</h2>
        <span className="text-xs text-gray-500 dark:text-gray-400">{selectedVideoIds.length} / 4 selected</span>
      </div>
      {hasMixedConfigs && (
        <div className="flex items-start gap-2 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 p-3 text-sm text-amber-800 dark:text-amber-300">
          <svg className="w-4 h-4 mt-0.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" /></svg>
          <span>Selected videos have different store configurations. Zone-level comparisons may not be meaningful.</span>
        </div>
      )}
      {selectedVideoIds.length < 2 && <p className="text-xs text-gray-500 dark:text-gray-400">Select at least 2 videos to enable comparison.</p>}
      <div className="divide-y divide-gray-100 dark:divide-gray-800 rounded-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
        {videos.length === 0 && <div className="p-4 text-sm text-gray-500 dark:text-gray-400 text-center">No videos available.</div>}
        {videos.map((video) => {
          const checked = selectedVideoIds.includes(video.id)
          const disabled = !checked && selectedVideoIds.length >= 4
          return (
            <label key={video.id} className={`flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors ${disabled ? 'opacity-40 cursor-not-allowed' : 'hover:bg-gray-50 dark:hover:bg-gray-800/50'} ${checked ? 'bg-indigo-50 dark:bg-indigo-900/20' : 'bg-white dark:bg-gray-900'}`}>
              <input type="checkbox" checked={checked} disabled={disabled} onChange={() => toggle(video.id)} className="w-4 h-4 rounded accent-indigo-600" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{video.filename}</p>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                  {video.resolution} · {formatDuration(video.duration_seconds)} · {video.status}
                  {video.store_config && <span className="ml-2 px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 font-mono text-gray-600 dark:text-gray-400">{video.store_config}</span>}
                </p>
              </div>
              {checked && <span className="shrink-0 w-5 h-5 rounded-full bg-indigo-600 flex items-center justify-center"><svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}><path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" /></svg></span>}
            </label>
          )
        })}
      </div>
    </div>
  )
}

function formatDuration(seconds: number): string {
  if (!seconds || !isFinite(seconds)) return '—'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}
