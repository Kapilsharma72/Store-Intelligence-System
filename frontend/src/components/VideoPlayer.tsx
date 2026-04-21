import { useRef, useState, useEffect, useCallback } from 'react';

export type EventType = 'ENTRY' | 'EXIT' | 'BILLING_QUEUE_JOIN';

export interface EventMarker {
  timestamp_seconds: number;
  event_type: EventType;
}

export interface BoundingBox {
  visitor_id: string;
  x: number;       // normalized 0-1
  y: number;       // normalized 0-1
  width: number;   // normalized 0-1
  height: number;  // normalized 0-1
  is_staff: boolean;
}

export interface LiveMetrics {
  unique_visitors: number;
  queue_depth: number;
  active_zones: string[];
}

interface VideoPlayerProps {
  src: string;
  events?: EventMarker[];
  onTimeUpdate?: (currentTime: number) => void;
  seekTo?: number;
  boundingBoxes?: BoundingBox[];
  liveMetrics?: LiveMetrics;
}

const EVENT_COLORS: Record<EventType, string> = {
  ENTRY: '#22c55e',           // green-500
  EXIT: '#ef4444',            // red-500
  BILLING_QUEUE_JOIN: '#3b82f6', // blue-500
};

const EVENT_LABEL: Record<EventType, string> = {
  ENTRY: 'Entry',
  EXIT: 'Exit',
  BILLING_QUEUE_JOIN: 'Queue Join',
};

