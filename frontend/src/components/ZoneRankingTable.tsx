import { useState, useEffect, useCallback } from 'react'
import api from '../api/axios'

interface ZoneRankingEntry {
  zone_id: string
  zone_name: string
  conversion_rate: number
  avg_dwell: number
  visit_count: number
  performance_score: number
}

interface ZoneRankingResponse {
  zones: ZoneRankingEntry[]
}

type SortKey = keyof Omit<ZoneRankingEntry, 'zone_id' | 'zone_name'>
type SortDir = 'asc' | 'desc'

interface ZoneRankingTableProps {
  videoId: string
  onZoneSelect?: (zoneId: string) => void
  filterContext?: { activeZoneId?: string }
}

export default function ZoneRankingTable({ videoId, onZoneSelect, filterContext }: ZoneRankingTableProps) {
  const [data, setData] = useState<ZoneRankingResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('performance_score')
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get<ZoneRankingResponse>(`/api/v1/videos/${videoId}/zone-ranking`)
      setData(res.data)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to load zone ranking data')
    } finally {
      setLoading(false)
    }
  }, [videoId])

  useEffect(() => { fetchData() }, [fetchData])

  const handleSort = (key: SortKey) => {
    if (key === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(key); setSortDir('desc') }
  }

  if (loading) return <Spinner />
  if (error) return <ErrorMessage message={error} onRetry={fetchData} />
  if (!data || data.zones.length === 0) return <EmptyState />

  const sorted = [...data.zones].sort((a, b) => {
    const av = a[sortKey], bv = b[sortKey]
    return sortDir === 'asc' ? av - bv : bv - av
  })

  const activeZoneId = filterContext?.activeZoneId
  const columns: { key: SortKey; label: string }[] = [
    { key: 'conversion_rate', label: 'Conv. Rate' },
    { key: 'avg_dwell', label: 'Avg Dwell' },
    { key: 'visit_count', label: 'Visits' },
    { key: 'performance_score', label: 'Score' },
  ]

  return (
    <div className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 p-4">
      <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-200 mb-3">Zone Performance Ranking</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 dark:border-gray-700">
              <th className="text-left py-2 px-3 text-xs font-medium text-gray-500 dark:text-gray-400">Zone</th>
              {columns.map(({ key, label }) => (
                <th key={key} onClick={() => handleSort(key)}
                  className="text-right py-2 px-3 text-xs font-medium text-gray-500 dark:text-gray-400 cursor-pointer select-none hover:text-indigo-500 whitespace-nowrap">
                  {label}{sortKey === key && <span className="ml-1">{sortDir === 'asc' ? '↑' : '↓'}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((zone) => (
              <tr key={zone.zone_id} onClick={() => onZoneSelect?.(zone.zone_id)}
                className={`border-b border-gray-100 dark:border-gray-700/50 cursor-pointer transition-colors ${activeZoneId === zone.zone_id ? 'bg-indigo-50 dark:bg-indigo-900/30' : 'hover:bg-gray-50 dark:hover:bg-gray-700/40'}`}>
                <td className="py-2 px-3 font-medium text-gray-800 dark:text-gray-200">{zone.zone_name}</td>
                <td className="py-2 px-3 text-right text-gray-600 dark:text-gray-300">{(zone.conversion_rate * 100).toFixed(1)}%</td>
                <td className="py-2 px-3 text-right text-gray-600 dark:text-gray-300">{zone.avg_dwell.toFixed(0)}s</td>
                <td className="py-2 px-3 text-right text-gray-600 dark:text-gray-300">{zone.visit_count}</td>
                <td className="py-2 px-3 text-right">
                  <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${zone.performance_score >= 70 ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-400' : zone.performance_score >= 40 ? 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-400' : 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-400'}`}>
                    {zone.performance_score.toFixed(1)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
  return <div className="flex items-center justify-center h-40 rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800"><p className="text-sm text-gray-400">No zone ranking data available.</p></div>
}
