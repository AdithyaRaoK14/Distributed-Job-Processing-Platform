import { useState, useEffect, useRef } from 'react'
import {
  AreaChart, Area, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts'

const CHART_MAX = 30  // seconds of history

function MetricCard({ label, value, sub, color = 'text-white' }) {
  return (
    <div className="bg-card border border-border rounded-lg p-4">
      <p className="text-xs text-muted mb-1">{label}</p>
      <p className={`text-3xl font-bold tabular-nums ${color}`}>{value ?? '—'}</p>
      {sub && <p className="text-xs text-muted mt-1">{sub}</p>}
    </div>
  )
}

export default function QueueMetrics({ metrics, workers }) {
  const [history, setHistory] = useState([])
  const tickRef = useRef(0)

  useEffect(() => {
    if (!metrics) return
    const now = new Date().toLocaleTimeString('en', { hour12: false })
    setHistory(prev => {
      const next = [
        ...prev,
        {
          time: now,
          pending: metrics.queue_depth?.pending ?? 0,
          processing: metrics.queue_depth?.processing ?? 0,
          high: metrics.queue_depth?.high_priority ?? 0,
          medium: metrics.queue_depth?.medium_priority ?? 0,
          low: metrics.queue_depth?.low_priority ?? 0,
          jps: metrics.jobs_per_second ?? 0,
        },
      ]
      return next.slice(-CHART_MAX)
    })
  }, [metrics])

  const activeW = workers?.filter(w => w.status === 'active') ?? []
  const totalActive = activeW.reduce((s, w) => s + (w.active_jobs ?? 0), 0)

  return (
    <div className="space-y-6">
      {/* Top stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
        <MetricCard label="Pending" value={metrics?.queue_depth?.pending} color="text-warning" />
        <MetricCard label="Processing" value={metrics?.queue_depth?.processing} color="text-accent" />
        <MetricCard label="Scheduled" value={metrics?.queue_depth?.scheduled} color="text-purple-400" />
        <MetricCard label="Completed" value={metrics?.total_completed} color="text-success" />
        <MetricCard label="Dead Lettered" value={metrics?.total_dead_lettered} color="text-danger" />
        <MetricCard label="Jobs / sec" value={metrics?.jobs_per_second} color="text-white"
          sub={`${totalActive} tasks running`} />
      </div>

      {/* Priority breakdown */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'High Priority', key: 'high_priority', color: 'text-danger' },
          { label: 'Medium Priority', key: 'medium_priority', color: 'text-warning' },
          { label: 'Low Priority', key: 'low_priority', color: 'text-success' },
        ].map(({ label, key, color }) => (
          <div key={key} className="bg-card border border-border rounded-lg p-4">
            <p className="text-xs text-muted mb-1">{label}</p>
            <p className={`text-2xl font-bold ${color}`}>
              {metrics?.queue_depth?.[key] ?? '—'}
            </p>
          </div>
        ))}
      </div>

      {/* Queue depth over time */}
      <div className="bg-card border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-4 text-white">Queue Depth (live)</h3>
        <ResponsiveContainer width="100%" height={200}>
          <AreaChart data={history}>
            <defs>
              <linearGradient id="gPending" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#d29922" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#d29922" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="gProcessing" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#58a6ff" stopOpacity={0.3} />
                <stop offset="95%" stopColor="#58a6ff" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
            <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#8b949e' }} />
            <YAxis tick={{ fontSize: 10, fill: '#8b949e' }} />
            <Tooltip
              contentStyle={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 6 }}
              labelStyle={{ color: '#8b949e' }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Area type="monotone" dataKey="pending" stroke="#d29922" fill="url(#gPending)" name="Pending" />
            <Area type="monotone" dataKey="processing" stroke="#58a6ff" fill="url(#gProcessing)" name="Processing" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Priority breakdown over time */}
      <div className="bg-card border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-4 text-white">Priority Breakdown (live)</h3>
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={history.slice(-15)}>
            <CartesianGrid strokeDasharray="3 3" stroke="#30363d" />
            <XAxis dataKey="time" tick={{ fontSize: 10, fill: '#8b949e' }} />
            <YAxis tick={{ fontSize: 10, fill: '#8b949e' }} />
            <Tooltip
              contentStyle={{ background: '#161b22', border: '1px solid #30363d', borderRadius: 6 }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="high" stackId="a" fill="#f85149" name="High" />
            <Bar dataKey="medium" stackId="a" fill="#d29922" name="Medium" />
            <Bar dataKey="low" stackId="a" fill="#3fb950" name="Low" radius={[2, 2, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* Worker summary */}
      <div className="bg-card border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-3 text-white">Worker Summary</h3>
        <div className="flex gap-6 text-sm">
          <div>
            <span className="text-muted">Active: </span>
            <span className="text-success font-semibold">{metrics?.active_workers ?? 0}</span>
          </div>
          <div>
            <span className="text-muted">Dead: </span>
            <span className="text-danger font-semibold">{metrics?.dead_workers ?? 0}</span>
          </div>
          <div>
            <span className="text-muted">Total tasks running: </span>
            <span className="text-accent font-semibold">{totalActive}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
