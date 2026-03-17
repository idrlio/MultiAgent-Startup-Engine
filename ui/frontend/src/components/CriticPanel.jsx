export default function CriticPanel({ activeRun }) {
  const critic = activeRun?.results?.critic
  const score  = activeRun?.critic_score
  const agents = activeRun?.agents_revised || []
  const rounds = activeRun?.feedback_rounds || 0

  if (!critic) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: 'var(--text-muted)', fontSize: 13, padding: '32px 0',
      }}>
        Critic analysis will appear after the pipeline completes.
      </div>
    )
  }

  const scoreColor = score >= 7.5 ? 'var(--green)' : score >= 5 ? 'var(--amber)' : 'var(--red)'
  const scoreBg    = score >= 7.5 ? 'var(--green-bg)' : score >= 5 ? 'var(--amber-bg)' : 'var(--red-bg)'
  const scoreBd    = score >= 7.5 ? 'var(--green-border)' : score >= 5 ? 'var(--amber-border)' : 'var(--red-border)'
  const scoreLabel = score >= 7.5 ? 'Strong' : score >= 5 ? 'Moderate' : 'Needs work'

  return (
    <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      {/* Score card */}
      <div style={{
        display: 'flex', gap: 14, flexWrap: 'wrap',
      }}>
        {/* Confidence score */}
        <div style={{
          flex: '0 0 auto',
          padding: '18px 24px',
          background: scoreBg,
          border: `1px solid ${scoreBd}`,
          borderRadius: 'var(--radius-lg)',
          textAlign: 'center',
          minWidth: 140,
        }}>
          <div style={{ fontSize: 36, fontWeight: 700, color: scoreColor, lineHeight: 1 }}>
            {score?.toFixed(1)}
          </div>
          <div style={{ fontSize: 11, color: scoreColor, fontWeight: 500, marginTop: 4 }}>/ 10</div>
          <div style={{ fontSize: 12, color: scoreColor, marginTop: 6, fontWeight: 500 }}>{scoreLabel}</div>
        </div>

        {/* Stats */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <StatRow label="Feedback rounds" value={rounds} />
          <StatRow label="Agents revised"  value={agents.length > 0 ? agents.join(', ') : 'None'} />
          <StatRow label="Duration"        value={`${critic.duration_s?.toFixed(2)}s`} />
          {critic.iteration > 0 && (
            <StatRow label="Last iteration" value={`Round ${critic.iteration}`} />
          )}
        </div>
      </div>

      {/* Revised agents chips */}
      {agents.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {agents.map(a => (
            <span key={a} style={{
              fontSize: 11, fontWeight: 500,
              padding: '3px 10px', borderRadius: 20,
              background: 'var(--amber-bg)', color: 'var(--amber)',
              border: '1px solid var(--amber-border)',
            }}>↺ {a}</span>
          ))}
        </div>
      )}

      {/* Critic output */}
      <div style={{
        background: 'var(--surface-2)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        padding: '14px 16px',
        maxHeight: 420,
        overflowY: 'auto',
      }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '.06em', marginBottom: 10 }}>
          Critic Report
        </div>
        <div className="md" style={{ fontSize: 13 }}>
          {critic.content.split('\n').map((line, i) => (
            <p key={i} style={{ marginBottom: '.4em', color: 'var(--text-secondary)' }}>{line}</p>
          ))}
        </div>
      </div>
    </div>
  )
}

function StatRow({ label, value }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '8px 12px',
      background: 'var(--surface-2)',
      borderRadius: 'var(--radius-sm)',
      fontSize: 12,
    }}>
      <span style={{ color: 'var(--text-muted)', flex: 1 }}>{label}</span>
      <span style={{ fontWeight: 500, fontFamily: 'var(--mono)', fontSize: 11 }}>{value}</span>
    </div>
  )
}
