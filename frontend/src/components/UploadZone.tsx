import { useRef, useState, useCallback, DragEvent, ChangeEvent } from 'react'
import api from '../api/axios'

// ── Types ──────────────────────────────────────────────────────────────────────

interface UploadQuota {
  used: number
  limit: number
}

interface UploadZoneProps {
  uploadQuota?: UploadQuota
  onUploadComplete?: () => void
}

type FileStatus = 'pending' | 'uploading' | 'completed' | 'failed'

interface FileEntry {
  id: string
  file: File
  status: FileStatus
  bytesUploaded: number
  error?: string
}

// ── Constants ──────────────────────────────────────────────────────────────────

const ACCEPTED_EXTENSIONS = ['.mp4', '.avi', '.mov']
const ACCEPTED_MIME_TYPES = ['video/mp4', 'video/x-msvideo', 'video/quicktime']
const MAX_CONCURRENT = 5

// ── Helpers ────────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`
}

function isValidFile(file: File): boolean {
  const ext = '.' + file.name.split('.').pop()?.toLowerCase()
  return ACCEPTED_EXTENSIONS.includes(ext) && ACCEPTED_MIME_TYPES.includes(file.type)
}

function uid(): string {
  return Math.random().toString(36).slice(2)
}

// ── Component ──────────────────────────────────────────────────────────────────

export default function UploadZone({ uploadQuota, onUploadComplete }: UploadZoneProps) {
  const [files, setFiles] = useState<FileEntry[]>([])
  const [isDragging, setIsDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const showQuotaWarning =
    uploadQuota != null &&
    uploadQuota.limit === 10 &&
    uploadQuota.used >= 8

  // ── File selection ───────────────────────────────────────────────────────────

  const addFiles = useCallback((incoming: FileList | File[]) => {
    const valid: FileEntry[] = []
    Array.from(incoming).forEach((file) => {
      if (isValidFile(file)) {
        valid.push({ id: uid(), file, status: 'pending', bytesUploaded: 0 })
      }
    })
    if (valid.length) {
      setFiles((prev) => [...prev, ...valid])
    }
  }, [])

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(false)
  }

  const handleDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(false)
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files)
  }

  const handleInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) {
      addFiles(e.target.files)
      e.target.value = ''
    }
  }

  const removeFile = (id: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== id))
  }

  // ── Upload logic ─────────────────────────────────────────────────────────────

  const uploadFile = async (entry: FileEntry): Promise<void> => {
    setFiles((prev) =>
      prev.map((f) => (f.id === entry.id ? { ...f, status: 'uploading' } : f))
    )

    const formData = new FormData()
    formData.append('file', entry.file)

    try {
      await api.post('/api/v1/videos/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (event) => {
          const loaded = event.loaded ?? 0
          setFiles((prev) =>
            prev.map((f) =>
              f.id === entry.id ? { ...f, bytesUploaded: loaded } : f
            )
          )
        },
      })
      setFiles((prev) =>
        prev.map((f) =>
          f.id === entry.id
            ? { ...f, status: 'completed', bytesUploaded: entry.file.size }
            : f
        )
      )
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Upload failed'
      setFiles((prev) =>
        prev.map((f) =>
          f.id === entry.id ? { ...f, status: 'failed', error: message } : f
        )
      )
    }
  }

  const handleUpload = async () => {
    const pending = files.filter((f) => f.status === 'pending')
    if (!pending.length) return

    setUploading(true)

    // Upload in batches of MAX_CONCURRENT
    for (let i = 0; i < pending.length; i += MAX_CONCURRENT) {
      const batch = pending.slice(i, i + MAX_CONCURRENT)
      await Promise.allSettled(batch.map(uploadFile))
    }

    setUploading(false)
    onUploadComplete?.()
  }

  // ── Derived summary ──────────────────────────────────────────────────────────

  const total = files.length
  const completed = files.filter((f) => f.status === 'completed').length
  const failed = files.filter((f) => f.status === 'failed').length
  const hasPending = files.some((f) => f.status === 'pending')

  return (
    <div className="space-y-4">
      {/* Quota warning */}
      {showQuotaWarning && (
        <div className="flex items-center gap-2 rounded-lg border border-yellow-400 bg-yellow-50 dark:bg-yellow-900/30 dark:border-yellow-600 px-4 py-3 text-sm text-yellow-800 dark:text-yellow-300">
          <WarningIcon />
          <span>Warning: 8/10 uploads used this hour</span>
        </div>
      )}

      {/* Drop zone */}
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload zone — drag and drop or click to select files"
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => e.key === 'Enter' && inputRef.current?.click()}
        className={`
          flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed
          cursor-pointer select-none transition-colors px-6 py-10
          ${isDragging
            ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/20'
            : 'border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-800 hover:border-blue-400 dark:hover:border-blue-500'
          }
        `}
      >
        <UploadIcon />
        <p className="text-sm font-medium text-gray-700 dark:text-gray-200">
          Drag &amp; drop videos here, or click to browse
        </p>
        <p className="text-xs text-gray-500 dark:text-gray-400">
          Accepted formats: MP4, AVI, MOV
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".mp4,.avi,.mov,video/mp4,video/x-msvideo,video/quicktime"
          className="hidden"
          onChange={handleInputChange}
        />
      </div>

      {/* File list */}
      {files.length > 0 && (
        <ul className="space-y-2">
          {files.map((entry) => (
            <FileRow
              key={entry.id}
              entry={entry}
              onRemove={() => removeFile(entry.id)}
            />
          ))}
        </ul>
      )}

      {/* Summary */}
      {total > 0 && (
        <p className="text-sm text-gray-600 dark:text-gray-400">
          {completed} of {total} file{total !== 1 ? 's' : ''} completed
          {failed > 0 && (
            <span className="ml-2 text-red-600 dark:text-red-400">
              · {failed} failed
            </span>
          )}
        </p>
      )}

      {/* Upload button */}
      {hasPending && (
        <button
          onClick={handleUpload}
          disabled={uploading}
          className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {uploading ? 'Uploading…' : `Upload ${files.filter((f) => f.status === 'pending').length} file${files.filter((f) => f.status === 'pending').length !== 1 ? 's' : ''}`}
        </button>
      )}
    </div>
  )
}

