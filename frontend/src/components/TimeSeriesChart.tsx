import { useState, useEffect, useCallback, useRef } from 'react'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  TimeScale,
} from 'chart.js'
import { Line } from 'react-chartjs-2'
import zoomPlugin from 'chartjs-plugin-zoom'
import api from '../api/axios'

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  TimeScale,
  zoomPlugin
)

interface TimeSeriesPoint {
  timestamp_seconds: number
  unique_visitors_cumulative: number
  conversion_rate: number
  queue_depth: number
  avg_dwell_seconds: number
}

interface TimeSeriesResponse {
  intervals: TimeSeriesPoint[]
}

interface TimeSeriesChartProps {
  videoId: string
  onSeek?: (seconds: number) => void
  filterContext?: { startTime?: number; endTime?: number }
}

function formatTimestamp(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function TimeSeriesChart({ videoId, onSeek, filterContext }: TimeSeriesChartProps) {
  const [data, setData] = useState<TimeSeriesResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const chartRef = useRef<ChartJS<'line'>>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params: Record<string, number> = {}
      if (filterContext?.startTime !== undefined) params.start_time = filterContext.startTime
      if (filterContext?.endTime !== undefined) params.end_time = filterContext.endTime
      const res = await api.get<TimeSeriesResponse>(`/api/v1/videos/${videoId}/timeseries`, { params })
      setData(res.data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load time-series data')
    } finally {
      setLoading(false)
    }
  }, [videoId, filterContext?.startTime, filterContext?.endTime])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  if (loading) return <Spinner />
  if (error) return <ErrorMessage message={error} onRetry={fetchData} />
  if (!data || data.intervals.length === 0) return <EmptyState />

  const labels = data.intervals.map((p) => formatTimestamp(p.timestamp_seconds))

  const chartData = {
    labels,
    datasets: [
      {
        label: 'Unique Visitors (cumulative)',
        data: data.intervals.map((p) => p.unique_visitors_cumulative),
        borderColor: '#6366f1',
        backgroundColor: 'rgba(99,102,241,0.1)',
        tension: 0.3,
        pointRadius: 4,
        pointHoverRadius: 7,
      },
      {
        label: 'Conversion Rate (%)',
        data: data.intervals.map((p) => p.conversion_rate),
        borderColor: '#10b981',
        backgroundColor: 'rgba(16,185,129,0.1)',
        tension: 0.3,
        pointRadius: 4,
        pointHoverRadius: 7,
      },
      {
        label: 'Queue Depth',
        data: data.intervals.map((p) => p.queue_depth),
        borderColor: '#f59e0b',
        backgroundColor: 'rgba(245,158,11,0.1)',
        tension: 0.3,
        pointRadius: 4,
        pointHoverRadius: 7,
      },
      {
        label: 'Avg Dwell (s)',
        data: data.intervals.map((p) => p.avg_dwell_seconds),
        borderColor: '#ef4444',
        backgroundColor: 'rgba(239,68,68,0.1)',
        tension: 0.3,
        pointRadius: 4,
        pointHoverRadius: 7,
      },
    ],
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
      mode: 'index' as const,
      intersect: false,
    },
    plugins: {
      legend: {
        position: 'top' as const,
        labels: {
          color: 'currentColor',
          boxWidth: 12,
        },
      },
      tooltip: {
        backgroundColor: 'rgba(17,24,39,0.95)',
        titleColor: '#f9fafb',
        bodyColor: '#e5e7eb',
        borderColor: 'rgba(99,102,241,0.4)',
        borderWidth: 1,
        padding: 10,
        callbacks: {
          title: (items: { dataIndex: number }[]) => {
            const idx = items[0]?.dataIndex ?? 0
            const ts = data.intervals[idx]?.timestamp_seconds ?? 0
            return `Time: ${formatTimestamp(ts)} (${ts}s)`
          },
          label: (item: { dataset: { label?: string }; parsed: { y: number | null } }) => {
            const label = item.dataset.label ?? ''
            const val = item.parsed.y ?? 0
            return ` ${label}: ${val.toFixed(2)}`
          },
        },
      },
      zoom: {
        zoom: {
          wheel: { enabled: true },
          pinch: { enabled: true },
          mode: 'x' as const,
          onZoomComplete: () => {
            // Re-fetch with tighter time range when zoomed
            fetchData()
          },
        },
        pan: {
          enabled: true,
          mode: 'x' as const,
        },
      },
    },
    scales: {
      x: {
        ticks: { color: 'currentColor', maxTicksLimit: 10 },
        grid: { color: 'rgba(128,128,128,0.2)' },
      },
      y: {
        ticks: { color: 'currentColor' },
        grid: { color: 'rgba(128,128,128,0.2)' },
      },
    },
    onClick: (_event: unknown, elements: { index: number }[]) => {
      if (elements.length > 0 && onSeek) {
        const idx = elements[0].index
        const ts = data.intervals[idx]?.timestamp_seconds
        if (ts !== undefined) onSeek(ts)
      }
    },
  }

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-200">
          Time-Series Metrics
        </h3>
        <button
          onClick={() => chartRef.current?.resetZoom()}
          className="text-xs px-2 py-1 rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
        >
          Reset Zoom
        </button>
      </div>
      <div className="h-64">
        <Line ref={chartRef} data={chartData} options={options} />
      </div>
    </div>
  )
}

function Spinner() {
  return (
    <div className="flex items-center justify-center h-64 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
      <div className="w-8 h-8 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin" />
    </div>
  )
}

function ErrorMessage({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center h-64 rounded-xl border border-red-200 dark:border-red-800 bg-white dark:bg-gray-800 gap-2">
      <p className="text-sm text-red-500">{message}</p>
      <button
        onClick={onRetry}
        className="text-xs px-3 py-1 rounded bg-indigo-500 text-white hover:bg-indigo-600"
      >
        Retry
      </button>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="flex items-center justify-center h-64 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
      <p className="text-sm text-gray-400">No time-series data available.</p>
    </div>
  )
}
