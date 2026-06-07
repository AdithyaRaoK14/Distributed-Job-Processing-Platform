import { useState, useEffect, useCallback } from 'react'
import { Activity, Send, Users, AlertTriangle, BarChart2, RefreshCw } from 'lucide-react'
import JobSubmitter from './components/JobSubmitter'
import JobList from './components/JobList'
import WorkerHealth from './components/WorkerHealth'
import QueueMetrics from './components/QueueMetrics'
import DeadLetterQueue from './components/DeadLetterQueue'
import { getMetrics, listWorkers } from './api/client'

const TABS = [
  { id: 'metrics',    label: 'Metrics',      icon: BarChart2 },
  { id: 'submit',     label: 'Submit Job',   icon: Send },
  { id: 'jobs',       label: 'Job History',  icon: Activity },
  { id: 'workers',    label: 'Workers',      icon: Users },
  { id: 'deadletter', label: 'Dead Letter',  icon: AlertTriangle },
]

export default function App() {
  const [tab, setTab] = useState('metrics')
  const [metrics, setMetrics] = useState(null)
  const [workers, setWorkers] = useState([])
  const [lastRefresh, setLastRefresh] = useState(null)
  const [refreshing, setRefreshing] = useState(false)

  const refresh = useCallback(async () => {
    setRefreshing(true)
    try {
      const [m, w] = await Promise.all([getMetrics(), listWorkers()])
      setMetrics(m)
      setWorkers(w)
      setLastRefresh(new Date())
    } catch (e) {
      console.error('Refresh failed:', e)
    } finally {
      setRefreshing(false)
    }
  }, [])

  // Auto-refresh every 2 seconds
  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 2000)
    return () => clearInterval(id)
  }, [refresh])

  const activeWorkers = workers.filter(w => w.status === 'active').length
  const pendingJobs = metrics?.queue_depth?.pending ?? '—'
  const processingJobs = metrics?.queue_depth?.processing ?? '—'

  return (
    <div className="min-h-screen bg-surface">
      {/* Header */}
      <header className="border-b border-border px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-2 h-2 rounded-full bg-success animate-pulse" />
          <h1 className="text-lg font-semibold tracking-tight text-white">
            Distributed Job Queue
          </h1>
          <span className="text-xs text-muted px-2 py-0.5 rounded border border-border">v1.0</span>
        </div>

        <div className="flex items-center gap-6 text-sm text-muted">
          <Stat label="Pending" value={pendingJobs} color="text-warning" />
          <Stat label="Running" value={processingJobs} color="text-accent" />
          <Stat label="Workers" value={activeWorkers} color="text-success" />
          <Stat label="j/s" value={metrics?.jobs_per_second ?? '—'} color="text-white" />
          <button
            onClick={refresh}
            className={`p-1.5 rounded hover:bg-card transition-colors ${refreshing ? 'opacity-50' : ''}`}
          >
            <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} />
          </button>
          {lastRefresh && (
            <span className="text-xs opacity-50">
              {lastRefresh.toLocaleTimeString()}
            </span>
          )}
        </div>
      </header>

      {/* Tabs */}
      <nav className="border-b border-border px-6 flex gap-1">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-2 px-4 py-3 text-sm transition-colors border-b-2 -mb-px
              ${tab === id
                ? 'border-accent text-accent'
                : 'border-transparent text-muted hover:text-white'
              }`}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </nav>

      {/* Content */}
      <main className="p-6 max-w-7xl mx-auto">
        {tab === 'metrics'    && <QueueMetrics metrics={metrics} workers={workers} />}
        {tab === 'submit'     && <JobSubmitter onSubmitted={refresh} />}
        {tab === 'jobs'       && <JobList />}
        {tab === 'workers'    && <WorkerHealth workers={workers} />}
        {tab === 'deadletter' && <DeadLetterQueue onRetried={refresh} />}
      </main>
    </div>
  )
}

function Stat({ label, value, color }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-xs opacity-50">{label}</span>
      <span className={`font-semibold tabular-nums ${color}`}>{value}</span>
    </div>
  )
}
