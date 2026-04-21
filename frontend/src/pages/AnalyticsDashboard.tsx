import { useState, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import CustomerJourneyChart from '../components/CustomerJourneyChart'
import TimeSeriesChart from '../components/TimeSeriesChart'
import StaffAnalysisChart from '../components/StaffAnalysisChart'
import PeakHoursChart from '../components/PeakHoursChart'
import ZoneRankingTable from '../components/ZoneRankingTable'
import QueueAnalysisPanel from '../components/QueueAnalysisPanel'
import DwellDistributionChart from '../components/DwellDistributionChart'

interface FilterState {
  activeVisitorId?: string
  activeZoneId?: string
  seekTime?: number
  startTime?: number
  endTime?: number
}

const EMPTY_FILTER: FilterState = {}

function hasActiveFilters(f: FilterState): boolean {
  return f.activeVisitorId !== undefined || f.activeZoneId !== undefined ||
    f.seekTime !== undefined || f.startTime !== undefined || f.endTime !== undefined
}

interface AnalyticsDashboardProps {
  videoId?: string
}

export default function AnalyticsDashboard({ videoId: propVideoId }: AnalyticsDashboardProps) {
  const { videoId: paramVideoId } = useParams<{ videoId: string }>()
  const videoId = propVideoId ?? paramVideoId ?? ''
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTER)

  const handleVisitorSelect = useCallback((visitorId: string, startTime: number, endTime: number) => {
    setFilters((prev) => ({ ...prev, activeVisitorId: visitorId, startTime, endTime }))
  }, [])

  const handleZoneSelect = useCallback((zoneId: string) => {
    setFilters((prev) => ({ ...prev, activeZoneId: zoneId }))
  }, [])

  const handleSeek = useCallback((seconds: number) => {
    setFilters((prev) => ({ ...prev, seekTime: seconds }))
  }, [])

  const resetFilters = useCallback(() => setFilters(EMPTY_FILTER), [])

  if (!videoId) return (
    <div className="flex items-center justify-center h-64 text-gray-500 dark:text-gray-400">No video selected.</div>
  )

  const isFiltered = hasActiveFilters(filters)

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-900 dark:text-gray-100">Analytics Dashboard</h1>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 font-mono">{videoId}</p>
        </div>
        {isFiltered && (
          <button onClick={resetFilters}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium bg-indigo-100 text-indigo-700 hover:bg-indigo-200 dark:bg-indigo-900/40 dark:text-indigo-300 transition-colors">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
            Reset Filters
          </button>
        )}
      </div>

      {isFiltered && (
        <div className="flex flex-wrap gap-2">
          {filters.activeVisitorId && <FilterBadge label="Visitor" value={filters.activeVisitorId} onRemove={() => setFilters((f) => ({ ...f, activeVisitorId: undefined, startTime: undefined, endTime: undefined }))} />}
          {filters.activeZoneId && <FilterBadge label="Zone" value={filters.activeZoneId} onRemove={() => setFilters((f) => ({ ...f, activeZoneId: undefined }))} />}
          {filters.seekTime !== undefined && <FilterBadge label="Seek" value={`${filters.seekTime}s`} onRemove={() => setFilters((f) => ({ ...f, seekTime: undefined }))} />}
          {(filters.startTime !== undefined || filters.endTime !== undefined) && <FilterBadge label="Time range" value={`${filters.startTime ?? 0}s – ${filters.endTime ?? '?'}s`} onRemove={() => setFilters((f) => ({ ...f, startTime: undefined, endTime: undefined }))} />}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        <div className="col-span-1 md:col-span-2 xl:col-span-3">
          <CustomerJourneyChart videoId={videoId} onVisitorSelect={handleVisitorSelect} filterContext={{ activeVisitorId: filters.activeVisitorId }} />
        </div>
        <div className="col-span-1 md:col-span-2">
          <TimeSeriesChart videoId={videoId} onSeek={handleSeek} filterContext={{ startTime: filters.startTime, endTime: filters.endTime }} />
        </div>
        <div className="col-span-1">
          <StaffAnalysisChart videoId={videoId} />
        </div>
        <div className="col-span-1 md:col-span-2">
          <PeakHoursChart videoId={videoId} onSeek={handleSeek} />
        </div>
        <div className="col-span-1">
          <ZoneRankingTable videoId={videoId} onZoneSelect={handleZoneSelect} filterContext={{ activeZoneId: filters.activeZoneId }} />
        </div>
        <div className="col-span-1 md:col-span-2">
          <QueueAnalysisPanel videoId={videoId} />
        </div>
        <div className="col-span-1">
          <DwellDistributionChart videoId={videoId} />
        </div>
      </div>
    </div>
  )
}

function FilterBadge({ label, value, onRemove }: { label: string; value: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs bg-indigo-50 text-indigo-700 border border-indigo-200 dark:bg-indigo-900/30 dark:text-indigo-300 dark:border-indigo-700">
      <span className="font-medium">{label}:</span>
      <span className="font-mono truncate max-w-[120px]">{value}</span>
      <button onClick={onRemove} className="ml-0.5 hover:text-indigo-900 dark:hover:text-indigo-100">
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </span>
  )
}
