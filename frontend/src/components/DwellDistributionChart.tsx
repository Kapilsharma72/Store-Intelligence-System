import { useState, useEffect, useCallback, useRef } from 'react'
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend } from 'chart.js'
import { Bar } from 'react-chartjs-2'
import zoomPlugin from 'chartjs-plugin-zoom'
import api from '../api/axios'

ChartJS.register(CategoryScale, LinearScale, BarElement, Title, Tooltip, Legend, zoomPlugin)

interface DwellBucket {
  bucket_start: number
  bucket_end: number
  count: number
}

interface DwellDistributionResponse {
  buckets: DwellBucket[]
  median_dwell: number
  mean_dwell: number
  p95_dwell: number
}

interface DwellDistributionChartProps {
  videoId: string
}

function formatSeconds(s: number): string {
  if (s < 60) return `${s.toFixed(0)}s`
  const m = Math.floor(s / 60)
  const rem = Math.round(s % 60)
  return rem > 0 ? `${m}m ${rem}s` : `${m}m`
}

export default function DwellDistributionChart({ videoId }: DwellDistributionChartProps) {
  const [data, setData] = useState<DwellDistributionResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const chartRef = useRef<ChartJS<'bar'>>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get<DwellDistributionResponse>(`/api/v1/videos/${videoId}/dwell-distribution`)
      setData(res.data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load dwell distribution data')
    } finally {
      setLoading(false)
    }
  }, [videoId])

  useEffect(() => { fetchData() }, [fetchData])

  if (loading) return <Spinner />
  if (error) return <ErrorMessage message={error} onRetry={fetchData} />
  if (!data || data.buckets.length === 0) return <EmptyState />

  const total = data.buckets.reduce((sum, b) => sum + b.count, 0)
  const labels = data.buckets.map((b) => `${b.bucket_start}–${b.bucket_end}s`)

  const chartData = {
    labels,
    datasets: [{
      label: 'Visitors',
      data: data.buckets.map((b) => b.count),
      backgroundColor: 'rgba(99,102,241,0.75)',
      borderColor: '#4f46e5',
      borderWidth: 1,
      borderRadius: 4,
    }],
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: 'rgba(17,24,39,0.95)',
        titleColor: '#f9fafb',
        bodyColor: '#e5e7eb',
        borderColor: 'rgba(99,102,241,0.4)',
        borderWidth: 1,
        padding: 10,
        callbacks: {
          title: (items: { dataIndex: number }[]) => {
            const b = data.buckets[items[0]?.dataIndex ?? 0]
            return `${b.bucket_start}s – ${b.bucket_end}s`
          },
          label: (item: { parsed: { y: number | null } }) => ` Visitors: ${item.parsed.y ?? 0}`,
          afterLabel: (item: { dataIndex: number }) => {
            const b = data.buckets[item.dataIndex]
            const pct = total > 0 ? ((b.count / total) * 100).toFixed(1) : '0.0'
            return ` % of total: ${pct}%`
          },
        },
      },
      zoom: {
        zoom: {
          wheel: { enabled: true },
          pinch: { enabled: true },
          mode: 'x' as const,
        },
        pan: {
          enabled: true,
          mode: 'x' as const,
        },
      },
    },
    scales: {
      x: { ticks: { color: 'currentColor', maxRotation: 45, minRotation: 30, font: { size: 10 } }, grid: { color: 'rgba(128,128,128,0.2)' } },
      y: { ticks: { color: 'currentColor' }, grid: { color: 'rgba(128,128,128,0.2)' } },
    },
  }

  const stats = [
    { label: 'Median', value: formatSeconds(data.median_dwell), color: 'text-indigo-600 dark:text-indigo-400' },
    { label: 'Mean', value: formatSeconds(data.mean_dwell), color: 'text-green-600 dark:text-green-400' },
    { label: 'P95', value: formatSeconds(data.p95_dwell), color: 'text-orange-600 dark:text-orange-400' },
  ]

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-200">Dwell Time Distribution</h3>
        <button
          onClick={() => chartRef.current?.resetZoom()}
          className="text-xs px-2 py-1 rounded bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600"
        >
          Reset Zoom
        </button>
      </div>
      <div className="h-56"><Bar ref={chartRef} data={chartData} options={options} /></div>
      <div className="grid grid-cols-3 gap-3">
        {stats.map(({ label, value, color }) => (
          <div key={label} className="rounded-lg border border-gray-100 dark:border-gray-700 bg-gray-50 dark:bg-gray-700/50 p-3 text-center">
            <p className={`text-lg font-bold ${color}`}>{value}</p>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{label}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

function Spinner() {
  return <div className="flex items-center justify-center h-64 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"><div className="w-8 h-8 border-4 border-indigo-500 border-t-transparent rounded-full animate-spin" /></div>
}
function ErrorMessage({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="flex flex-col items-center justify-center h-64 rounded-xl border border-red-200 dark:border-red-800 bg-white dark:bg-gray-800 gap-2"><p className="text-sm text-red-500">{message}</p><button onClick={onRetry} className="text-xs px-3 py-1 rounded bg-indigo-500 text-white hover:bg-indigo-600">Retry</button></div>
}
function EmptyState() {
  return <div className="flex items-center justify-center h-64 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"><p className="text-sm text-gray-400">No dwell distribution data available.</p></div>
}
