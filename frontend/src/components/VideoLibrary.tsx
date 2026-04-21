import { useState, useEffect, useCallback } from 'react'
import api from '../api/axios'

// ── Types ──────────────────────────────────────────────────────────────────────

type ProcessingStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled'

interface VideoMetadata {
  video_id: string
  filename: string
  duration_seconds: number | null
  resolution: string | null
  upload_timestamp: string
  status: ProcessingStatus
}

interface PaginatedVideos {
  items: VideoMetadata[]
  total: number
  page: number
  page_size: number
}

interface VideoLibraryProps {
  onVideoSelect?: (videoId: string) => void
  /** Refresh trigger — increment to force a reload */
  refreshKey?: number
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function formatDuration(seconds: number | null): string {
  if (seconds == null) return '—'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  const mm = String(m).padStart(2, '0')
  const ss = String(s).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

function formatTimestamp(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

// ── Status badge ───────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<ProcessingStatus, string> = {
  pending:    'bg-gray-200 text-gray-700 dark:bg-gray-700 dark:text-gray-300',
  processing: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
  completed:  'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  failed:     'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
  cancelled:  'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300',
}

function StatusBadge({ status }: { status: ProcessingStatus }) {
  return (
    <span
      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${STATUS_STYLES[status] ?? STATUS_STYLES.pending}`}
    >
      {status}
    </span>
  )
}

// ── Component ──────────────────────────────────────────────────────────────────

export default function VideoLibrary({ onVideoSelect, refreshKey }: VideoLibraryProps) {
  const [page, setPage] = useState(1)
  const [data, setData] = useState<PaginatedVideos | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const PAGE_SIZE = 10

  const fetchVideos = useCallback(async (p: number) => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get<PaginatedVideos>('/api/v1/videos', {
        params: { page: p, page_size: PAGE_SIZE },
      })
      setData(res.data)
    } catch {
      setError('Failed to load videos. Please try again.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchVideos(page)
  }, [page, fetchVideos, refreshKey])

  const handleDelete = async (video: VideoMetadata) => {
    const confirmed = window.confirm(
      `Delete "${video.filename}"? This will permanently remove the video and all associated data.`
    )
    if (!confirmed) return

    setDeletingId(video.video_id)
    try {
      await api.delete(`/api/v1/videos/${video.video_id}`)
      // Remove from local list; if page is now empty and not page 1, go back
      setData((prev) => {
        if (!prev) return prev
        const items = prev.items.filter((v) => v.video_id !== video.video_id)
        const total = prev.total - 1
        return { ...prev, items, total }
      })
    } catch {
      alert(`Failed to delete "${video.filename}". Please try again.`)
    } finally {
      setDeletingId(null)
    }
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  // ── Render states ────────────────────────────────────────────────────────────

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center py-16 text-gray-500 dark:text-gray-400">
        <Spinner />
        <span className="ml-3">Loading videos…</span>
      </div>
    )
  }

  if (error && !data) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6 text-center dark:border-red-800 dark:bg-red-950">
        <p className="text-red-700 dark:text-red-300">{error}</p>
        <button
          onClick={() => fetchVideos(page)}
          className="mt-3 rounded-md bg-red-600 px-4 py-2 text-sm text-white hover:bg-red-700"
        >
          Retry
        </button>
      </div>
    )
  }

  const videos = data?.items ?? []

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
          Video Library
          {data && (
            <span className="ml-2 text-sm font-normal text-gray-500 dark:text-gray-400">
              ({data.total} {data.total === 1 ? 'video' : 'videos'})
            </span>
          )}
        </h2>
        {loading && <Spinner className="h-4 w-4 text-gray-400" />}
      </div>

      {/* Empty state */}
      {!loading && videos.length === 0 && (
        <div className="rounded-lg border border-dashed border-gray-300 py-16 text-center dark:border-gray-600">
          <p className="text-gray-500 dark:text-gray-400">No videos uploaded yet.</p>
        </div>
      )}

      {/* Video cards */}
      {videos.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-gray-200 dark:border-gray-700">
          <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
            <thead className="bg-gray-50 dark:bg-gray-800">
              <tr>
                {['Filename', 'Duration', 'Resolution', 'Uploaded', 'Status', ''].map((h) => (
                  <th
                    key={h}
                    className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-gray-500 dark:text-gray-400"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white dark:divide-gray-700 dark:bg-gray-900">
              {videos.map((video) => (
                <tr
                  key={video.video_id}
                  onClick={() => onVideoSelect?.(video.video_id)}
                  className={`transition-colors ${
                    onVideoSelect
                      ? 'cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800'
                      : ''
                  }`}
                >
                  <td className="max-w-xs truncate px-4 py-3 text-sm font-medium text-gray-900 dark:text-gray-100">
                    {video.filename}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600 dark:text-gray-300">
                    {formatDuration(video.duration_seconds)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600 dark:text-gray-300">
                    {video.resolution ?? '—'}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600 dark:text-gray-300">
                    {formatTimestamp(video.upload_timestamp)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3">
                    <StatusBadge status={video.status} />
                  </td>
                  <td
                    className="whitespace-nowrap px-4 py-3 text-right"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <button
                      onClick={() => handleDelete(video)}
                      disabled={deletingId === video.video_id}
                      aria-label={`Delete ${video.filename}`}
                      className="rounded-md px-2.5 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:text-red-400 dark:hover:bg-red-950"
                    >
                      {deletingId === video.video_id ? 'Deleting…' : 'Delete'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1 || loading}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-40 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800"
          >
            ← Previous
          </button>
          <span className="text-sm text-gray-600 dark:text-gray-400">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages || loading}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-40 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  )
}

// ── Spinner ────────────────────────────────────────────────────────────────────

function Spinner({ className = 'h-5 w-5' }: { className?: string }) {
  return (
    <svg
      className={`animate-spin ${className} text-gray-500`}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
      />
    </svg>
  )
}
