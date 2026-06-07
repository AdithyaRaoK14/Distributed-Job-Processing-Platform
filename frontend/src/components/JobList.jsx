import { useState, useEffect } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { listJobs } from '../api/client'

const STATUS_COLORS = {
  pending:      'text-warning border-warning/30 bg-warning/5',
  running:      'text-accent border-accent/30 bg-accent/5',
  completed:    'text-success border-success/30 bg-success/5',
  failed:       'text-danger border-danger/30 bg-danger/5',
  dead_lettered:'text-danger border-danger/50 bg-danger/10',
}

const PRIORITY_DOT = {
  high:   'bg-danger',
  medium: 'bg-warning',
  low:    'bg-success',
}

export default function JobList() {
  const [jobs, setJobs]         = useState([])
  const [total, setTotal]       = useState(0)
  const [page, setPage]         = useState(1)
  const [filterStatus, setFilterStatus] = useState('')
  const [filterPriority, setFilterPriority] = useState('')
  const [expanded, setExpanded] = useState(null)
  const PAGE_SIZE = 20

  useEffect(() => {
    let alive = true
    async function load() {
      try {
        const params = { page, page_size: PAGE_SIZE }
        if (filterStatus) params.status = filterStatus
        if (filterPriority) params.priority = filterPriority
        const data = await listJobs(params)
        if (alive) {
          setJobs(data.jobs)
          setTotal(data.total)
        }
      } catch (e) {
        console.error(e)
      }
    }
    load()
    const id = setInterval(load, 2000)
    return () => { alive = false; clearInterval(id) }
  }, [page, filterStatus, filterPriority])

  const totalPages = Math.ceil(total / PAGE_SIZE)

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <select
          value={filterStatus}
          onChange={e => { setFilterStatus(e.target.value); setPage(1) }}
          className="bg-card border border-border rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-accent"
        >
          <option value="">All Statuses</option>
          {['pending','running','completed','failed','dead_lettered'].map(s => (
            <option key={s} value={s}>{s.replace('_', ' ')}</option>
          ))}
        </select>

        <select
          value={filterPriority}
          onChange={e => { setFilterPriority(e.target.value); setPage(1) }}
          className="bg-card border border-border rounded px-3 py-1.5 text-sm text-white focus:outline-none focus:border-accent"
        >
          <option value="">All Priorities</option>
          {['high','medium','low'].map(p => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>

        <span className="text-xs text-muted self-center">{total} jobs</span>
      </div>

      {/* Table */}
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-muted text-xs">
              <th className="text-left px-4 py-3">ID</th>
              <th className="text-left px-4 py-3">Type</th>
              <th className="text-left px-4 py-3">Priority</th>
              <th className="text-left px-4 py-3">Status</th>
              <th className="text-left px-4 py-3">Retries</th>
              <th className="text-left px-4 py-3">Worker</th>
              <th className="text-left px-4 py-3">Created</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map(job => (
              <>
                <tr
                  key={job.id}
                  onClick={() => setExpanded(expanded === job.id ? null : job.id)}
                  className="border-b border-border hover:bg-surface/50 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3 font-mono text-xs text-muted">{job.id.slice(0, 12)}…</td>
                  <td className="px-4 py-3 text-white">{job.type}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1.5">
                      <div className={`w-1.5 h-1.5 rounded-full ${PRIORITY_DOT[job.priority]}`} />
                      <span className="text-muted text-xs capitalize">{job.priority}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-xs px-2 py-0.5 rounded border capitalize ${STATUS_COLORS[job.status] ?? ''}`}>
                      {job.status.replace('_', ' ')}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted text-xs">
                    {job.retry_count}/{job.max_retries}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-muted">
                    {job.worker_id ? job.worker_id.slice(0, 14) + '…' : '—'}
                  </td>
                  <td className="px-4 py-3 text-xs text-muted">
                    {job.created_at ? new Date(job.created_at).toLocaleTimeString() : '—'}
                  </td>
                </tr>
                {expanded === job.id && (
                  <tr key={`${job.id}-exp`} className="bg-surface/30">
                    <td colSpan={7} className="px-4 py-4">
                      <div className="grid grid-cols-2 gap-4 text-xs font-mono">
                        <div>
                          <p className="text-muted mb-1">Full ID</p>
                          <p className="text-white">{job.id}</p>
                        </div>
                        <div>
                          <p className="text-muted mb-1">Payload</p>
                          <pre className="text-white overflow-x-auto">
                            {JSON.stringify(job.payload, null, 2)}
                          </pre>
                        </div>
                        {job.result && (
                          <div>
                            <p className="text-muted mb-1">Result</p>
                            <pre className="text-success overflow-x-auto">
                              {JSON.stringify(job.result, null, 2)}
                            </pre>
                          </div>
                        )}
                        {job.error && (
                          <div>
                            <p className="text-muted mb-1">Error</p>
                            <p className="text-danger">{job.error}</p>
                          </div>
                        )}
                        {job.started_at && (
                          <div>
                            <p className="text-muted mb-1">Duration</p>
                            <p className="text-white">
                              {job.completed_at
                                ? `${((new Date(job.completed_at) - new Date(job.started_at)) / 1000).toFixed(2)}s`
                                : 'running…'}
                            </p>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>
        {jobs.length === 0 && (
          <p className="text-center py-12 text-muted text-sm">No jobs found</p>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
            className="flex items-center gap-1 px-3 py-1.5 rounded border border-border text-muted hover:text-white disabled:opacity-30"
          >
            <ChevronLeft size={14} /> Prev
          </button>
          <span className="text-muted text-xs">Page {page} of {totalPages}</span>
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            className="flex items-center gap-1 px-3 py-1.5 rounded border border-border text-muted hover:text-white disabled:opacity-30"
          >
            Next <ChevronRight size={14} />
          </button>
        </div>
      )}
    </div>
  )
}