const SPEEDS = [0.5, 1, 1.5, 2] as const;

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || isNaN(seconds)) return '0:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export default function VideoPlayer({
  src,
  events = [],
  onTimeUpdate,
  seekTo,
  boundingBoxes = [],
  liveMetrics,
}: VideoPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rafRef = useRef<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [speed, setSpeed] = useState<number>(1);
  const [tooltip, setTooltip] = useState<{ x: number; marker: EventMarker } | null>(null);
  const prevSeekTo = useRef<number | undefined>(undefined);

  // Sync playback speed
  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.playbackRate = speed;
    }
  }, [speed]);

  // Seek when seekTo prop changes
  useEffect(() => {
    if (seekTo !== undefined && seekTo !== prevSeekTo.current && videoRef.current) {
      videoRef.current.currentTime = seekTo;
      prevSeekTo.current = seekTo;
    }
  }, [seekTo]);

  // Sync canvas size to video element using ResizeObserver
  useEffect(() => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    const syncSize = () => {
      canvas.width = video.clientWidth;
      canvas.height = video.clientHeight;
    };

    syncSize();
    const ro = new ResizeObserver(syncSize);
    ro.observe(video);
    return () => ro.disconnect();
  }, []);

  // Draw bounding boxes on canvas
  const drawBoxes = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    for (const box of boundingBoxes) {
      const px = box.x * canvas.width;
      const py = box.y * canvas.height;
      const pw = box.width * canvas.width;
      const ph = box.height * canvas.height;

      ctx.strokeStyle = box.is_staff ? '#f97316' : '#06b6d4'; // orange-500 / cyan-500
      ctx.lineWidth = 2;
      ctx.strokeRect(px, py, pw, ph);

      // Label background
      ctx.font = 'bold 11px sans-serif';
      const labelText = box.visitor_id;
      const textMetrics = ctx.measureText(labelText);
      const labelW = textMetrics.width + 6;
      const labelH = 16;
      const labelY = py - labelH - 2;

      ctx.fillStyle = box.is_staff ? '#f97316' : '#06b6d4';
      ctx.fillRect(px, labelY, labelW, labelH);

      ctx.fillStyle = '#ffffff';
      ctx.fillText(labelText, px + 3, labelY + 12);
    }
  }, [boundingBoxes]);

  // Redraw on every animation frame while playing, or immediately when boxes change
  useEffect(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }

    if (playing) {
      const loop = () => {
        drawBoxes();
        rafRef.current = requestAnimationFrame(loop);
      };
      rafRef.current = requestAnimationFrame(loop);
    } else {
      drawBoxes();
    }

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
  }, [playing, drawBoxes]);

  const handlePlayPause = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      video.play();
    } else {
      video.pause();
    }
  }, []);

  const handleTimeUpdate = useCallback(() => {
    const video = videoRef.current;
    if (!video) return;
    setCurrentTime(video.currentTime);
    onTimeUpdate?.(video.currentTime);
  }, [onTimeUpdate]);

  const handleLoadedMetadata = useCallback(() => {
    if (videoRef.current) {
      setDuration(videoRef.current.duration);
      // Sync canvas size on metadata load
      if (canvasRef.current) {
        canvasRef.current.width = videoRef.current.clientWidth;
        canvasRef.current.height = videoRef.current.clientHeight;
      }
    }
  }, []);

  const handleSeekChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const t = parseFloat(e.target.value);
    if (videoRef.current) {
      videoRef.current.currentTime = t;
      setCurrentTime(t);
    }
  }, []);

  const handleSpeedChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    setSpeed(parseFloat(e.target.value));
  }, []);

  const handlePlay = useCallback(() => setPlaying(true), []);
  const handlePause = useCallback(() => setPlaying(false), []);
  const handleEnded = useCallback(() => setPlaying(false), []);

  // Compute marker position as percentage
  const markerPosition = (ts: number) => {
    if (!duration || duration === 0) return 0;
    return Math.min(100, Math.max(0, (ts / duration) * 100));
  };

  return (
    <div className="flex flex-col gap-3 w-full bg-white dark:bg-gray-900 rounded-xl shadow p-4">
      {/* Video element with bounding box overlay */}
      <div className="relative w-full bg-black rounded-lg overflow-hidden aspect-video">
        <video
          ref={videoRef}
          src={src}
          controls={false}
          className="w-full h-full object-contain"
          onTimeUpdate={handleTimeUpdate}
          onLoadedMetadata={handleLoadedMetadata}
          onPlay={handlePlay}
          onPause={handlePause}
          onEnded={handleEnded}
        />
        {/* Bounding box canvas overlay */}
        <canvas
          ref={canvasRef}
          className="absolute inset-0 pointer-events-none"
          style={{ width: '100%', height: '100%' }}
        />
      </div>

      {/* Live metrics panel */}
      {liveMetrics && (
        <div className="flex items-center gap-4 flex-wrap px-1 py-2 rounded-lg
          bg-gray-100 dark:bg-gray-800 text-sm text-gray-700 dark:text-gray-300">
          <span className="flex items-center gap-1">
            <span className="font-semibold text-indigo-600 dark:text-indigo-400">Visitors:</span>
            {liveMetrics.unique_visitors}
          </span>
          <span className="flex items-center gap-1">
            <span className="font-semibold text-orange-500 dark:text-orange-400">Queue:</span>
            {liveMetrics.queue_depth}
          </span>
          <span className="flex items-center gap-1">
            <span className="font-semibold text-cyan-600 dark:text-cyan-400">Active Zones:</span>
            {liveMetrics.active_zones.length > 0
              ? liveMetrics.active_zones.join(', ')
              : <span className="text-gray-400 dark:text-gray-500 italic">None</span>}
          </span>
        </div>
      )}

      {/* Timeline scrubber with event markers */}
      <div className="relative w-full">
        {/* Seek slider */}
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.1}
          value={currentTime}
          onChange={handleSeekChange}
          className="w-full h-2 appearance-none rounded-full cursor-pointer
            bg-gray-200 dark:bg-gray-700
            accent-indigo-500"
          aria-label="Seek"
        />

        {/* Event marker ticks */}
        {duration > 0 && events.map((marker, i) => {
          const pct = markerPosition(marker.timestamp_seconds);
          return (
            <div
              key={i}
              className="absolute top-0 -translate-x-1/2 cursor-pointer group"
              style={{ left: `${pct}%` }}
              onMouseEnter={(e) => {
                const rect = (e.currentTarget.closest('.relative') as HTMLElement)?.getBoundingClientRect();
                const x = (e.currentTarget as HTMLElement).getBoundingClientRect().left - (rect?.left ?? 0);
                setTooltip({ x, marker });
              }}
              onMouseLeave={() => setTooltip(null)}
            >
              {/* Tick mark */}
              <div
                className="w-2 h-4 rounded-sm opacity-90 hover:opacity-100 transition-opacity"
                style={{ backgroundColor: EVENT_COLORS[marker.event_type] }}
              />
            </div>
          );
        })}

        {/* Tooltip */}
        {tooltip && (
          <div
            className="absolute bottom-6 z-10 -translate-x-1/2 pointer-events-none
              bg-gray-800 dark:bg-gray-700 text-white text-xs rounded px-2 py-1 whitespace-nowrap shadow-lg"
            style={{ left: `${markerPosition(tooltip.marker.timestamp_seconds)}%` }}
          >
            <span
              className="inline-block w-2 h-2 rounded-full mr-1"
              style={{ backgroundColor: EVENT_COLORS[tooltip.marker.event_type] }}
            />
            {EVENT_LABEL[tooltip.marker.event_type]} — {formatTime(tooltip.marker.timestamp_seconds)}
          </div>
        )}
      </div>

      {/* Controls row */}
      <div className="flex items-center gap-4 flex-wrap">
        {/* Play/Pause */}
        <button
          onClick={handlePlayPause}
          className="flex items-center justify-center w-10 h-10 rounded-full
            bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800
            text-white transition-colors focus:outline-none focus:ring-2 focus:ring-indigo-400"
          aria-label={playing ? 'Pause' : 'Play'}
        >
          {playing ? <PauseIcon /> : <PlayIcon />}
        </button>

        {/* Time display */}
        <span className="text-sm font-mono text-gray-700 dark:text-gray-300 tabular-nums">
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Speed selector */}
        <label className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-400">
          Speed
          <select
            value={speed}
            onChange={handleSpeedChange}
            className="rounded border border-gray-300 dark:border-gray-600
              bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-200
              text-sm px-2 py-1 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          >
            {SPEEDS.map((s) => (
              <option key={s} value={s}>{s}x</option>
            ))}
          </select>
        </label>
      </div>

      {/* Event legend */}
      {events.length > 0 && (
        <div className="flex items-center gap-4 flex-wrap text-xs text-gray-500 dark:text-gray-400">
          {(Object.keys(EVENT_COLORS) as EventType[]).map((type) => (
            <span key={type} className="flex items-center gap-1">
              <span
                className="inline-block w-3 h-3 rounded-sm"
                style={{ backgroundColor: EVENT_COLORS[type] }}
              />
              {EVENT_LABEL[type]}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function PlayIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5 ml-0.5">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}

function PauseIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
      <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
    </svg>
  );
}
