import { useState } from 'react'

export default function RunForm({ form, setForm, isStreaming, onSubmit, onCancel }) {
  return (
    <form onSubmit={onSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10 }}>Startup Objective</div>
      <textarea
        value={form.objective}
        onChange={e => setForm(f => ({ ...f, objective: e.target.value }))}
        placeholder="e.g. Build an AI-native CRM for freelancers…"
        rows={3}
        style={{
          width: '100%', resize: 'none',
          padding: '10px 12px',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
          fontSize: 13,
          background: 'var(--surface)',
          color: 'var(--text-primary)',
          lineHeight: 1.5,
          outline: 'none',
          transition: 'border-color .15s',
        }}
        onFocus={e => e.target.style.borderColor = 'var(--accent)'}
        onBlur={e => e.target.style.borderColor = 'var(--border)'}
      />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, margin: '12px 0' }}>
        {[
          ['enable_critic',       'Enable critic agent'],
          ['enable_feedback_loop','Enable feedback loop'],
          ['enable_vector_memory','Enable vector memory (RAG)'],
        ].map(([key, label]) => (
          <label key={key} style={{
            display: 'flex', alignItems: 'center', gap: 8,
            fontSize: 12, color: 'var(--text-secondary)', cursor: 'pointer',
          }}>
            <input
              type="checkbox"
              checked={form[key]}
              onChange={e => setForm(f => ({ ...f, [key]: e.target.checked }))}
              style={{ accentColor: 'var(--accent)', width: 14, height: 14 }}
            />
            {label}
          </label>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 8 }}>
        <button
          type="submit"
          disabled={isStreaming || !form.objective.trim()}
          style={{
            flex: 1, padding: '9px 0',
            background: isStreaming || !form.objective.trim()
              ? 'var(--border)' : 'var(--accent)',
            color: isStreaming || !form.objective.trim()
              ? 'var(--text-muted)' : '#fff',
            borderRadius: 'var(--radius)',
            fontWeight: 600, fontSize: 13,
            transition: 'all .15s',
            cursor: isStreaming || !form.objective.trim() ? 'not-allowed' : 'pointer',
          }}
        >
          {isStreaming ? 'Running…' : '▶  Run Pipeline'}
        </button>
        {isStreaming && (
          <button
            type="button"
            onClick={onCancel}
            style={{
              padding: '9px 14px',
              background: 'var(--red-bg)', color: 'var(--red)',
              border: '1px solid var(--red-border)',
              borderRadius: 'var(--radius)',
              fontWeight: 500, fontSize: 13,
            }}
          >Stop</button>
        )}
      </div>
    </form>
  )
}
