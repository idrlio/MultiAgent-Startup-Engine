import { useState, useEffect } from 'react'

export default function MemoryStats({ activeRun }) {
  const [stats, setStats] = useState(null)

  useEffect(() => {
    fetch('/api/memory/stats')
      .then(r => r.json())
      .then(setStats)
      .catch(() => {})
  }, [activeRun])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <SectionTitle>Live Memory State</SectionTitle>

      {/* KV Memory */}
      <Card>
        <CardHeader color="#7c3aed">Short-term Memory (KV)</CardHeader>
        <MetricRow label="Stored keys" value={stats?.kv_keys ?? '—'} />
        <MetricRow label="Backend"     value="In-memory" />
        <MetricRow label="Persistence" value="Session only" />
      </Card>

      {/* Vector Memory */}
      <Card>
        <CardHeader color="#2563eb">
          Long-term Memory (FAISS)
          <Badge available={stats?.vector_available}>
            {stats?.vector_available ? 'Active' : 'Unavailable'}
          </Badge>
        </CardHeader>
        <MetricRow label="Chunks indexed"  value={stats?.vector_chunks ?? '—'} />
        <MetricRow label="Embed cache"     value={stats?.embed_cache_size ?? '—'} />
        <MetricRow label="Embedding model" value="Claude Haiku" />
        <MetricRow label="Dimensions"      value="256" />
        <MetricRow label="Index type"      value="FAISS IndexFlatIP" />
        <MetricRow label="Similarity"      value="Cosine (L2-normalised)" />
      </Card>

      {/* Current run */}
      {activeRun && (
        <Card>
          <CardHeader color="#059669">Current Run</CardHeader>
          <MetricRow label="Run ID"          value={activeRun.run_id?.slice(0, 12) + '…'} />
          <MetricRow label="Vector chunks"   value={activeRun.vector_chunks ?? '—'} />
          <MetricRow label="Feedback rounds" value={activeRun.feedback_rounds ?? 0} />
          <MetricRow label="Status"          value={activeRun.status} />
        </Card>
      )}

      {/* RAG explanation */}
      <div style={{
        padding: '12px 14px',
        background: 'var(--blue-bg)',
        border: '1px solid var(--blue-border)',
        borderRadius: 'var(--radius)',
        fontSize: 12,
        color: 'var(--blue)',
        lineHeight: 1.6,
      }}>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>How RAG works here</div>
        Each agent's output is chunked, embedded via Claude Haiku (256-dim vectors),
        and stored in FAISS. Before every Claude call, the top-K most semantically
        similar chunks are retrieved and prepended to the prompt — so later agents
        automatically benefit from earlier agents' context.
      </div>
    </div>
  )
}

function SectionTitle({ children }) {
  return (
    <div style={{ fontWeight: 600, fontSize: 13, marginBottom: -4 }}>{children}</div>
  )
}

function Card({ children }) {
  return (
    <div style={{
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius)',
      overflow: 'hidden',
    }}>
      {children}
    </div>
  )
}

function CardHeader({ children, color }) {
  return (
    <div style={{
      padding: '10px 14px',
      background: 'var(--surface-2)',
      borderBottom: '1px solid var(--border)',
      fontSize: 12, fontWeight: 600,
      color,
      display: 'flex', alignItems: 'center', gap: 8,
    }}>
      {children}
    </div>
  )
}

function Badge({ children, available }) {
  return (
    <span style={{
      fontSize: 10, fontWeight: 500, padding: '1px 7px', borderRadius: 10,
      marginLeft: 'auto',
      background: available ? 'var(--green-bg)' : 'var(--red-bg)',
      color: available ? 'var(--green)' : 'var(--red)',
      border: `1px solid ${available ? 'var(--green-border)' : 'var(--red-border)'}`,
    }}>{children}</span>
  )
}

function MetricRow({ label, value }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center',
      padding: '8px 14px',
      borderBottom: '1px solid var(--border-light)',
      fontSize: 12,
    }}>
      <span style={{ color: 'var(--text-muted)', flex: 1 }}>{label}</span>
      <span style={{ fontFamily: 'var(--mono)', fontWeight: 500, fontSize: 11 }}>{String(value)}</span>
    </div>
  )
}
