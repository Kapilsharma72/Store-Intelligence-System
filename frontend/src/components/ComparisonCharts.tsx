import { useEffect, useState, useRef } from 'react'
import { Chart as ChartJS, CategoryScale, LinearScale, BarElement, Tooltip, Legend } from 'chart.js'
import { Bar } from 'react-chartjs-2'
import api from '../api/axios'

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip, Legend)

interface VideoMetrics {
  video_id: string
  filename?: string
  conversion_rate: number
  avg_dwell: number
  unique_visitors: number
  conversion_rate_normalized: number
  avg_dwell_normalized: number
  unique_visitors_normalized: number
}

interface ComparisonChartsProps {
  videoIds: string[]
}

const PALETTE = ['rgba(99,102,241,0.8)', 'rgba(16,185,129,0.8)', 'rgba(245,158,11,0.8)', 'rgba(239,68,68,0.8)']

export default function ComparisonCharts({ videoIds }: ComparisonChartsProps) {
  const [data, setData] = useState<VideoMetrics[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (videoIds.length < 2) { setData([]); return }
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setLoading(true)
    setError(null)
    const [primary, ...rest] = videoIds
    const params = new URLSearchParams()
    rest.forEach((id) => params.append('comparison_video_ids', id))
    api.get(`/api/v1/videos/${primary}/comparison?${params.toString()}`, { signal: ctrl.signal })
      .then((res) => setData(res.data.videos ?? res.data ?? []))
      .catch((err) => { if (err.name !== 'CanceledError' && err.name !== 'AbortError') setError('Failed to load comparison data.') })
      .finally(() => setLoading(false))
  }, [videoIds.join(',')])

  if (videoIds.length < 2) return <div className="flex items-center justify-center h-32 text-sm text-gray-500 dark:text-gray-400">Select at least 2 videos to see comparison charts.</div>
  if (loading) return <div className="flex items-center justify-center h-32 text-sm text-gray-500 dark:text-gray-400">Loading comparison data…</div>
  if (error) return <div className="rounded-lg bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4 text-sm text-red-700 dark:text-red-300">{error}</div>
  if (!data.length) return null

  const labels = data.map((v) => v.filename ?? v.video_id)
  const barData = {
    labels,
    datasets: [
      { label: 'Conversion Rate (norm.)', data: data.map((v) => v.conversion_rate_normalized ?? 0), backgroundColor: PALETTE[0], borderRadius: 4 },
      { label: 'Avg Dwell (norm.)', data: data.map((v) => v.avg_dwell_normalized ?? 0), backgroundColor: PALETTE[1], borderRadius: 4 },
      { label: 'Unique Visitors (norm.)', data: data.map((v) => v.unique_visitors_normalized ?? 0), backgroundColor: PALETTE[2], borderRadius: 4 },
    ],
  }

  const barOptions = {
    responsive: true,
    plugins: { legend: { position: 'top' as const } },
    scales: { y: { min: 0, max: 100, title: { display: true, text: 'Normalized Score (0–100)' } } },
  }

  return (
    <div className="space-y-6">
      <div className="bg-white dark:bg-gray-900 rounded-xl shadow p-4">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">Normalized Metrics Comparison</h3>
        <Bar data={barData} options={barOptions} />
      </div>
      <div className="bg-white dark:bg-gray-900 rounded-xl shadow overflow-hidden">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 px-4 pt-4 pb-2">Summary</h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 dark:bg-gray-800 text-left">
                <th className="px-4 py-2 font-medium text-gray-600 dark:text-gray-400">Video</th>
                <th className="px-4 py-2 font-medium text-gray-600 dark:text-gray-400">Conversion Rate</th>
                <th className="px-4 py-2 font-medium text-gray-600 dark:text-gray-400">Avg Dwell (s)</th>
                <th className="px-4 py-2 font-medium text-gray-600 dark:text-gray-400">Unique Visitors</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {data.map((v, i) => (
                <tr key={v.video_id} className="hover:bg-gray-50 dark:hover:bg-gray-800/50 transition-colors">
                  <td className="px-4 py-2 font-medium text-gray-900 dark:text-gray-100 flex items-center gap-2">
                    <span className="inline-block w-3 h-3 rounded-sm shrink-0" style={{ backgroundColor: PALETTE[i % PALETTE.length].replace('0.8', '1') }} />
                    <span className="truncate max-w-[160px]">{v.filename ?? v.video_id}</span>
                  </td>
                  <td className="px-4 py-2 text-gray-700 dark:text-gray-300">{(v.conversion_rate * 100).toFixed(1)}%</td>
                  <td className="px-4 py-2 text-gray-700 dark:text-gray-300">{v.avg_dwell?.toFixed(1) ?? '—'}</td>
                  <td className="px-4 py-2 text-gray-700 dark:text-gray-300">{v.unique_visitors}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
