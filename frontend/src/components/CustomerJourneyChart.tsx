import { useState, useEffect, useCallback, useRef } from 'react'
import api from '../api/axios'

interface ZoneTransition {
  zone: string
  entry_timestamp: number
  exit_timestamp: number
  dwell_time: number
}

interface VisitorJourney {
  visitor_id: string
  transitions: ZoneTransition[]
}

interface JourneyResponse {
  visitors: VisitorJourney[]
}

interface CustomerJourneyChartProps {
  videoId: string
  onVisitorSelect?: (visitorId: string, startTime: number, endTime: number) => void
  filterContext?: { activeVisitorId?: string }
}

const VISITOR_COLORS = [
  '#6366f1', '#f59e0b', '#10b981', '#ef4444', '#3b82f6',
  '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#84cc16',
]

const NODE_WIDTH = 120
const NODE_HEIGHT = 36
const NODE_GAP = 16
const SVG_PADDING = { top: 20, right: 20, bottom: 20, left: 20 }
const PATH_AREA_WIDTH = 260

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}m ${s}s`
}

function getVisitorColor(index: number): string {
  return VISITOR_COLORS[index % VISITOR_COLORS.length]
}

function getTotalDuration(transitions: ZoneTransition[]): number {
  return transitions.reduce((sum, t) => sum + t.dwell_time, 0)
}

function getTimeRange(transitions: ZoneTransition[]): { start: number; end: number } {
  if (transitions.length === 0) return { start: 0, end: 0 }
  return {
    start: Math.min(...transitions.map((t) => t.entry_timestamp)),
    end: Math.max(...transitions.map((t) => t.exit_timestamp)),
  }
}

interface TooltipState {
  x: number
  y: number
  visitorId: string
  totalDuration: number
  zonesVisited: number
}

export default function CustomerJourneyChart({ videoId, onVisitorSelect, filterContext }: CustomerJourneyChartProps) {
  const [journeyData, setJourneyData] = useState<JourneyResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedVisitorId, setSelectedVisitorId] = useState<string | null>(null)
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)
  const svgRef = useRef<SVGSVGElement>(null)

  const activeVisitorId = filterContext?.activeVisitorId ?? selectedVisitorId

  const fetchJourney = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await api.get<JourneyResponse>(`/api/v1/videos/${videoId}/journey`)
      setJourneyData(res.data)
    } catch {
      setError('Failed to load journey data.')
    } finally {
      setLoading(false)
    }
  }, [videoId])

  useEffect(() => { fetchJourney() }, [fetchJourney])

  const handlePathClick = (visitor: VisitorJourney) => {
    setSelectedVisitorId(visitor.visitor_id)
    if (onVisitorSelect) {
      const { start, end } = getTimeRange(visitor.transitions)
      onVisitorSelect(visitor.visitor_id, start, end)
    }
  }

  const visitors = journeyData?.visitors ?? []
  const zoneSet = new Set<string>()
  visitors.forEach((v) => v.transitions.forEach((t) => zoneSet.add(t.zone)))
  const zones = Array.from(zoneSet)

  const svgHeight = SVG_PADDING.top + zones.length * (NODE_HEIGHT + NODE_GAP) - NODE_GAP + SVG_PADDING.bottom
  const svgWidth = SVG_PADDING.left + PATH_AREA_WIDTH + NODE_WIDTH + SVG_PADDING.right

  const zoneY = (zone: string) => {
    const idx = zones.indexOf(zone)
    return SVG_PADDING.top + idx * (NODE_HEIGHT + NODE_GAP) + NODE_HEIGHT / 2
  }

  const nodeX = SVG_PADDING.left + PATH_AREA_WIDTH

  if (loading) return (
    <div className="flex items-center justify-center h-48 rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
      <Spinner /><span className="ml-2 text-sm text-gray-500 dark:text-gray-400">Loading…</span>
    </div>
  )

  if (error) return (
    <div className="flex flex-col items-center justify-center h-48 rounded-xl bg-white dark:bg-gray-800 border border-red-200 dark:border-red-800 gap-3">
      <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
      <button onClick={fetchJourney} className="px-3 py-1.5 text-xs rounded-lg bg-red-100 text-red-700 hover:bg-red-200 dark:bg-red-900 dark:text-red-300">Retry</button>
    </div>
  )

  if (!visitors.length) return (
    <div className="flex items-center justify-center h-48 rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700">
      <p className="text-sm text-gray-500 dark:text-gray-400">No journey data available.</p>
    </div>
  )

  return (
    <div className="rounded-xl bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 p-4">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">Customer Journey Flow</h3>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{visitors.length} visitors · {zones.length} zones</p>
        </div>
        {activeVisitorId && (
          <button onClick={() => setSelectedVisitorId(null)} className="px-3 py-1.5 text-xs rounded-lg bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300">Reset Filters</button>
        )}
      </div>

      <div className="flex flex-wrap gap-2 mb-3">
        {visitors.map((v, i) => (
          <button key={v.visitor_id} onClick={() => handlePathClick(v)}
            className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-xs transition-opacity ${!activeVisitorId || activeVisitorId === v.visitor_id ? 'opacity-100' : 'opacity-30'} bg-gray-50 dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600`}>
            <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: getVisitorColor(i) }} />
            <span className="text-gray-700 dark:text-gray-300 font-mono">{v.visitor_id.length > 10 ? `${v.visitor_id.slice(0, 8)}…` : v.visitor_id}</span>
          </button>
        ))}
      </div>

      <div className="relative overflow-x-auto">
        <svg ref={svgRef} width={svgWidth} height={svgHeight} className="block" onMouseLeave={() => setTooltip(null)}>
          {zones.map((zone) => {
            const y = zoneY(zone)
            return (
              <g key={zone}>
                <rect x={nodeX} y={y - NODE_HEIGHT / 2} width={NODE_WIDTH} height={NODE_HEIGHT} rx={6}
                  className="fill-indigo-50 stroke-indigo-300 dark:fill-indigo-900 dark:stroke-indigo-600" strokeWidth={1.5} />
                <text x={nodeX + NODE_WIDTH / 2} y={y + 1} textAnchor="middle" dominantBaseline="middle"
                  className="fill-indigo-800 dark:fill-indigo-200" fontSize={11} fontWeight={500}>
                  {zone.length > 14 ? `${zone.slice(0, 12)}…` : zone}
                </text>
              </g>
            )
          })}

          {visitors.map((visitor, visitorIdx) => {
            const color = getVisitorColor(visitorIdx)
            const isActive = !activeVisitorId || activeVisitorId === visitor.visitor_id
            const opacity = isActive ? 1 : 0.12
            if (!visitor.transitions.length) return null

            const firstZone = visitor.transitions[0].zone
            const entryY = zoneY(firstZone)
            const offsetY = (visitorIdx - visitors.length / 2) * 3
            const totalDuration = getTotalDuration(visitor.transitions)
            const zonesVisited = new Set(visitor.transitions.map((t) => t.zone)).size

            const handleMouseEnter = (e: React.MouseEvent<SVGPathElement>) => {
              const rect = svgRef.current?.getBoundingClientRect()
              if (!rect) return
              setTooltip({ x: e.clientX - rect.left, y: e.clientY - rect.top, visitorId: visitor.visitor_id, totalDuration, zonesVisited })
            }

            const segments = visitor.transitions.slice(0, -1).map((t, i) => ({ from: t.zone, to: visitor.transitions[i + 1].zone }))

            return (
              <g key={visitor.visitor_id} style={{ opacity }}>
                <path
                  d={`M ${SVG_PADDING.left} ${entryY + offsetY} C ${SVG_PADDING.left + PATH_AREA_WIDTH * 0.4} ${entryY + offsetY}, ${nodeX - 20} ${entryY + offsetY}, ${nodeX} ${entryY}`}
                  fill="none" stroke={color} strokeWidth={isActive ? 2.5 : 1.5} strokeLinecap="round"
                  style={{ cursor: 'pointer' }} onMouseEnter={handleMouseEnter} onMouseLeave={() => setTooltip(null)} onClick={() => handlePathClick(visitor)} />
                {segments.map((seg, segIdx) => {
                  const fromY = zoneY(seg.from)
                  const toY = zoneY(seg.to)
                  const cpX = nodeX + NODE_WIDTH * 1.3
                  return (
                    <path key={segIdx}
                      d={`M ${nodeX + NODE_WIDTH} ${fromY + offsetY} C ${cpX} ${fromY + offsetY}, ${cpX} ${toY + offsetY}, ${nodeX} ${toY}`}
                      fill="none" stroke={color} strokeWidth={isActive ? 2.5 : 1.5} strokeLinecap="round"
                      style={{ cursor: 'pointer' }} onMouseEnter={handleMouseEnter} onMouseLeave={() => setTooltip(null)} onClick={() => handlePathClick(visitor)} />
                  )
                })}
                <circle cx={SVG_PADDING.left} cy={entryY + offsetY} r={4} fill={color} style={{ cursor: 'pointer' }} onClick={() => handlePathClick(visitor)} />
              </g>
            )
          })}
        </svg>

        {tooltip && (
          <div className="pointer-events-none absolute z-10 rounded-lg shadow-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-2 text-xs"
            style={{ left: tooltip.x + 12, top: tooltip.y - 10, maxWidth: 220 }}>
            <p className="font-semibold text-gray-900 dark:text-gray-100 font-mono mb-1 truncate">{tooltip.visitorId}</p>
            <p className="text-gray-600 dark:text-gray-400">Duration: <span className="font-medium text-gray-800 dark:text-gray-200">{formatDuration(tooltip.totalDuration)}</span></p>
            <p className="text-gray-600 dark:text-gray-400">Zones visited: <span className="font-medium text-gray-800 dark:text-gray-200">{tooltip.zonesVisited}</span></p>
            <p className="mt-1 text-gray-400 dark:text-gray-500 italic">Click to filter</p>
          </div>
        )}
      </div>
    </div>
  )
}

function Spinner() {
  return (
    <svg className="animate-spin h-5 w-5 text-indigo-500" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  )
}
