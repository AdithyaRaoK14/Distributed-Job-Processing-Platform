import { Cpu, Heart, AlertCircle } from 'lucide-react'

function timeSince(ts) {
  if (!ts) return 'never'
  const diff = (Date.now() - new Date(ts).getTime()) / 1000
  if (diff < 5) return 'just now'
  if (diff < 60) return `${Math.round(diff)}s ago`
  return `${Math.round(diff / 60)}m ago`
}

function LoadBar({ value, max }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  const color = pct >= 90 ? 'bg-danger' : pct >= 60 ? 'bg-warning' : 'bg-success'
  return (
    <div className="mt-2">
      <div className="flex justify-between text-xs text-muted mb-1">
        <span>Load</span>
        <span>{value}/{max} ({pct}%)</span>
      </div>
      <div className="h-1.5 bg-surface rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default function WorkerHealth({ workers }) {
  const active = workers.filter(w => w.status === 'active')
  const dead   = workers.filter(w => w.status === 'dead')

  return (
    <div className="space-y-6">
      <div className="flex gap-4 text-sm">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-success" />
          <span className="text-muted">{active.length} active</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-danger" />
          <span className="text-muted">{dead.length} dead</span>
        </div>
      </div>

      {workers.length === 0 && (
        <div className="text-center py-20 text-muted">
          <Cpu size={32} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">No workers registered yet</p>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {workers.map(worker => {
          const isActive = worker.status === 'active'
          const heartbeatAge = worker.last_heartbeat
            ? (Date.now() - new Date(worker.last_heartbeat).getTime()) / 1000
            : 999
          const stale = heartbeatAge > 15

          return (
            <div
              key={worker.id}
              className={`bg-card border rounded-lg p-5 ${
                isActive
                  ? stale ? 'border-warning/50' : 'border-border'
                  : 'border-danger/30 opacity-60'
              }`}
            >
              {/* Header */}
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${isActive ? 'bg-success animate-pulse' : 'bg-danger'}`} />
                    <span className="text-sm font-semibold text-white truncate max-w-[160px]">
                      {worker.hostname || worker.id}
                    </span>
                  </div>
                  <p className="text-xs text-muted font-mono mt-0.5">{worker.id}</p>
                </div>
                {stale && isActive && (
                  <AlertCircle size={14} className="text-warning flex-shrink-0" />
                )}
              </div>

              {/* Stats */}
              <div className="grid grid-cols-2 gap-3 text-xs mb-3">
                <div>
                  <p className="text-muted">Status</p>
                  <p className={`font-semibold capitalize ${isActive ? 'text-success' : 'text-danger'}`}>
                    {worker.status}
                  </p>
                </div>
                <div>
                  <p className="text-muted">Concurrency</p>
                  <p className="text-white font-semibold">{worker.concurrency}</p>
                </div>
                <div>
                  <p className="text-muted">Heartbeat</p>
                  <p className={`font-semibold ${stale ? 'text-warning' : 'text-white'} flex items-center gap-1`}>
                    <Heart size={10} />
                    {timeSince(worker.last_heartbeat)}
                  </p>
                </div>
                <div>
                  <p className="text-muted">Registered</p>
                  <p className="text-muted">{timeSince(worker.registered_at)}</p>
                </div>
              </div>

              <LoadBar value={worker.active_jobs ?? 0} max={worker.concurrency} />
            </div>
          )
        })}
      </div>
    </div>
  )
}
