import { useState, useEffect, useCallback } from 'react'
import api from '../api/axios'

interface HighWaitPeriod {
  period_start: number
  period_end: number
  avg_wait_seconds: number
}

interface QueueAnalysisResponse {
  avg_wait_time_seconds: number
  max_wait_time_seconds: number
  abandonment_count: number
  abandonment_rate: number
  high_wait_periods: HighWaitPeriod[]
}

interface QueueAnalysisPanelProps {
  videoId: string
}

function formatSeconds(s: number): string {
  if (s < 60) return `${s.toFixed(0)}s`
  const m = Math.floor(s / 60)
  const rem = Math.round(s % 60)
  return rem > 0 ? `${m}m ${rem}s` : `${m}m`
}

function formatTimestamp(s: number): string {
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

export default function QueueAnalysisPanel({ videoId }: QueueAnalysisPanelProps) {
  const [data, setData] = useState<QueueAnalysisResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get<QueueAnalysisResponse>(`/api/v1/videos/${videoId}/queue-analysis`)
      setData(res.data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load queue analysis data')
    } finally {
      setLoading(false)
    }
  }, [videoId])

  useEffect(() => { fetchData() }, [fetchData])

  if (loading) return <Spinner />
  if (error) return <ErrorMessage message={error} onRetry={fetchData} />
  if (!data) return <EmptyState />

  const stats = [
    { label: 'Avg Wait', value: formatSeconds(data.avg_wait_time_seconds), color: 'text-indigo-600 dark:text-indigo-400' },
    { label: 'Max Wait', value: formatSeconds(data.max_wait_time_seconds), color: 'text-orange-600 dark:text-orange-400' },
    { label: 'Abandonments', value: data.abandonment_count.toString(), color: 'text-red-600 dark:text-red-400' },
    { label: 'Abandon Rate', value: `${(data.abandonment_rate * 100).toFixed(1)}%`, color: 'text-red-600 dark:text-red-400' },
  ]

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 space-y-4">
      <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-200">Queue Analysis</h3>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {stats.map(({ label, value, color }) => (
          <div key={label} className="rounded-lg border border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-700/50 p-3 text-center">
            <p className={`text-xl font-bold ${color}`}>{value}</p>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{label}</p>
          </div>
        ))}
      </div>
      {data.high_wait_periods.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-red-600 dark:text-red-400 mb-2 uppercase tracking-wide">High Wait Periods</h4>
          <div className="space-y-1">
            {data.high_wait_periods.map((p, i) => (
              <div key={i} className="flex items-center justify-between rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 px-3 py-2 text-xs">
                <span className="text-red-700 dark:text-red-300 font-medium">{formatTimestamp(p.period_start)} – {formatTimestamp(p.period_end)}</span>
                <span className="text-red-600 dark:text-red-400">Avg wait: {formatSeconds(p.avg_wait_seconds)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function Spinner() {
  return <div className="flex items-center justify-center h-40 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"><div className="w-8 h-8 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin" /></div>
}
function ErrorMessage({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="flex flex-col items-center justify-center h-40 rounded-xl border border-red-200 dark:border-red-800 bg-white dark:bg-gray-800 gap-2"><p className="text-sm text-red-500">{message}</p><button onClick={onRetry} className="text-xs px-3 py-1 rounded bg-indigo-500 text-white hover:bg-indigo-600">Retry</button></div>
}
function EmptyState() {
  return <div className="flex items-center justify-center h-40 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"><p className="text-sm text-gray-400">No queue analysis data available.</p></div>
}
