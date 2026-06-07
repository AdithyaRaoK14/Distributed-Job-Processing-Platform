import { useState, useEffect } from 'react'
import { RotateCcw, Skull, ChevronDown, ChevronRight } from 'lucide-react'
import { listDeadLetter, retryJob } from '../api/client'

export default function DeadLetterQueue({ onRetried }) {
  const [jobs, setJobs]         = useState([])
  const [total, setTotal]       = useState(0)
  const [page, setPage]         = useState(1)
  const [expanded, setExpanded] = useState(null)
  const [retrying, setRetrying] = useState(null)
  const [message, setMessage]   = useState(null)
  const PAGE_SIZE = 20

  useEffect(() => {
    let alive = true
    async function load() {
      try {
        const data = await listDeadLetter({ page, page_size: PAGE_SIZE })
        if (alive) { setJobs(data.jobs); setTotal(data.total) }
      } catch (e) { console.error(e) }
    }
    load()
    const id = setInterval(load, 3000)
    return () => { alive = false; clearInterval(id) }
  }, [page])

  async function handleRetry(jobId) {
    setRetrying(jobId)
    setMessage(null)
    try {
      await retryJob(jobId)
      setMessage({ type: 'ok', text: `Job ${jobId.slice(0, 12)}… re-enqueued` })
      onRetried?.()
      // Refresh list
      const data = await listDeadLetter({ page, page_size: PAGE_SIZE })
      setJobs(data.jobs)
      setTotal(data.total)
    } catch (e) {
      setMessage({ type: 'err', text: e.message })
    } finally {
      setRetrying(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Skull size={18} className="text-danger" />
            Dead Letter Queue
          </h2>
          <p className="text-sm text-muted mt-0.5">
            Jobs that exhausted all retry attempts. Inspect and re-enqueue from here.
          </p>
        </div>
        <span className="text-sm text-danger font-semibold">{total} jobs</span>
      </div>

      {message && (
        <div className={`text-xs px-4 py-2 rounded border font-mono
          ${message.type === 'ok'
            ? 'border-success/30 bg-success/5 text-success'
            : 'border-danger/30 bg-danger/5 text-danger'}`}>
          {message.text}
        </div>
      )}

      {jobs.length === 0 ? (
        <div className="text-center py-20 text-muted">
          <Skull size={32} className="mx-auto mb-3 opacity-20" />
          <p className="text-sm">Dead letter queue is empty</p>
        </div>
      ) : (
        <div className="bg-card border border-border rounded-lg divide-y divide-border">
          {jobs.map(job => (
            <div key={job.id}>
              {/* Row */}
              <div
                className="flex items-center gap-4 px-4 py-3 hover:bg-surface/50 cursor-pointer"
                onClick={() => setExpanded(expanded === job.id ? null : job.id)}
              >
                <span className="text-muted">
                  {expanded === job.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3">
                    <span className="text-white text-sm font-medium">{job.type}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded border capitalize
                      ${job.priority === 'high' ? 'border-danger/30 text-danger'
                        : job.priority === 'medium' ? 'border-warning/30 text-warning'
                        : 'border-success/30 text-success'}`}>
                      {job.priority}
                    </span>
                    <span className="text-xs text-muted font-mono">{job.id.slice(0, 16)}…</span>
                  </div>
                  <p className="text-xs text-danger mt-0.5 truncate">{job.error}</p>
                </div>
                <div className="text-right text-xs text-muted shrink-0">
                  <p>{job.retry_count}/{job.max_retries} retries</p>
                  <p>{job.completed_at ? new Date(job.completed_at).toLocaleString() : '—'}</p>
                </div>
                <button
                  onClick={e => { e.stopPropagation(); handleRetry(job.id) }}
                  disabled={retrying === job.id}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs rounded border border-accent/30
                    text-accent hover:bg-accent/10 disabled:opacity-40 transition-colors shrink-0"
                >
                  <RotateCcw size={12} className={retrying === job.id ? 'animate-spin' : ''} />
                  Retry
                </button>
              </div>

              {/* Expanded detail */}
              {expanded === job.id && (
                <div className="px-8 pb-4 bg-surface/30">
                  <div className="grid grid-cols-2 gap-4 text-xs font-mono pt-3">
                    <div>
                      <p className="text-muted mb-1">Full Job ID</p>
                      <p className="text-white break-all">{job.id}</p>
                    </div>
                    <div>
                      <p className="text-muted mb-1">Worker</p>
                      <p className="text-white">{job.worker_id ?? 'none'}</p>
                    </div>
                    <div>
                      <p className="text-muted mb-1">Payload</p>
                      <pre className="text-white bg-surface p-2 rounded border border-border overflow-x-auto">
                        {JSON.stringify(job.payload, null, 2)}
                      </pre>
                    </div>
                    <div>
                      <p className="text-muted mb-1">Error</p>
                      <pre className="text-danger bg-surface p-2 rounded border border-border overflow-x-auto whitespace-pre-wrap">
                        {job.error}
                      </pre>
                    </div>
                    <div>
                      <p className="text-muted mb-1">Created</p>
                      <p className="text-white">{job.created_at ? new Date(job.created_at).toLocaleString() : '—'}</p>
                    </div>
                    <div>
                      <p className="text-muted mb-1">Dead-lettered at</p>
                      <p className="text-white">{job.completed_at ? new Date(job.completed_at).toLocaleString() : '—'}</p>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Pagination */}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-center gap-3 text-sm">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
            className="px-3 py-1 rounded border border-border text-muted hover:text-white disabled:opacity-30"
          >
            Prev
          </button>
          <span className="text-muted text-xs">Page {page} of {Math.ceil(total / PAGE_SIZE)}</span>
          <button
            onClick={() => setPage(p => p + 1)}
            disabled={page >= Math.ceil(total / PAGE_SIZE)}
            className="px-3 py-1 rounded border border-border text-muted hover:text-white disabled:opacity-30"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
