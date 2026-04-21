import { useState, useEffect } from 'react'
import ComparisonSelector from '../components/ComparisonSelector'
import ComparisonCharts from '../components/ComparisonCharts'
import MultiVideoPlayer from '../components/MultiVideoPlayer'
import type { VideoEntry } from '../components/MultiVideoPlayer'
import api from '../api/axios'

interface VideoItem {
  id: string
  filename: string
  src?: string
}

export default function ComparePage() {
  const [selectedVideoIds, setSelectedVideoIds] = useState<string[]>([])
  const [videoMap, setVideoMap] = useState<Record<string, VideoItem>>({})

  useEffect(() => {
    api.get('/api/v1/videos')
      .then((res) => {
        const items: VideoItem[] = res.data.videos ?? res.data ?? []
        const map: Record<string, VideoItem> = {}
        items.forEach((v) => { map[v.id] = v })
        setVideoMap(map)
      })
      .catch(() => {})
  }, [])

  const playerVideos: VideoEntry[] = selectedVideoIds
    .map((id) => {
      const v = videoMap[id]
      if (!v) return null
      return { videoId: id, src: v.src ?? `/api/v1/videos/${id}/stream`, title: v.filename } satisfies VideoEntry
    })
    .filter((v): v is NonNullable<typeof v> => v !== null)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100">Compare Videos</h1>
        <p className="mt-1 text-sm text-gray-500 dark:text-gray-400">Select 2–4 videos to compare analytics and watch them side-by-side.</p>
      </div>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-1 bg-white dark:bg-gray-900 rounded-xl shadow p-4">
          <ComparisonSelector selectedVideoIds={selectedVideoIds} onSelectionChange={setSelectedVideoIds} />
        </div>
        <div className="xl:col-span-2 space-y-6">
          <ComparisonCharts videoIds={selectedVideoIds} />
          {playerVideos.length >= 2 && (
            <div className="bg-white dark:bg-gray-900 rounded-xl shadow p-4">
              <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Synchronized Playback</h2>
              <MultiVideoPlayer videos={playerVideos} />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
