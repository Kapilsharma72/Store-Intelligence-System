import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/axios'

interface Video {
  id: string
  filename: string
  status: string
  upload_timestamp: string
  duration_seconds?: number
}

export default function AnalyticsListPage() {
  const [videos, setVideos] = useState<Video[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchVideos()
  }, [])

  async function fetchVideos() {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/videos')
      setVideos(response.data.items || [])
      setError(null)
    } catch (err: any) {
      setError(err.message || 'Failed to load videos')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="col-span-full">
        <h1 className="text-2xl font-bold mb-4">Analytics</h1>
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="col-span-full">
        <h1 className="text-2xl font-bold mb-4">Analytics</h1>
        <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4">
          <p className="text-red-800 dark:text-red-200">Error: {error}</p>
        </div>
      </div>
    )
  }

  const processedVideos = videos.filter(v => v.status === 'completed')

  return (
    <>
      <div className="col-span-full">
        <h1 className="text-2xl font-bold mb-4">Analytics</h1>
        <p className="text-gray-600 dark:text-gray-400 mb-6">
          Select a processed video to view detailed analytics and insights.
        </p>
      </div>

      {processedVideos.length === 0 ? (
        <div className="col-span-full">
          <div className="bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-6 text-center">
            <svg className="w-16 h-16 text-yellow-600 dark:text-yellow-400 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
            </svg>
            <h3 className="text-lg font-semibold mb-2">No Processed Videos</h3>
            <p className="text-gray-600 dark:text-gray-400 mb-4">
              You need to upload and process videos before viewing analytics.
            </p>
            <Link 
              to="/videos" 
              className="inline-block bg-blue-600 hover:bg-blue-700 text-white font-medium px-6 py-2 rounded transition-colors"
            >
              Go to Videos →
            </Link>
          </div>
        </div>
      ) : (
        <div className="col-span-full grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {processedVideos.map((video) => (
            <Link
              key={video.id}
              to={`/analytics/${video.id}`}
              className="block bg-white dark:bg-gray-800 rounded-lg shadow hover:shadow-lg transition-shadow border border-gray-200 dark:border-gray-700 p-4"
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex-1">
                  <h3 className="font-semibold text-lg mb-1 truncate">{video.filename}</h3>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    {new Date(video.upload_timestamp).toLocaleDateString()}
                  </p>
                </div>
                <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">
                  Processed
                </span>
              </div>
              
              {video.duration_seconds && (
                <p className="text-sm text-gray-600 dark:text-gray-400 mb-3">
                  Duration: {Math.floor(video.duration_seconds / 60)}m {Math.floor(video.duration_seconds % 60)}s
                </p>
              )}

              <div className="flex items-center text-blue-600 dark:text-blue-400 text-sm font-medium">
                View Analytics
                <svg className="w-4 h-4 ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  )
}
