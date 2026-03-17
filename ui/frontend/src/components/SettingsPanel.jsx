import { useState, useEffect } from 'react'

export default function SettingsPanel() {
  const [settings, setSettings] = useState(null)

  useEffect(() => {
    fetch('/api/settings')
      .then(r => r.json())
      .then(setSettings)
      .catch(() => {})
  }, [])

  if (!settings) return (
    <div style={{ color: 'var(--text-muted)', fontSize: 13, padding: '32px 0', textAlign: 'center' }}>
      Loading settings…
    </div>
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <SettingsGroup title="Models">
        <SettingRow label="Primary model"    value={settings.model_name}      note="Used for all agent reasoning" />
        <SettingRow label="Embedding model"  value={settings.embedding_model} note="Used for RAG vector embeddings" />
        <SettingRow label="Max tokens"       value={settings.max_tokens} />
        <SettingRow label="Temperature"      value={settings.temperature} />
      </SettingsGroup>

      <SettingsGroup title="Integrations">
        <SettingRow
          label="Anthropic API"
          value="Configured"
          status="ok"
        />
        <SettingRow
          label="Tavily Search"
          value={settings.tavily_configured ? 'Configured' : 'Not configured — using mock'}
          status={settings.tavily_configured ? 'ok' : 'warn'}
        />
      </SettingsGroup>

      <SettingsGroup title="Feedback Loop">
        <SettingRow label="Enabled"              value={settings.enable_feedback_loop ? 'Yes' : 'No'} />
        <SettingRow label="Score threshold"      value={`${settings.feedback_score_threshold} / 10`} note="Critic score below this triggers retries" />
        <SettingRow label="Max iterations"       value={settings.max_feedback_iterations} />
      </SettingsGroup>

      <SettingsGroup title="Memory">
        <SettingRow label="KV backend"          value={settings.memory_backend} />
        <SettingRow label="Vector memory"       value={settings.enable_vector_memory ? 'Enabled' : 'Disabled'} />
        <SettingRow label="RAG top-K"           value={settings.rag_top_k} />
      </SettingsGroup>

      <div style={{
        padding: '12px 14px',
        background: 'var(--surface-2)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6,
      }}>
        Settings are read from your <code style={{ fontFamily: 'var(--mono)', fontSize: 11, background: 'var(--border)', padding: '1px 4px', borderRadius: 3 }}>.env</code> file.
        To change them, edit <code style={{ fontFamily: 'var(--mono)', fontSize: 11, background: 'var(--border)', padding: '1px 4px', borderRadius: 3 }}>.env</code> and restart the backend server.
      </div>
    </div>
  )
}

function SettingsGroup({ title, children }) {
  return (
    <div style={{
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius)',
      overflow: 'hidden',
    }}>
      <div style={{
        padding: '9px 14px',
        background: 'var(--surface-2)',
        borderBottom: '1px solid var(--border)',
        fontSize: 11, fontWeight: 700,
        color: 'var(--text-muted)',
        textTransform: 'uppercase',
        letterSpacing: '.06em',
      }}>{title}</div>
      {children}
    </div>
  )
}

function SettingRow({ label, value, note, status }) {
  const statusColor = status === 'ok' ? 'var(--green)' : status === 'warn' ? 'var(--amber)' : null

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12,
      padding: '9px 14px',
      borderBottom: '1px solid var(--border-light)',
      fontSize: 12,
    }}>
      <div style={{ flex: 1 }}>
        <div style={{ color: 'var(--text-secondary)' }}>{label}</div>
        {note && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 1 }}>{note}</div>}
      </div>
      <div style={{
        fontFamily: 'var(--mono)', fontSize: 11, fontWeight: 500,
        color: statusColor || 'var(--text-primary)',
      }}>
        {String(value)}
      </div>
    </div>
  )
}
