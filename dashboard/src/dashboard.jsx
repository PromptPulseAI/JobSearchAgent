/**
 * JobSearchAgent Dashboard — 6 panels
 * Run: cd dashboard && npm install && npm run dev
 * Requires: python dashboard/api_server.py (in a separate terminal)
 */
import React, { useEffect, useState, useCallback } from 'react'
import ReactDOM from 'react-dom/client'

const API = '/api'
const POLL_MS = 5000

// ── Styles ────────────────────────────────────────────────────────────────────

const s = {
  root:        { fontFamily: 'system-ui, sans-serif', padding: '1rem', maxWidth: 1200, margin: '0 auto', background: '#f5f5f5', minHeight: '100vh' },
  header:      { display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' },
  title:       { fontSize: '1.4rem', fontWeight: 700, margin: 0 },
  grid:        { display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: '1rem' },
  card:        { background: '#fff', borderRadius: 8, padding: '1rem', boxShadow: '0 1px 4px rgba(0,0,0,.1)' },
  cardTitle:   { fontSize: '0.85rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', color: '#555', marginBottom: '0.75rem' },
  metric:      { display: 'flex', justifyContent: 'space-between', padding: '0.25rem 0', borderBottom: '1px solid #f0f0f0', fontSize: '0.88rem' },
  jobRow:      { padding: '0.5rem 0', borderBottom: '1px solid #f0f0f0', fontSize: '0.85rem' },
  btn:         { padding: '0.2rem 0.55rem', fontSize: '0.8rem', borderRadius: 4, border: 'none', cursor: 'pointer', margin: '0 2px' },
  btnGreen:    { background: '#22c55e', color: '#fff' },
  btnRed:      { background: '#ef4444', color: '#fff' },
  funnel:      { display: 'flex', flexDirection: 'column', gap: '0.4rem' },
  funnelRow:   { display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' },
  empty:       { color: '#999', fontSize: '0.85rem', textAlign: 'center', padding: '1rem' },
  histRow:     { display: 'flex', justifyContent: 'space-between', padding: '0.25rem 0', fontSize: '0.8rem', borderBottom: '1px solid #f5f5f5' },
  pendingCard: { background: '#eff6ff', border: '1px solid #bfdbfe', borderRadius: 6, padding: '0.6rem', marginBottom: '0.5rem' },
  followBadge: { background: '#fef3c7', color: '#92400e', padding: '0.1rem 0.4rem', borderRadius: 4, fontSize: '0.75rem', marginLeft: 4 },
}

const STATUS_COLOR = {
  Discovered: { bg: '#e0e7ff', fg: '#3730a3' },
  Tailored:   { bg: '#d1fae5', fg: '#065f46' },
  Applied:    { bg: '#fef3c7', fg: '#92400e' },
  Interview:  { bg: '#dbeafe', fg: '#1e40af' },
  Offered:    { bg: '#f0fdf4', fg: '#166534' },
  Accepted:   { bg: '#bbf7d0', fg: '#14532d' },
  Rejected:   { bg: '#fee2e2', fg: '#991b1b' },
  Ghosted:    { bg: '#f3f4f6', fg: '#6b7280' },
  Declined:   { bg: '#fce7f3', fg: '#9d174d' },
}

const TRANSITIONS = {
  Discovered: ['Tailored', 'Rejected'],
  Tailored:   ['Applied', 'Rejected'],
  Applied:    ['Interview', 'Rejected', 'Ghosted'],
  Interview:  ['Offered', 'Rejected'],
  Offered:    ['Accepted', 'Declined'],
  Ghosted:    ['Applied'],
}

function Badge({ status }) {
  const c = STATUS_COLOR[status] ?? { bg: '#eee', fg: '#333' }
  return <span style={{ display: 'inline-block', padding: '0.15rem 0.5rem', borderRadius: 12, fontSize: '0.75rem', fontWeight: 600, background: c.bg, color: c.fg }}>{status}</span>
}

function FunnelBar({ pct }) {
  return <div style={{ height: 12, borderRadius: 6, background: '#3b82f6', width: `${Math.max(pct, 2)}%`, transition: 'width 0.3s' }} />
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function apiFetch(path) {
  const res = await fetch(`${API}${path}`)
  if (!res.ok) throw new Error(`${res.status}`)
  return res.json()
}

async function apiPost(path, body) {
  const res = await fetch(`${API}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  return res.json()
}

// ── Panel 1: Daily Digest ─────────────────────────────────────────────────────

function DailyDigest({ history, tracker }) {
  const last = history[history.length - 1] ?? {}
  return (
    <div style={s.card}>
      <div style={s.cardTitle}>Daily Digest</div>
      {last.timestamp ? (
        <>
          <div style={s.metric}><span>Last run</span><span>{new Date(last.timestamp).toLocaleString()}</span></div>
          <div style={s.metric}><span>Jobs found</span><span>{last.jobs_found ?? 0}</span></div>
          <div style={s.metric}><span>Approved</span><span>{last.jobs_approved ?? 0}</span></div>
          <div style={s.metric}><span>Completed</span><span>{last.jobs_completed ?? 0}</span></div>
          <div style={s.metric}><span>Skipped</span><span>{last.jobs_skipped ?? 0}</span></div>
          <div style={s.metric}><span>Active applications</span><span>{(tracker?.jobs ?? []).length}</span></div>
          {last.dry_run && <div style={{ color: '#f59e0b', fontSize: '0.8rem', marginTop: 6 }}>⚠ Dry run — no API calls made</div>}
        </>
      ) : <div style={s.empty}>No runs recorded yet.</div>}
    </div>
  )
}

// ── Panel 2: Conversion Funnel ────────────────────────────────────────────────

function ConversionFunnel({ tracker }) {
  const m = tracker?.metrics ?? {}
  const top = Math.max(m.total_discovered || 0, 1)
  const stages = [
    ['Discovered', m.total_discovered ?? 0],
    ['Tailored',   m.total_tailored   ?? 0],
    ['Applied',    m.total_applied    ?? 0],
    ['Interview',  m.total_interview  ?? 0],
    ['Offered',    m.total_offered    ?? 0],
    ['Accepted',   m.total_accepted   ?? 0],
  ]
  return (
    <div style={s.card}>
      <div style={s.cardTitle}>Conversion Funnel</div>
      <div style={s.funnel}>
        {stages.map(([label, count]) => (
          <div key={label} style={s.funnelRow}>
            <span style={{ width: 90, flexShrink: 0 }}>{label}</span>
            <FunnelBar pct={count / top * 100} />
            <span style={{ color: '#555' }}>{count}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Panel 3: Pending Review (Gate 1) ─────────────────────────────────────────

function PendingReview({ pending, onApprove }) {
  const [selected, setSelected] = useState(new Set())
  const jobs = pending?.jobs ?? []
  const isAwaiting = pending?.status === 'awaiting_approval'

  function toggle(id) {
    setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  }

  async function submitApproval(approvedIds) {
    await apiPost('/approve', { approved_ids: approvedIds })
    setSelected(new Set())
    onApprove?.()
  }

  if (!isAwaiting) return (
    <div style={s.card}><div style={s.cardTitle}>Pending Review (Gate 1)</div><div style={s.empty}>No jobs awaiting approval.</div></div>
  )

  return (
    <div style={s.card}>
      <div style={s.cardTitle}>Pending Review — {jobs.length} job(s) found</div>
      {jobs.map(job => (
        <div key={job.job_id} style={s.pendingCard}>
          <label style={{ display: 'flex', gap: 8, cursor: 'pointer' }}>
            <input type="checkbox" checked={selected.has(job.job_id)} onChange={() => toggle(job.job_id)} />
            <div>
              <strong>{job.title}</strong> @ {job.company}<br />
              <span style={{ color: '#555', fontSize: '0.8rem' }}>{job.location} · Score: {Math.round(job.score)}/100</span>
              {job.score_breakdown?.reasoning && <div style={{ fontSize: '0.75rem', color: '#777', marginTop: 2 }}>{job.score_breakdown.reasoning}</div>}
            </div>
          </label>
        </div>
      ))}
      <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
        <button style={{ ...s.btn, ...s.btnGreen }} onClick={() => submitApproval([...selected])} disabled={selected.size === 0}>
          Approve {selected.size > 0 ? `(${selected.size})` : ''}
        </button>
        <button style={{ ...s.btn, ...s.btnRed }} onClick={() => submitApproval([])}>Reject All</button>
      </div>
    </div>
  )
}

// ── Panel 4: Job Cards ────────────────────────────────────────────────────────

function JobCards({ tracker, onStatusChange }) {
  const jobs = [...(tracker?.jobs ?? [])].sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))

  async function changeStatus(jobId, newStatus) {
    await apiPost('/status', { job_id: jobId, status: newStatus })
    onStatusChange?.()
  }

  if (jobs.length === 0) return (
    <div style={s.card}><div style={s.cardTitle}>Job Cards</div><div style={s.empty}>No active applications.</div></div>
  )

  return (
    <div style={s.card}>
      <div style={s.cardTitle}>Job Cards ({jobs.length})</div>
      {jobs.map(job => (
        <div key={job.job_id} style={s.jobRow}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div>
              <strong>{job.title}</strong> @ {job.company}&nbsp;<Badge status={job.status} />
              {job.follow_up_needed && <span style={s.followBadge}>Follow up!</span>}
            </div>
            <span style={{ color: '#999', fontSize: '0.75rem' }}>{Math.round(job.score)}/100</span>
          </div>
          <div style={{ marginTop: 4, display: 'flex', flexWrap: 'wrap' }}>
            {(TRANSITIONS[job.status] ?? []).map(ns => {
              const c = STATUS_COLOR[ns] ?? { bg: '#eee', fg: '#333' }
              return <button key={ns} style={{ ...s.btn, background: c.bg, color: c.fg }} onClick={() => changeStatus(job.job_id, ns)}>→ {ns}</button>
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Panel 5: Follow-up Reminders ─────────────────────────────────────────────

function FollowupReminders({ tracker }) {
  const followups = (tracker?.jobs ?? []).filter(j => j.follow_up_needed)
  return (
    <div style={s.card}>
      <div style={s.cardTitle}>Follow-up Reminders</div>
      {followups.length === 0
        ? <div style={s.empty}>No follow-ups needed.</div>
        : followups.map(job => (
          <div key={job.job_id} style={s.jobRow}>
            <strong>{job.title}</strong> @ {job.company}
            <span style={{ ...s.followBadge, marginLeft: 6 }}>Applied {job.updated_at ? new Date(job.updated_at).toLocaleDateString() : '—'}</span>
            {job.url && <div><a href={job.url} target="_blank" rel="noreferrer" style={{ fontSize: '0.75rem', color: '#3b82f6' }}>View posting ↗</a></div>}
          </div>
        ))
      }
    </div>
  )
}

// ── Panel 6: Run History ──────────────────────────────────────────────────────

function RunHistory({ history }) {
  const recent = [...history].reverse().slice(0, 30)
  return (
    <div style={s.card}>
      <div style={s.cardTitle}>Run History (last 30)</div>
      {recent.length === 0
        ? <div style={s.empty}>No run history yet.</div>
        : recent.map((run, i) => (
          <div key={i} style={s.histRow}>
            <span style={{ color: '#555' }}>{new Date(run.timestamp).toLocaleDateString()}</span>
            <span>Found: {run.jobs_found ?? 0}</span>
            <span>Done: {run.jobs_completed ?? 0}</span>
            {run.dry_run && <span style={{ color: '#f59e0b' }}>dry</span>}
          </div>
        ))
      }
    </div>
  )
}

// ── Main Dashboard ────────────────────────────────────────────────────────────

function Dashboard() {
  const [tracker, setTracker] = useState(null)
  const [history, setHistory] = useState([])
  const [pending, setPending] = useState(null)
  const [lastRefresh, setLastRefresh] = useState(null)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    try {
      const [t, h, p] = await Promise.all([
        apiFetch('/tracker'),
        apiFetch('/run-history'),
        apiFetch('/pending'),
      ])
      setTracker(t)
      setHistory(Array.isArray(h) ? h : [])
      setPending(p)
      setLastRefresh(new Date().toLocaleTimeString())
      setError(null)
    } catch (e) {
      setError(`API error: ${e.message} — is api_server.py running?`)
    }
  }, [])

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, POLL_MS)
    return () => clearInterval(id)
  }, [refresh])

  return (
    <div style={s.root}>
      <div style={s.header}>
        <h1 style={s.title}>JobSearchAgent</h1>
        <span style={{ fontSize: '0.8rem', color: error ? '#ef4444' : '#666' }}>
          {error ?? `Refreshed: ${lastRefresh ?? '…'}`}
        </span>
      </div>
      <div style={s.grid}>
        <DailyDigest history={history} tracker={tracker} />
        <ConversionFunnel tracker={tracker} />
        <PendingReview pending={pending} onApprove={refresh} />
        <JobCards tracker={tracker} onStatusChange={refresh} />
        <FollowupReminders tracker={tracker} />
        <RunHistory history={history} />
      </div>
    </div>
  )
}

ReactDOM.createRoot(document.getElementById('root')).render(<Dashboard />)
