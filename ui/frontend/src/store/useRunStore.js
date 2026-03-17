import { useState, useCallback, useRef } from 'react'

const API = '/api'

export function useRunStore() {
  const [runs, setRuns]               = useState([])
  const [activeRun, setActiveRun]     = useState(null)   // RunDetailSchema
  const [agentStatuses, setAgentStatuses] = useState({}) // agent -> status
  const [agentPreviews, setAgentPreviews] = useState({}) // agent -> preview text
  const [isStreaming, setIsStreaming]  = useState(false)
  const [error, setError]             = useState(null)
  const [feedbackRound, setFeedbackRound] = useState(0)
  const abortRef = useRef(null)

  const fetchRuns = useCallback(async () => {
    try {
      const res = await fetch(`${API}/runs`)
      if (!res.ok) throw new Error(await res.text())
      setRuns(await res.json())
    } catch (e) { setError(e.message) }
  }, [])

  const fetchRun = useCallback(async (runId) => {
    try {
      const res = await fetch(`${API}/runs/${runId}`)
      if (!res.ok) throw new Error(await res.text())
      setActiveRun(await res.json())
    } catch (e) { setError(e.message) }
  }, [])

  const startRun = useCallback(async (payload) => {
    setError(null)
    setIsStreaming(true)
    setAgentStatuses({})
    setAgentPreviews({})
    setFeedbackRound(0)
    setActiveRun(null)

    const ctrl = new AbortController()
    abortRef.current = ctrl

    try {
      const res = await fetch(`${API}/runs/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        signal: ctrl.signal,
      })
      if (!res.ok) throw new Error(await res.text())

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''

        for (const part of parts) {
          const lines = part.trim().split('\n')
          const eventLine = lines.find(l => l.startsWith('event:'))
          const dataLine  = lines.find(l => l.startsWith('data:'))
          if (!eventLine || !dataLine) continue
          const eventType = eventLine.replace('event:', '').trim()
          const data = JSON.parse(dataLine.replace('data:', '').trim())
          _handleSSE(eventType, data)
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') setError(e.message)
    } finally {
      setIsStreaming(false)
      fetchRuns()
    }

    function _handleSSE(type, payload) {
      switch (type) {
        case 'run_started':
          setAgentStatuses(
            Object.fromEntries((payload.data.agents || []).map(a => [a, 'pending']))
          )
          break
        case 'step_started':
          setAgentStatuses(prev => ({ ...prev, [payload.data.agent]: 'running' }))
          break
        case 'step_completed':
          setAgentStatuses(prev => ({
            ...prev,
            [payload.data.agent]: payload.data.success ? 'succeeded' : 'failed',
          }))
          setAgentPreviews(prev => ({
            ...prev,
            [payload.data.agent]: payload.data.content_preview,
          }))
          break
        case 'step_failed':
          setAgentStatuses(prev => ({ ...prev, [payload.data.agent]: 'failed' }))
          break
        case 'feedback_started':
          setFeedbackRound(payload.data.round)
          // Mark flagged agents as running again
          payload.data.agents?.forEach(a =>
            setAgentStatuses(prev => ({ ...prev, [a]: 'running' }))
          )
          break
        case 'feedback_ended':
          setFeedbackRound(0)
          break
        case 'run_completed':
          // Fetch full detail once done
          fetchRun(payload.run_id)
          break
        case 'error':
          setError(payload.data.message)
          break
      }
    }
  }, [fetchRun, fetchRuns])

  const cancelRun = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  return {
    runs, activeRun, agentStatuses, agentPreviews,
    isStreaming, error, feedbackRound,
    startRun, cancelRun, fetchRuns, fetchRun,
  }
}
