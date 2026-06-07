const BASE = '/api'

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Request failed')
  }
  if (res.status === 204) return null
  return res.json()
}

// Jobs
export const submitJob = (body) =>
  request('/jobs/submit', { method: 'POST', body: JSON.stringify(body) })

export const listJobs = (params = {}) => {
  const qs = new URLSearchParams(params).toString()
  return request(`/jobs${qs ? '?' + qs : ''}`)
}

export const getJob = (id) => request(`/jobs/${id}`)

export const listDeadLetter = (params = {}) => {
  const qs = new URLSearchParams(params).toString()
  return request(`/jobs/dead-letter/list${qs ? '?' + qs : ''}`)
}

export const retryJob = (id) =>
  request(`/jobs/${id}/retry`, { method: 'POST' })

export const deleteJob = (id) =>
  request(`/jobs/${id}`, { method: 'DELETE' })

// Workers
export const listWorkers = () => request('/workers')

// Metrics
export const getMetrics = () => request('/metrics')
