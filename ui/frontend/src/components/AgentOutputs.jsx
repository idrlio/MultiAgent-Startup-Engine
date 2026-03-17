import { useState } from 'react'
import ReactMarkdown from 'react-markdown'

const AGENT_META = {
  research:  { label: 'Research',   color: '#2563eb', emoji: '🔍' },
  ceo:       { label: 'CEO',         color: '#7c3aed', emoji: '🧭' },
  product:   { label: 'Product',     color: '#0891b2', emoji: '📋' },
  engineer:  { label: 'Engineer',    color: '#059669', emoji: '⚙️' },
  marketing: { label: 'Marketing',   color: '#d97706', emoji: '📣' },
  critic:    { label: 'Critic',      color: '#dc2626', emoji: '🔬' },
}

function AgentTab({ name, result, isActive, onClick }) {
  const meta   = AGENT_META[name] || { label: name, color: '#666', emoji: '🤖' }
  const isFail = result && !result.success

  return (
    <button
      onClick={onClick}
      style={{
        padding: '8px 14px',
        borderRadius: 'var(--radius-sm)',
        fontSize: 12,
        fontWeight: isActive ? 600 : 400,
        color: isActive ? meta.color : 'var(--text-secondary)',
        background: isActive ? '#fff' : 'transparent',
        border: isActive ? `1px solid var(--border)` : '1px solid transparent',
        boxShadow: isActive ? 'var(--shadow-sm)' : 'none',
        display: 'flex', alignItems: 'center', gap: 5,
        transition: 'all .15s',
        whiteSpace: 'nowrap',
      }}
    >
      <span>{meta.emoji}</span>
      {meta.label}
      {result && (
        <span style={{
          width: 6, height: 6, borderRadius: '50%',
          background: isFail ? 'var(--red)' : 'var(--green)',
          marginLeft: 2,
        }} />
      )}
    </button>
  )
}

export default function AgentOutputs({ results }) {
  const agentNames = Object.keys(results || {})
  const [active, setActive] = useState(agentNames[0] || null)

  if (!agentNames.length) {
    return (
      <div style={{
        flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: 'var(--text-muted)', fontSize: 13,
      }}>
        Agent outputs will appear here once the pipeline runs.
      </div>
    )
  }

  const activeResult = results[active]
  const meta = AGENT_META[active] || { label: active, color: '#666' }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14, height: '100%' }}>
      {/* Tabs */}
      <div style={{
        display: 'flex', gap: 4, flexWrap: 'wrap',
        background: 'var(--surface-2)',
        padding: 4, borderRadius: 'var(--radius)',
      }}>
        {agentNames.map(name => (
          <AgentTab
            key={name}
            name={name}
            result={results[name]}
            isActive={active === name}
            onClick={() => setActive(name)}
          />
        ))}
      </div>

      {/* Content */}
      {activeResult && (
        <div className="fade-in" style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          {/* Meta bar */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '10px 14px',
            background: 'var(--surface-2)',
            borderRadius: 'var(--radius)',
            marginBottom: 12,
            flexShrink: 0,
          }}>
            <div style={{
              width: 6, borderRadius: 2, alignSelf: 'stretch',
              background: meta.color,
            }} />
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{meta.label}</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                {activeResult.duration_s?.toFixed(2)}s
                {activeResult.iteration > 0 && ` · Revision ${activeResult.iteration}`}
                {activeResult.metadata?.mock_search && ' · Mock search'}
              </div>
            </div>
            <div style={{
              fontSize: 11, fontWeight: 500, padding: '3px 10px',
              borderRadius: 20,
              background: activeResult.success ? 'var(--green-bg)' : 'var(--red-bg)',
              color:      activeResult.success ? 'var(--green)'    : 'var(--red)',
              border:     `1px solid ${activeResult.success ? 'var(--green-border)' : 'var(--red-border)'}`,
            }}>
              {activeResult.success ? 'Succeeded' : 'Failed'}
            </div>
          </div>

          {/* Markdown body */}
          <div style={{
            flex: 1, overflowY: 'auto',
            padding: '0 4px',
          }}>
            <div className="md">
              <ReactMarkdown>{activeResult.content}</ReactMarkdown>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
