import { useState, useRef, useCallback } from 'react'

const TOKEN_KEY = 'glassbox_token'

export function useSSE() {
  const [isStreaming, setIsStreaming] = useState(false)
  const [eventObject, setEventObject] = useState(null)   // from mcp_event_triage result
  const [toolCalls, setToolCalls] = useState([])          // [{ name, input, result, isError }]
  const [report, setReport] = useState('')
  const [chatMessages, setChatMessages] = useState([])
  const [error, setError] = useState(null)
  const abortRef = useRef(null)

  const reset = useCallback(() => {
    setEventObject(null)
    setToolCalls([])
    setReport('')
    setError(null)
  }, [])

  const sendMessage = useCallback(async (userMessage) => {
    const token = localStorage.getItem(TOKEN_KEY)
    if (!token) return

    reset()
    setIsStreaming(true)
    setChatMessages(prev => [...prev, { role: 'user', content: userMessage }])

    abortRef.current = new AbortController()

    // Map: tool_name → pending input while waiting for its result
    const pendingInputs = {}

    try {
      const response = await fetch('/api/v1/diagnose/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
        body: JSON.stringify({ issue_description: userMessage }),
        signal: abortRef.current.signal,
      })

      if (!response.ok) {
        const errBody = await response.json().catch(() => ({}))
        throw new Error(errBody?.message || `HTTP ${response.status}: ${response.statusText}`)
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let currentEvent = null

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() // keep incomplete last line

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            const raw = line.slice(6).trim()
            let payload
            try {
              payload = JSON.parse(raw)
            } catch {
              continue
            }

            // ── session_start ──────────────────────────────────────────────
            if (currentEvent === 'session_start') {
              setChatMessages(prev => [...prev, {
                role: 'agent',
                content: '🔄 診斷開始，正在分析症狀…',
              }])
            }

            // ── tool_call ──────────────────────────────────────────────────
            else if (currentEvent === 'tool_call') {
              const { tool_name, tool_input } = payload
              pendingInputs[tool_name] = tool_input
              setToolCalls(prev => [...prev, { name: tool_name, input: tool_input, result: null, isError: false }])
              setChatMessages(prev => [...prev, {
                role: 'agent',
                content: `🔧 呼叫工具：\`${tool_name}\``,
              }])
            }

            // ── tool_result ────────────────────────────────────────────────
            else if (currentEvent === 'tool_result') {
              const { tool_name, tool_result: result, is_error } = payload

              // Patch the last placeholder with this name that has no result yet
              setToolCalls(prev => {
                const idx = [...prev].reverse().findIndex(t => t.name === tool_name && t.result === null)
                if (idx < 0) {
                  return [...prev, { name: tool_name, input: pendingInputs[tool_name] ?? {}, result, isError: is_error }]
                }
                const realIdx = prev.length - 1 - idx
                const next = [...prev]
                next[realIdx] = { ...next[realIdx], result, isError: is_error }
                return next
              })

              // Extract Event Object from mcp_event_triage result
              if (tool_name === 'mcp_event_triage' && result && !is_error) {
                const urgency = result.attributes?.urgency ?? 'low'
                setEventObject({
                  event_id:           result.event_id,
                  event_type:         result.event_type,
                  urgency,
                  recommended_skills: result.recommended_skills ?? [],
                  analysis_hints:     result.attributes?.symptom,
                })
                setChatMessages(prev => [...prev, {
                  role: 'agent',
                  content: `🔍 事件分類：**${result.event_type}** (${urgency.toUpperCase()})`,
                }])
              }

              delete pendingInputs[tool_name]
            }

            // ── report ─────────────────────────────────────────────────────
            else if (currentEvent === 'report') {
              const { content, total_turns } = payload
              setReport(content ?? '')
              setChatMessages(prev => [...prev, {
                role: 'agent',
                content: `✅ 診斷完成（${total_turns ?? '?'} 回合），請查看左側報告。`,
              }])
            }

            // ── error ──────────────────────────────────────────────────────
            else if (currentEvent === 'error') {
              const msg = payload.message || '發生未知錯誤'
              setError(msg)
              setChatMessages(prev => [...prev, {
                role: 'agent',
                content: `❌ 錯誤：${msg}`,
              }])
            }

            // ── done ───────────────────────────────────────────────────────
            // nothing to do, streaming flag cleared in finally

            currentEvent = null
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        const msg = err.message || '網路錯誤'
        setError(msg)
        setChatMessages(prev => [...prev, {
          role: 'agent',
          content: `❌ 錯誤：${msg}`,
        }])
      }
    } finally {
      setIsStreaming(false)
    }
  }, [reset])

  const stop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  return {
    isStreaming,
    eventObject,
    toolCalls,
    report,
    chatMessages,
    error,
    sendMessage,
    stop,
    setChatMessages,
  }
}
