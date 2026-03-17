import { useState } from 'react'
import clsx from 'clsx'

const NAV = [
  { id: 'run',      label: 'New Run',     icon: '▶' },
  { id: 'history',  label: 'History',     icon: '◷' },
  { id: 'memory',   label: 'Memory',      icon: '◈' },
  { id: 'settings', label: 'Settings',    icon: '◎' },
]

export default function Sidebar({ active, onChange }) {
  return (
    <aside style={{
      width: 'var(--sidebar-w)',
      background: 'var(--surface)',
      borderRight: '1px solid var(--border)',
      display: 'flex',
      flexDirection: 'column',
      padding: '0',
      flexShrink: 0,
    }}>
      {/* Logo */}
      <div style={{
        padding: '20px 20px 16px',
        borderBottom: '1px solid var(--border-light)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 30, height: 30,
            background: 'var(--accent)',
            borderRadius: 8,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#fff', fontSize: 14, fontWeight: 700,
            flexShrink: 0,
          }}>A</div>
          <div>
            <div style={{ fontWeight: 600, fontSize: 13, letterSpacing: '-.01em' }}>AgentForge</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>v1.0</div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ padding: '12px 10px', flex: 1 }}>
        {NAV.map(item => (
          <button
            key={item.id}
            onClick={() => onChange(item.id)}
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '8px 10px',
              borderRadius: 'var(--radius-sm)',
              marginBottom: 2,
              background: active === item.id ? 'var(--surface-2)' : 'transparent',
              color: active === item.id ? 'var(--text-primary)' : 'var(--text-secondary)',
              fontWeight: active === item.id ? 500 : 400,
              fontSize: 13,
              textAlign: 'left',
              transition: 'all .15s',
            }}
          >
            <span style={{ fontSize: 12, opacity: .7, width: 16, textAlign: 'center' }}>{item.icon}</span>
            {item.label}
          </button>
        ))}
      </nav>

      {/* Footer */}
      <div style={{
        padding: '14px 20px',
        borderTop: '1px solid var(--border-light)',
        fontSize: 11,
        color: 'var(--text-muted)',
      }}>
        Multi-agent AI system
      </div>
    </aside>
  )
}