// ── FileRow sub-component ──────────────────────────────────────────────────────

function FileRow({ entry, onRemove }: { entry: FileEntry; onRemove: () => void }) {
  const { file, status, bytesUploaded } = entry
  const percent =
    file.size > 0 ? Math.min(100, Math.round((bytesUploaded / file.size) * 100)) : 0

  const statusColor: Record<FileStatus, string> = {
    pending: 'text-gray-500 dark:text-gray-400',
    uploading: 'text-blue-600 dark:text-blue-400',
    completed: 'text-green-600 dark:text-green-400',
    failed: 'text-red-600 dark:text-red-400',
  }

  const statusLabel: Record<FileStatus, string> = {
    pending: 'Pending',
    uploading: `${formatBytes(bytesUploaded)} / ${formatBytes(file.size)} · ${percent}%`,
    completed: 'Completed',
    failed: entry.error ?? 'Failed',
  }

  return (
    <li className="rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-4 py-3 space-y-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-gray-900 dark:text-gray-100">
            {file.name}
          </p>
          <p className={`text-xs mt-0.5 ${statusColor[status]}`}>
            {formatBytes(file.size)} · {statusLabel[status]}
          </p>
        </div>
        {status !== 'uploading' && (
          <button
            onClick={onRemove}
            aria-label={`Remove ${file.name}`}
            className="shrink-0 rounded p-1 text-gray-400 hover:text-red-500 dark:hover:text-red-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
          >
            <XIcon />
          </button>
        )}
      </div>

      {/* Progress bar — shown while uploading */}
      {status === 'uploading' && (
        <div className="h-1.5 w-full rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
          <div
            className="h-full rounded-full bg-blue-500 transition-all duration-200"
            style={{ width: `${percent}%` }}
          />
        </div>
      )}

      {/* Completed bar */}
      {status === 'completed' && (
        <div className="h-1.5 w-full rounded-full bg-green-200 dark:bg-green-900 overflow-hidden">
          <div className="h-full w-full rounded-full bg-green-500" />
        </div>
      )}

      {/* Failed bar */}
      {status === 'failed' && (
        <div className="h-1.5 w-full rounded-full bg-red-200 dark:bg-red-900 overflow-hidden">
          <div className="h-full w-full rounded-full bg-red-500" />
        </div>
      )}
    </li>
  )
}

// ── Icons ──────────────────────────────────────────────────────────────────────

function UploadIcon() {
  return (
    <svg className="h-10 w-10 text-gray-400 dark:text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
        d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
    </svg>
  )
}

function XIcon() {
  return (
    <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
    </svg>
  )
}

function WarningIcon() {
  return (
    <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
    </svg>
  )
}
