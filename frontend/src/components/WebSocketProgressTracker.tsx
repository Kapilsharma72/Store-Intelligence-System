import { useEffect, useRef, useState, useCallback } from 'react'

// ── Types ──────────────────────────────────────────────────────────────────────

type ProcessingStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled'

interface ProgressMessage {
  current_frame: number
  total_frames: number
  percentage_complete: number
  estimated_time_remaining_seconds: number | null
  status?: ProcessingStatus
}

type ConnectionState =
  | 'connecting'
  | 'connected'
  | 'reconnecting'
  | 'failed'
  | 'closed'

interface WebSocketProgressTrackerProps {
  videoId: string
  onComplete?: () => void
}

// ── Constants ──────────────────────────────────────────────────────────────────

const MAX_RECONNECT_ATTEMPTS = 5
const BACKOFF_DELAYS = [1000, 2000, 4000, 8000, 16000]

// ── Status badge ───────────────────────────────────────────────────────────────

const STATUS_STYLES: Partial<Record<ProcessingStatus, string>> = {
  completed: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
  failed:    'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
  cancelled: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900 dark:text-yellow-300',
}

function StatusBadge({ status }: { status: ProcessingStatus }) {
  const style = STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300'
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium capitalize ${style}`}>
      {status}
    </span>
  )
}

// ── Component ──────────────────────────────────────────────────────────────────

export default function WebSocketProgressTracker({
  videoId,
  onComplete,
}: WebSocketProgressTrackerProps) {
  const [progress, setProgress] = useState<ProgressMessage | null>(null)
  const [connState, setConnState] = useState<ConnectionState>('connecting')
  const [reconnectAttempt, setReconnectAttempt] = useState(0)

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const attemptRef = useRef(0)
  const onCompleteRef = useRef(onComplete)
  onCompleteRef.current = onComplete
  const intentionalCloseRef = useRef(false)

  const cleanup = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current)
      reconnectTimerRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.onopen = null
      wsRef.current.onmessage = null
      wsRef.current.onerror = null
      wsRef.current.onclose = null
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  const connect = useCallback(() => {
    cleanup()
    intentionalCloseRef.current = false

    const token = localStorage.getItem('auth_token') ?? ''
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${protocol}://${window.location.host}/ws/videos/${videoId}/progress?token=${encodeURIComponent(token)}`

    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      attemptRef.current = 0
      setReconnectAttempt(0)
      setConnState('connected')
    }

    ws.onmessage = (event: MessageEvent) => {
      try {
        const msg: ProgressMessage = JSON.parse(event.data as string)
        setProgress(msg)

        if (msg.status === 'completed' || msg.status === 'failed') {
          intentionalCloseRef.current = true
          setConnState('closed')
          cleanup()
          onCompleteRef.current?.()
        }
      } catch {
        // ignore malformed messages
      }
    }

    ws.onerror = () => {
      // onerror is always followed by onclose; handle reconnect there
    }

    ws.onclose = () => {
      wsRef.current = null
      if (intentionalCloseRef.current) return

      const nextAttempt = attemptRef.current + 1
      if (nextAttempt > MAX_RECONNECT_ATTEMPTS) {
        setConnState('failed')
        return
      }

      attemptRef.current = nextAttempt
      setReconnectAttempt(nextAttempt)
      setConnState('reconnecting')

      const delay = BACKOFF_DELAYS[nextAttempt - 1] ?? 16000
      reconnectTimerRef.current = setTimeout(() => {
        connect()
      }, delay)
    }
  }, [videoId, cleanup]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!videoId) return
    connect()
    return cleanup
  }, [videoId, connect, cleanup])

  if (!videoId) return null

  const pct = progress?.percentage_complete ?? 0
  const isTerminal = progress?.status === 'completed' || progress?.status === 'failed'

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-900">
      {connState === 'reconnecting' && (
        <p className="mb-3 text-sm text-yellow-600 dark:text-yellow-400">
          Reconnecting (attempt {reconnectAttempt}/{MAX_RECONNECT_ATTEMPTS})…
        </p>
      )}
      {connState === 'failed' && (
        <p className="mb-3 text-sm text-red-600 dark:text-red-400">
          Connection failed after {MAX_RECONNECT_ATTEMPTS} attempts.
        </p>
      )}

      <div className="mb-2 h-3 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
        <div
          className={`h-full rounded-full transition-all duration-300 ${
            progress?.status === 'failed'
              ? 'bg-red-500'
              : progress?.status === 'completed'
              ? 'bg-green-500'
              : 'bg-blue-500'
          }`}
          style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
        />
      </div>

      <p className="text-sm text-gray-700 dark:text-gray-300">
        {progress
          ? `Frame ${progress.current_frame} of ${progress.total_frames} (${Math.round(pct)}%)`
          : connState === 'connecting'
          ? 'Connecting…'
          : '—'}
      </p>

      {progress?.estimated_time_remaining_seconds != null && !isTerminal && (
        <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
          Estimated time remaining: {Math.round(progress.estimated_time_remaining_seconds)}s
        </p>
      )}

      {progress?.status && isTerminal && (
        <div className="mt-2">
          <StatusBadge status={progress.status} />
        </div>
      )}
    </div>
  )
}
