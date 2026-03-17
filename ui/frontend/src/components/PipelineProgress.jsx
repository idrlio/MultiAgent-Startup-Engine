import clsx from 'clsx'

const AGENTS = [
  { id: 'research',  label: 'Research',  desc: 'Market intelligence',   color: '#2563eb' },
  { id: 'ceo',       label: 'CEO',        desc: 'Vision & strategy',     color: '#7c3aed' },
  { id: 'product',   label: 'Product',    desc: 'Specs & roadmap',       color: '#0891b2' },
  { id: 'engineer',  label: 'Engineer',   desc: 'Architecture',          color: '#059669' },
  { id: 'marketing', label: 'Marketing',  desc: 'GTM & positioning',     color: '#d97706' },
  { id: 'critic',    label: 'Critic',     desc: 'Quality control',       color: '#dc2626' },
]

const STATUS_CONFIG = {
  pending:   { bg: 'var(--surface-2)', border: 'var(--border)',        dot: '#d4d4d0', label: 'Waiting'  },
  running:   { bg: 'var(--blue-bg)',   border: 'var(--blue-border)',   dot: '#2563eb', label: 'Running'  },
  succeeded: { bg: 'var(--green-bg)',  border: 'var(--green-border)',  dot: '#16a34a', label: 'Done'     },
  failed:    { bg: 'var(--red-bg)',    border: 'var(--red-border)',    dot: '#dc2626', label: 'Failed'   },
  skipped:   { bg: 'var(--surface-2)' ,border: 'var(--border)',       dot: '#9b9b97', label: 'Skipped'  },
}

export default function PipelineProgress({ statuses, previews, feedbackRound, isStreaming }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
        <div style={{ fontWeight: 600, fontSize: 13 }}>Pipeline</div>
        {feedbackRound > 0 && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6,
            fontSize: 11, fontWeight: 500,
            color: 'var(--amber)', background: 'var(--amber-bg)',
            border: '1px solid var(--amber-border)',
            borderRadius: 20, padding: '3px 10px',
          }}>
            <span className="pulse">●</span>
            Feedback round {feedbackRound}
          </div>
        )}
        {isStreaming && feedbackRound === 0 && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6,
            fontSize: 11, color: 'var(--blue)',
            background: 'var(--blue-bg)',
            border: '1px solid var(--blue-border)',
            borderRadius: 20, padding: '3px 10px',
          }}>
            <span className="pulse">●</span> Running
          </div>
        )}
      </div>

      {/* Steps */}
      {AGENTS.map((agent, i) => {
        const status = statuses[agent.id] || 'pending'
        const cfg    = STATUS_CONFIG[status] || STATUS_CONFIG.pending
        const preview = previews[agent.id]

        return (
          <div
            key={agent.id}
            className="fade-in"
            style={{
              background: cfg.bg,
              border: `1px solid ${cfg.border}`,
              borderRadius: 'var(--radius)',
              padding: '12px 14px',
              transition: 'all .25s',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {/* Step number / status dot */}
              <div style={{
                width: 28, height: 28, borderRadius: '50%',
                background: status === 'pending' ? 'var(--border)' : cfg.dot,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                flexShrink: 0,
                transition: 'background .25s',
              }}>
                {status === 'running' ? (
                  <div className="spin" style={{
                    width: 12, height: 12, borderRadius: '50%',
                    border: '2px solid rgba(255,255,255,.3)',
                    borderTopColor: '#fff',
                  }} />
                ) : status === 'succeeded' ? (
                  <span style={{ color: '#fff', fontSize: 11 }}>✓</span>
                ) : status === 'failed' ? (
                  <span style={{ color: '#fff', fontSize: 11 }}>✕</span>
                ) : (
                  <span style={{ color: 'var(--text-muted)', fontSize: 11, fontFamily: 'var(--mono)' }}>{i + 1}</span>
                )}
              </div>

              {/* Agent info */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontWeight: 600, fontSize: 13 }}>{agent.label}</span>
                  <span style={{
                    fontSize: 10, fontWeight: 500,
                    color: cfg.dot === '#d4d4d0' ? 'var(--text-muted)' : cfg.dot,
                    textTransform: 'uppercase', letterSpacing: '.05em',
                  }}>{cfg.label}</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{agent.desc}</div>
              </div>

              {/* Timing or color dot */}
              <div style={{
                width: 8, height: 8, borderRadius: '50%',
                background: agent.color, opacity: status === 'pending' ? .2 : .8,
                flexShrink: 0,
              }} />
            </div>

            {/* Preview text */}
            {preview && status === 'succeeded' && (
              <div style={{
                marginTop: 8,
                paddingTop: 8,
                borderTop: '1px solid var(--green-border)',
                fontSize: 11,
                color: 'var(--text-secondary)',
                lineHeight: 1.5,
                fontStyle: 'italic',
              }}>
                {preview.slice(0, 160)}{preview.length > 160 ? '…' : ''}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
