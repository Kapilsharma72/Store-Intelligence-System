import { useState, useEffect, useCallback } from 'react'
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js'
import { Bar } from 'react-chartjs-2'
import api from '../api/axios'

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend)

interface PeakInterval {
  start_seconds: number
  end_seconds: number
  unique_visitors: number
  purchases: number
  avg_queue_depth: number
  is_peak: boolean
}

interface PeakHoursResponse {
  intervals: PeakInterval[]
}

interface PeakHoursChartProps {
  videoId: string
  onSeek?: (seconds: number) => void
}

function formatTimestamp(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function PeakHoursChart({ videoId, onSeek }: PeakHoursChartProps) {
  const [data, setData] = useState<PeakHoursResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get<PeakHoursResponse>(`/api/v1/videos/${videoId}/peak-hours`)
      setData(res.data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load peak hours data')
    } finally {
      setLoading(false)
    }
  }, [videoId])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  if (loading) return <Spinner />
  if (error) return <ErrorMessage message={error} onRetry={fetchData} />
  if (!data || data.intervals.length === 0) return <EmptyState />

  const labels = data.intervals.map(
    (iv) => `${formatTimestamp(iv.start_seconds)}–${formatTimestamp(iv.end_seconds)}`
  )

  const chartData = {
    labels,
    datasets: [
      {
        label: 'Unique Visitors',
        data: data.intervals.map((iv) => iv.unique_visitors),
        backgroundColor: data.intervals.map((iv) =>
          iv.is_peak ? 'rgba(249,115,22,0.85)' : 'rgba(99,102,241,0.7)'
        ),
        borderColor: data.intervals.map((iv) =>
          iv.is_peak ? '#ea580c' : '#4f46e5'
        ),
        borderWidth: 1,
        borderRadius: 4,
      },
    ],
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: false,
      },
      tooltip: {
        backgroundColor: 'rgba(17,24,39,0.95)',
        titleColor: '#f9fafb',
        bodyColor: '#e5e7eb',
        borderColor: 'rgba(249,115,22,0.4)',
        borderWidth: 1,
        padding: 10,
        callbacks: {
          title: (items: { dataIndex: number }[]) => {
            const idx = items[0]?.dataIndex ?? 0
            const iv = data.intervals[idx]
            return `${formatTimestamp(iv.start_seconds)} – ${formatTimestamp(iv.end_seconds)}${iv.is_peak ? ' 🔥 Peak' : ''}`
          },
          label: (item: { parsed: { y: number | null } }) => ` Unique Visitors: ${item.parsed.y ?? 0}`,
          afterLabel: (item: { dataIndex: number }) => {
            const iv = data.intervals[item.dataIndex]
            return [
              ` Purchases: ${iv.purchases}`,
              ` Avg Queue Depth: ${iv.avg_queue_depth.toFixed(1)}`,
            ]
          },
        },
      },
    },
    scales: {
      x: {
        ticks: {
          color: 'currentColor',
          maxRotation: 45,
          minRotation: 30,
          font: { size: 10 },
        },
        grid: { color: 'rgba(128,128,128,0.2)' },
      },
      y: {
        ticks: { color: 'currentColor' },
        grid: { color: 'rgba(128,128,128,0.2)' },
        title: {
          display: true,
          text: 'Unique Visitors',
          color: 'currentColor',
          font: { size: 11 },
        },
      },
    },
    onClick: (_event: unknown, elements: { index: number }[]) => {
      if (elements.length > 0 && onSeek) {
        const idx = elements[0].index
        const ts = data.intervals[idx]?.start_seconds
        if (ts !== undefined) onSeek(ts)
      }
    },
  }

  const peakCount = data.intervals.filter((iv) => iv.is_peak).length

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-200">
          Peak Hours (15-min intervals)
        </h3>
        <div className="flex items-center gap-3 text-xs text-gray-500 dark:text-gray-400">
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-3 rounded-sm bg-indigo-500" /> Normal
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block w-3 h-3 rounded-sm bg-orange-500" /> Peak ({peakCount})
          </span>
        </div>
      </div>
      <div className="h-64">
        <Bar data={chartData} options={options} />
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
      <p className="text-sm text-gray-400">No peak hours data available.</p>
    </div>
  )
}
