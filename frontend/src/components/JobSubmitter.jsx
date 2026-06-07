import { useState } from 'react'
import { Send, Zap } from 'lucide-react'
import { submitJob } from '../api/client'

const JOB_TYPES = [
  { value: 'process_image', label: 'Process Image', payload: '{"url":"https://example.com/img.jpg","operations":["resize","compress"]}' },
  { value: 'send_email',    label: 'Send Email',    payload: '{"to":"user@example.com","subject":"Hello","body":"Test message"}' },
  { value: 'generate_report', label: 'Generate Report', payload: '{"type":"monthly","rows":5000}' },
  { value: 'data_pipeline', label: 'Data Pipeline', payload: '{"source":"database","records":1000}' },
  { value: 'thumbnail',     label: 'Thumbnail',     payload: '{"source_url":"photo.jpg","sizes":[128,256,512]}' },
  { value: 'noop',          label: 'No-op (benchmark)', payload: '{}' },
  { value: 'flaky_job',     label: 'Flaky Job (70% fail)', payload: '{}' },
  { value: 'failing_job',   label: 'Always Fails (→ DLQ)', payload: '{"reason":"intentional test"}' },
  { value: 'slow_job',      label: 'Slow Job (timeout test)', payload: '{"seconds":90}' },
]

const BATCH_SIZES = [1, 5, 10, 50, 100]

export default function JobSubmitter({ onSubmitted }) {
  const [jobType, setJobType]       = useState(JOB_TYPES[0].value)
  const [payload, setPayload]       = useState(JOB_TYPES[0].payload)
  const [priority, setPriority]     = useState('medium')
  const [maxRetries, setMaxRetries] = useState(3)
  const [timeout, setTimeout_]      = useState(120)
  const [delay, setDelay]           = useState(0)
  const [batchSize, setBatchSize]   = useState(1)
  const [status, setStatus]         = useState(null)  // null | 'sending' | 'ok' | 'error'
  const [lastResult, setLastResult] = useState(null)

  function handleTypeChange(type) {
    setJobType(type)
    const found = JOB_TYPES.find(j => j.value === type)
    if (found) setPayload(found.payload)
  }

  async function handleSubmit() {
    let parsed
    try {
      parsed = JSON.parse(payload)
    } catch {
      setStatus('error')
      setLastResult('Invalid JSON payload')
      return
    }

    setStatus('sending')
    setLastResult(null)
    try {
      const jobs = []
      for (let i = 0; i < batchSize; i++) {
        jobs.push(submitJob({
          type: jobType,
          payload: parsed,
          priority,
          max_retries: maxRetries,
          timeout_seconds: timeout,
          delay_seconds: delay > 0 ? delay : undefined,
        }))
      }
      const results = await Promise.all(jobs)
      setStatus('ok')
      setLastResult(batchSize === 1
        ? `Job submitted: ${results[0].id}`
        : `${batchSize} jobs submitted`)
      onSubmitted?.()
    } catch (e) {
      setStatus('error')
      setLastResult(e.message)
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-white mb-1">Submit Job</h2>
        <p className="text-sm text-muted">Push a new job onto the queue for workers to process.</p>
      </div>

      <div className="bg-card border border-border rounded-lg p-6 space-y-4">
        {/* Job type */}
        <Field label="Job Type">
          <select
            value={jobType}
            onChange={e => handleTypeChange(e.target.value)}
            className="w-full bg-surface border border-border rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-accent"
          >
            {JOB_TYPES.map(j => (
              <option key={j.value} value={j.value}>{j.label}</option>
            ))}
          </select>
        </Field>

        {/* Payload */}
        <Field label="Payload (JSON)">
          <textarea
            value={payload}
            onChange={e => setPayload(e.target.value)}
            rows={4}
            className="w-full bg-surface border border-border rounded px-3 py-2 text-sm font-mono text-white focus:outline-none focus:border-accent resize-none"
          />
        </Field>

        {/* Priority + Retries */}
        <div className="grid grid-cols-2 gap-4">
          <Field label="Priority">
            <div className="flex gap-2">
              {['high', 'medium', 'low'].map(p => (
                <button
                  key={p}
                  onClick={() => setPriority(p)}
                  className={`flex-1 py-1.5 text-xs rounded border transition-colors capitalize
                    ${priority === p
                      ? p === 'high' ? 'border-danger text-danger bg-danger/10'
                        : p === 'medium' ? 'border-warning text-warning bg-warning/10'
                        : 'border-success text-success bg-success/10'
                      : 'border-border text-muted hover:text-white'
                    }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </Field>

          <Field label="Max Retries">
            <input
              type="number" min={0} max={10}
              value={maxRetries}
              onChange={e => setMaxRetries(+e.target.value)}
              className="w-full bg-surface border border-border rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-accent"
            />
          </Field>
        </div>

        {/* Timeout + Delay */}
        <div className="grid grid-cols-2 gap-4">
          <Field label="Timeout (seconds)">
            <input
              type="number" min={5} max={3600}
              value={timeout}
              onChange={e => setTimeout_(+e.target.value)}
              className="w-full bg-surface border border-border rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-accent"
            />
          </Field>

          <Field label="Delay (seconds, 0 = immediate)">
            <input
              type="number" min={0}
              value={delay}
              onChange={e => setDelay(+e.target.value)}
              className="w-full bg-surface border border-border rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-accent"
            />
          </Field>
        </div>

        {/* Batch */}
        <Field label="Batch Size">
          <div className="flex gap-2">
            {BATCH_SIZES.map(n => (
              <button
                key={n}
                onClick={() => setBatchSize(n)}
                className={`px-3 py-1.5 text-xs rounded border transition-colors
                  ${batchSize === n ? 'border-accent text-accent bg-accent/10' : 'border-border text-muted hover:text-white'}`}
              >
                {n}
              </button>
            ))}
          </div>
        </Field>

        {/* Submit */}
        <button
          onClick={handleSubmit}
          disabled={status === 'sending'}
          className="w-full flex items-center justify-center gap-2 py-2.5 rounded bg-accent text-surface font-semibold text-sm hover:bg-accent/80 disabled:opacity-50 transition-colors"
        >
          {status === 'sending'
            ? <><Zap size={14} className="animate-spin" /> Submitting…</>
            : <><Send size={14} /> Submit {batchSize > 1 ? `${batchSize} Jobs` : 'Job'}</>
          }
        </button>

        {/* Result */}
        {lastResult && (
          <div className={`text-xs p-3 rounded border font-mono
            ${status === 'ok'
              ? 'border-success/30 bg-success/5 text-success'
              : 'border-danger/30 bg-danger/5 text-danger'
            }`}>
            {lastResult}
          </div>
        )}
      </div>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div>
      <label className="block text-xs text-muted mb-1.5">{label}</label>
      {children}
    </div>
  )
}
