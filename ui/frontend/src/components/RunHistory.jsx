import { useEffect } from 'react'

const STATUS_STYLE = {
  completed: { color: 'var(--green)', bg: 'var(--green-bg)', border: 'var(--green-border)' },
  partial:   { color: 'var(--amber)', bg: 'var(--amber-bg)', border: 'var(--amber-border)' },
  failed:    { color: 'var(--red)',   bg: 'var(--red-bg)',   border: 'var(--red-border)'   },
  running:   { color: 'var(--blue)',  bg: 'var(--blue-bg)',  border: 'var(--blue-border)'  },
}

export default function RunHistory({ runs, onSelect, fetchRuns }) {
  useEffect(() => { fetchRuns() }, [])

  if (!runs.length) {
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', gap: 8, padding: '48px 0',
        color: 'var(--text-muted)',
      }}>
        <div style={{ fontSize: 28 }}>◷</div>
        <div style={{ fontSize: 13 }}>No runs yet. Start a new run from the sidebar.</div>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 4,
      }}>
        <div style={{ fontWeight: 600, fontSize: 13 }}>Run History</div>
        <button
          onClick={fetchRuns}
          style={{
            fontSize: 11, color: 'var(--text-muted)',
            padding: '4px 10px', borderRadius: 'var(--radius-sm)',
            border: '1px solid var(--border)',
            background: 'var(--surface)',
          }}
        >↻ Refresh</button>
      </div>

      {runs.map(run => {
        const s = STATUS_STYLE[run.status] || STATUS_STYLE.running
        const date = new Date(run.created_at).toLocaleString()
        return (
          <button
            key={run.run_id}
            onClick={() => onSelect(run.run_id)}
            style={{
              display: 'flex', flexDirection: 'column', gap: 6,
              padding: '12px 14px',
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              textAlign: 'left',
              transition: 'box-shadow .15s, border-color .15s',
              cursor: 'pointer',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.boxShadow = 'var(--shadow)'
              e.currentTarget.style.borderColor = 'var(--text-muted)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.boxShadow = 'none'
              e.currentTarget.style.borderColor = 'var(--border)'
            }}
          >
            {/* Top row */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{
                fontSize: 11, fontWeight: 600,
                padding: '2px 8px', borderRadius: 10,
                background: s.bg, color: s.color, border: `1px solid ${s.border}`,
                textTransform: 'capitalize',
              }}>{run.status}</div>
              <div style={{ flex: 1 }} />
              <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--mono)' }}>
                {run.duration_s?.toFixed(1)}s
              </div>
            </div>

            {/* Objective */}
            <div style={{
              fontWeight: 500, fontSize: 13,
              color: 'var(--text-primary)',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {run.objective}
            </div>

            {/* Stats row */}
            <div style={{ display: 'flex', gap: 12, fontSize: 11, color: 'var(--text-muted)' }}>
              <span>✓ {run.succeeded_steps}/{run.total_steps} steps</span>
              {run.feedback_rounds > 0 && <span>↺ {run.feedback_rounds} feedback</span>}
              {run.vector_chunks > 0 && <span>◈ {run.vector_chunks} chunks</span>}
              <span style={{ marginLeft: 'auto' }}>{date}</span>
            </div>
          </button>
        )
      })}
    </div>
  )
}
