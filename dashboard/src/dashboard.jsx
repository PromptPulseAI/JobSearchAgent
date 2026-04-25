/**
 * JobSearchAgent Dashboard — skeleton
 * Full implementation: Commit 12
 *
 * Six panels:
 *  1. Daily Digest       — last run timestamp, jobs found/new/skipped
 *  2. Conversion Funnel  — Discovered → Tailored → Applied → Interview rates
 *  3. Pending Review     — jobs awaiting Gate 1 approval (pending_approval.json)
 *  4. Job Cards          — per-job cards with status, score, ATS%, action buttons
 *  5. Follow-up Reminders— Applied jobs > 7 days old
 *  6. Run History        — last 30 days timeline
 */
import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'

// TODO(Commit 12): Replace all stubs with real data loading from:
//   data/application_tracker.json
//   data/run_history.json
//   data/job_matches.json
//   data/pending_approval.json  (poll for Gate 1 approvals)

function Dashboard() {
  const [tracker, setTracker] = useState(null)
  const [runHistory, setRunHistory] = useState([])
  const [pendingApproval, setPendingApproval] = useState(null)

  useEffect(() => {
    // TODO(Commit 12): Load data from backend API or local file system
    // Poll pending_approval.json every 5 seconds for Gate 1 updates
  }, [])

  return (
    <div style={{ fontFamily: 'system-ui, sans-serif', padding: '1rem' }}>
      <h1>JobSearchAgent Dashboard</h1>
      <p style={{ color: '#888' }}>
        Dashboard implementation: Commit 12
      </p>

      {/* TODO(Commit 12): Implement all 6 panels */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '1rem' }}>
        <Panel title="Daily Digest" />
        <Panel title="Conversion Funnel" />
        <Panel title="Pending Review" />
        <Panel title="Job Cards" />
        <Panel title="Follow-up Reminders" />
        <Panel title="Run History" />
      </div>
    </div>
  )
}

function Panel({ title }) {
  return (
    <div style={{ border: '1px solid #ddd', borderRadius: 8, padding: '1rem' }}>
      <h3 style={{ margin: 0, marginBottom: '0.5rem' }}>{title}</h3>
      <p style={{ color: '#aaa', fontSize: '0.9rem' }}>Not yet implemented</p>
    </div>
  )
}

ReactDOM.createRoot(document.getElementById('root')).render(<Dashboard />)
