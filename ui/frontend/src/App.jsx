import { useState } from 'react'
import Sidebar        from './components/Sidebar.jsx'
import PipelineProgress from './components/PipelineProgress.jsx'
import AgentOutputs   from './components/AgentOutputs.jsx'
import CriticPanel    from './components/CriticPanel.jsx'
import MemoryStats    from './components/MemoryStats.jsx'
import RunHistory     from './components/RunHistory.jsx'
import SettingsPanel  from './components/SettingsPanel.jsx'
import { useRunStore } from './store/useRunStore.js'

const RESULT_TABS = [
  { id: 'outputs', label: 'Agent Outputs' },
  { id: 'critic',  label: 'Critic & Feedback' },
]

export default function App() {
  const [page, setPage]         = useState('run')
  const [resultTab, setResultTab] = useState('outputs')
  const [form, setForm]         = useState({
    objective: '',
    enable_critic: true,
    enable_feedback_loop: true,
    enable_vector_memory: true,
    max_feedback_iterations: 2,
    feedback_score_threshold: 6.0,
  })

  const {
    runs, activeRun, agentStatuses, agentPreviews,
    isStreaming, error, feedbackRound,
    startRun, cancelRun, fetchRuns, fetchRun,
  } = useRunStore()

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!form.objective.trim()) return
    setPage('run')
    startRun(form)
  }

  const handleSelectRun = async (runId) => {
    await fetchRun(runId)
    setPage('run')
  }

  const hasResults = activeRun && Object.keys(activeRun.results || {}).length > 0

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      {/* ---- Sidebar ---- */}
      <Sidebar active={page} onChange={setPage} />

      {/* ---- Main ---- */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

        {/* Header */}
        <header style={{
          height: 'var(--header-h)',
          background: 'var(--surface)',
          borderBottom: '1px solid var(--border)',
          display: 'flex', alignItems: 'center',
          padding: '0 24px',
          flexShrink: 0,
          gap: 16,
        }}>
          <div style={{ fontWeight: 600, fontSize: 14, letterSpacing: '-.01em' }}>
            {page === 'run'      && 'Workspace'}
            {page === 'history'  && 'Run History'}
            {page === 'memory'   && 'Memory & RAG'}
            {page === 'settings' && 'Settings'}
          </div>

          {/* Run status badge */}
          {isStreaming && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 6,
              fontSize: 11, fontWeight: 500,
              color: 'var(--blue)',
              background: 'var(--blue-bg)',
              border: '1px solid var(--blue-border)',
              borderRadius: 20, padding: '4px 12px',
            }}>
              <span className="pulse" style={{ fontSize: 8 }}>●</span>
              Pipeline running…
            </div>
          )}
          {activeRun && !isStreaming && (
            <div style={{
              fontSize: 11, fontWeight: 500,
              color:      activeRun.status === 'completed' ? 'var(--green)' : activeRun.status === 'failed' ? 'var(--red)' : 'var(--amber)',
              background: activeRun.status === 'completed' ? 'var(--green-bg)' : activeRun.status === 'failed' ? 'var(--red-bg)' : 'var(--amber-bg)',
              border:     `1px solid ${activeRun.status === 'completed' ? 'var(--green-border)' : activeRun.status === 'failed' ? 'var(--red-border)' : 'var(--amber-border)'}`,
              borderRadius: 20, padding: '4px 12px',
              textTransform: 'capitalize',
            }}>
              {activeRun.status}
            </div>
          )}

          <div style={{ flex: 1 }} />

          {/* Error */}
          {error && (
            <div style={{ fontSize: 11, color: 'var(--red)', maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              ⚠ {error}
            </div>
          )}
        </header>

        {/* Body */}
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex' }}>

          {/* ============================================================
              PAGE: Run
          ============================================================ */}
          {page === 'run' && (
            <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

              {/* Left panel: input + pipeline */}
              <div style={{
                width: 340, flexShrink: 0,
                borderRight: '1px solid var(--border)',
                display: 'flex', flexDirection: 'column',
                overflow: 'hidden',
              }}>
                {/* Objective form */}
                <form onSubmit={handleSubmit} style={{ padding: '20px 20px 0', flexShrink: 0 }}>
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
                    }}
                    onFocus={e => e.target.style.borderColor = 'var(--accent)'}
                    onBlur={e => e.target.style.borderColor = 'var(--border)'}
                  />

                  {/* Options */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, margin: '10px 0' }}>
                    {[
                      ['enable_critic',          'Enable critic agent'],
                      ['enable_feedback_loop',    'Enable feedback loop'],
                      ['enable_vector_memory',    'Enable vector memory (RAG)'],
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

                  {/* Actions */}
                  <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
                    <button
                      type="submit"
                      disabled={isStreaming || !form.objective.trim()}
                      style={{
                        flex: 1, padding: '9px 0',
                        background: isStreaming || !form.objective.trim() ? 'var(--border)' : 'var(--accent)',
                        color: isStreaming || !form.objective.trim() ? 'var(--text-muted)' : '#fff',
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
                        onClick={cancelRun}
                        style={{
                          padding: '9px 14px',
                          background: 'var(--red-bg)',
                          color: 'var(--red)',
                          border: '1px solid var(--red-border)',
                          borderRadius: 'var(--radius)',
                          fontWeight: 500, fontSize: 13,
                        }}
                      >Stop</button>
                    )}
                  </div>
                </form>

                {/* Pipeline progress */}
                <div style={{ flex: 1, overflowY: 'auto', padding: '0 20px 20px' }}>
                  <PipelineProgress
                    statuses={agentStatuses}
                    previews={agentPreviews}
                    feedbackRound={feedbackRound}
                    isStreaming={isStreaming}
                  />
                </div>
              </div>

              {/* Right panel: results */}
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                {/* Result tabs */}
                {hasResults && (
                  <div style={{
                    display: 'flex', gap: 0,
                    borderBottom: '1px solid var(--border)',
                    padding: '0 24px',
                    flexShrink: 0,
                  }}>
                    {RESULT_TABS.map(tab => (
                      <button
                        key={tab.id}
                        onClick={() => setResultTab(tab.id)}
                        style={{
                          padding: '14px 16px',
                          fontSize: 13,
                          fontWeight: resultTab === tab.id ? 600 : 400,
                          color: resultTab === tab.id ? 'var(--text-primary)' : 'var(--text-muted)',
                          borderBottom: resultTab === tab.id ? '2px solid var(--accent)' : '2px solid transparent',
                          marginBottom: -1,
                          transition: 'all .15s',
                        }}
                      >
                        {tab.label}
                      </button>
                    ))}

                    {/* Run summary chips */}
                    {activeRun && !isStreaming && (
                      <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Chip>{activeRun.duration_s?.toFixed(1)}s</Chip>
                        <Chip>{activeRun.succeeded_steps}/{activeRun.total_steps} steps</Chip>
                        {activeRun.feedback_rounds > 0 && <Chip>↺ {activeRun.feedback_rounds} revisions</Chip>}
                        {activeRun.vector_chunks > 0 && <Chip>◈ {activeRun.vector_chunks} chunks</Chip>}
                      </div>
                    )}
                  </div>
                )}

                {/* Tab content */}
                <div style={{ flex: 1, overflow: 'hidden', padding: '20px 24px' }}>
                  {!hasResults && !isStreaming && (
                    <EmptyState />
                  )}
                  {hasResults && resultTab === 'outputs' && (
                    <AgentOutputs results={activeRun.results} />
                  )}
                  {hasResults && resultTab === 'critic' && (
                    <div style={{ height: '100%', overflowY: 'auto' }}>
                      <CriticPanel activeRun={activeRun} />
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ============================================================
              PAGE: History
          ============================================================ */}
          {page === 'history' && (
            <div style={{ flex: 1, overflowY: 'auto', padding: '24px' }}>
              <RunHistory runs={runs} onSelect={handleSelectRun} fetchRuns={fetchRuns} />
            </div>
          )}

          {/* ============================================================
              PAGE: Memory
          ============================================================ */}
          {page === 'memory' && (
            <div style={{ flex: 1, overflowY: 'auto', padding: '24px', maxWidth: 600 }}>
              <MemoryStats activeRun={activeRun} />
            </div>
          )}

          {/* ============================================================
              PAGE: Settings
          ============================================================ */}
          {page === 'settings' && (
            <div style={{ flex: 1, overflowY: 'auto', padding: '24px', maxWidth: 560 }}>
              <SettingsPanel />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Chip({ children }) {
  return (
    <span style={{
      fontSize: 11, fontWeight: 500,
      padding: '3px 8px', borderRadius: 6,
      background: 'var(--surface-2)',
      border: '1px solid var(--border)',
      color: 'var(--text-secondary)',
      fontFamily: 'var(--mono)',
    }}>{children}</span>
  )
}

function EmptyState() {
  return (
    <div style={{
      height: '100%', display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center', gap: 12,
      color: 'var(--text-muted)',
    }}>
      <div style={{ fontSize: 40, opacity: .3 }}>◈</div>
      <div style={{ fontSize: 14, fontWeight: 500 }}>No results yet</div>
      <div style={{ fontSize: 12, textAlign: 'center', maxWidth: 280, lineHeight: 1.6 }}>
        Enter a startup objective in the left panel and click <strong>Run Pipeline</strong> to start.
      </div>
    </div>
  )
}
