import { useState, useEffect, useCallback } from 'react'
import {
  Chart as ChartJS,
  ArcElement,
  Tooltip,
  Legend,
} from 'chart.js'
import { Doughnut } from 'react-chartjs-2'
import api from '../api/axios'

ChartJS.register(ArcElement, Tooltip, Legend)

interface ZoneVisit {
  zone: string
  staff_visits: number
  customer_visits: number
}

interface StaffAnalysisResponse {
  staff_count: number
  customer_count: number
  staff_to_customer_ratio: number
  staff_zone_visits: ZoneVisit[]
  customer_zone_visits: ZoneVisit[]
}

interface StaffAnalysisChartProps {
  videoId: string
}

export default function StaffAnalysisChart({ videoId }: StaffAnalysisChartProps) {
  const [data, setData] = useState<StaffAnalysisResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get<StaffAnalysisResponse>(`/api/v1/videos/${videoId}/staff-analysis`)
      setData(res.data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load staff analysis data')
    } finally {
      setLoading(false)
    }
  }, [videoId])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  if (loading) return <Spinner />
  if (error) return <ErrorMessage message={error} onRetry={fetchData} />
  if (!data) return <EmptyState />

  const total = data.staff_count + data.customer_count
  const staffPct = total > 0 ? ((data.staff_count / total) * 100).toFixed(1) : '0'
  const customerPct = total > 0 ? ((data.customer_count / total) * 100).toFixed(1) : '0'

  const chartData = {
    labels: [`Staff (${staffPct}%)`, `Customers (${customerPct}%)`],
    datasets: [
      {
        data: [data.staff_count, data.customer_count],
        backgroundColor: ['#6366f1', '#10b981'],
        borderColor: ['#4f46e5', '#059669'],
        borderWidth: 2,
        hoverOffset: 6,
      },
    ],
  }

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        position: 'bottom' as const,
        labels: { color: 'currentColor', boxWidth: 12 },
      },
      tooltip: {
        callbacks: {
          label: (item: { label: string; raw: unknown }) =>
            ` ${item.label}: ${item.raw} detections`,
        },
      },
    },
  }

  // Merge zone visits into a unified list
  const allZones = Array.from(
    new Set([
      ...data.staff_zone_visits.map((z) => z.zone),
      ...data.customer_zone_visits.map((z) => z.zone),
    ])
  )
  const staffByZone = Object.fromEntries(data.staff_zone_visits.map((z) => [z.zone, z.staff_visits]))
  const customerByZone = Object.fromEntries(
    data.customer_zone_visits.map((z) => [z.zone, z.customer_visits])
  )

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
      <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-3">
        Staff vs Customer Analysis
      </h3>

      {/* Summary stats */}
      <div className="grid grid-cols-3 gap-2 mb-4">
        <StatCard label="Staff" value={data.staff_count} color="text-indigo-500" />
        <StatCard label="Customers" value={data.customer_count} color="text-emerald-500" />
        <StatCard
          label="Ratio"
          value={`1 : ${data.staff_to_customer_ratio.toFixed(1)}`}
          color="text-amber-500"
        />
      </div>

      {/* Doughnut chart */}
      <div className="h-48 mb-4">
        <Doughnut data={chartData} options={options} />
      </div>

      {/* Zone breakdown */}
      {allZones.length > 0 && (
        <div>
          <p className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">
            Zone Breakdown
          </p>
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {allZones.map((zone) => (
              <div
                key={zone}
                className="flex items-center justify-between text-xs text-gray-600 dark:text-gray-300 px-2 py-1 rounded bg-gray-50 dark:bg-gray-700"
              >
                <span className="font-medium truncate max-w-[120px]">{zone}</span>
                <span className="text-indigo-500">{staffByZone[zone] ?? 0} staff</span>
                <span className="text-emerald-500">{customerByZone[zone] ?? 0} cust.</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function StatCard({
  label,
  value,
  color,
}: {
  label: string
  value: string | number
  color: string
}) {
  return (
    <div className="flex flex-col items-center rounded-lg bg-gray-50 dark:bg-gray-700 p-2">
      <span className={`text-lg font-bold ${color}`}>{value}</span>
      <span className="text-xs text-gray-500 dark:text-gray-400">{label}</span>
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
      <p className="text-sm text-gray-400">No staff analysis data available.</p>
    </div>
  )
}
