/**
 * useChat Hook - Manage SSE streaming conversation
 *
 * **Why EventSource?**
 * - Native browser API for server-sent events
 * - One-way stream from server (perfect for agent updates)
 * - Auto-reconnects on disconnect
 * - Simpler than WebSockets for unidirectional data
 *
 * **State Machine:**
 * idle → sending → streaming → done
 *
 * **Events:**
 * - step: {step: "classify|retrieve|rerank|compress|generate|score"}
 * - token: {token: "word "} (incremental generation)
 * - sources: {sources: ["chunk-id-1", "chunk-id-2"]}
 * - faithfulness: {score: 0.85}
 * - error: {error: "message"}
 * - done: {status: "complete"}
 */

import { useState, useCallback, useRef, useEffect } from 'react'
import axios from 'axios'
import { getApiBase } from '@/lib/api'
import { getAuthHeaders, getAuthQueryParam } from '@/lib/auth'

export interface ChatMessage {
  id?: string
  role: 'user' | 'assistant'
  content: string
  sources?: string[]
  faithfulness?: number
  createdAt?: string
}

export interface UseChartState {
  messages: ChatMessage[]
  isLoading: boolean
  isStreaming: boolean
  currentStep: string
  streamingResponse: string
  sources: string[]
  faithfulness: number
  error: string | null
}

export interface UseChartActions {
  sendMessage: (content: string) => Promise<void>
  clearMessages: () => void
  stopStreaming: () => void
}

const API_BASE = getApiBase()

/**
 * useChat Hook
 *
 * Manages conversation state and SSE streaming.
 *
 * Usage:
 * ```tsx
 * const { messages, sendMessage, isStreaming } = useChat(conversationId)
 *
 * <button onClick={() => sendMessage("What's our allocation?")} disabled={isStreaming}>
 *   Send
 * </button>
 * ```
 */
export function useChat(clientId: string, conversationId: string) {
  const [state, setState] = useState<UseChartState>({
    messages: [],
    isLoading: false,
    isStreaming: false,
    currentStep: '',
    streamingResponse: '',
    sources: [],
    faithfulness: 0,
    error: null,
  })

  const eventSourceRef = useRef<EventSource | null>(null)

  // Load conversation messages on mount
  useEffect(() => {
    const loadMessages = async () => {
      if (!clientId || !conversationId) return
      try {
        const response = await axios.get(
          `${API_BASE}/conversations/${clientId}/conversations/${conversationId}`,
          { headers: getAuthHeaders() }
        )
        setState(prev => ({
          ...prev,
          messages: response.data.messages || [],
        }))
      } catch (error) {
        console.error('Failed to load conversation:', error)
      }
    }

    loadMessages()
  }, [clientId, conversationId])

  // Send message and stream response
  const sendMessage = useCallback(
    async (content: string) => {
      if (!content.trim() || state.isStreaming) return

      // Add user message immediately
      const userMessage: ChatMessage = {
        role: 'user',
        content,
      }

      setState(prev => ({
        ...prev,
        messages: [...prev.messages, userMessage],
        isLoading: true,
        isStreaming: true,
        streamingResponse: '',
        error: null,
      }))

      try {
        if (!clientId || !conversationId) {
          throw new Error('Missing client or conversation id')
        }
        // Open SSE connection
        const url = `${API_BASE}/conversations/${clientId}/conversations/${conversationId}/messages`

        // Use EventSource for SSE streaming
        const tokenParam = getAuthQueryParam()
        const queryPrefix = tokenParam ? `${tokenParam}&` : ''
        const eventSource = new EventSource(
          `${url}?${queryPrefix}query=${encodeURIComponent(content)}`
        )
        eventSourceRef.current = eventSource

        let fullResponse = ''
        let agentSources: string[] = []
        let agentFaithfulness = 0

        // Handle step events (agent progress)
        eventSource.addEventListener('step', (event) => {
          const data = JSON.parse(event.data)
          setState(prev => ({
            ...prev,
            currentStep: data.step,
          }))
        })

        // Handle token events (streaming response)
        eventSource.addEventListener('token', (event) => {
          const data = JSON.parse(event.data)
          fullResponse += data.token
          setState(prev => ({
            ...prev,
            streamingResponse: fullResponse,
          }))
        })

        // Handle sources event
        eventSource.addEventListener('sources', (event) => {
          const data = JSON.parse(event.data)
          agentSources = data.sources || []
        })

        // Handle faithfulness score
        eventSource.addEventListener('faithfulness', (event) => {
          const data = JSON.parse(event.data)
          agentFaithfulness = data.score || 0
        })

        // Handle done event
        eventSource.addEventListener('done', () => {
          eventSource.close()

          // Add assistant message
          const assistantMessage: ChatMessage = {
            role: 'assistant',
            content: fullResponse,
            sources: agentSources,
            faithfulness: agentFaithfulness,
          }

          setState(prev => ({
            ...prev,
            messages: [...prev.messages, assistantMessage],
            isStreaming: false,
            isLoading: false,
            streamingResponse: '',
          }))
        })

        // Handle errors
        eventSource.addEventListener('error', (event: MessageEvent) => {
          const data = JSON.parse(event.data)
          eventSource.close()

          setState(prev => ({
            ...prev,
            error: data.error || 'An error occurred',
            isStreaming: false,
            isLoading: false,
          }))
        })
      } catch (error) {
        const errorMessage =
          error instanceof Error ? error.message : 'Failed to send message'

        setState(prev => ({
          ...prev,
          error: errorMessage,
          isStreaming: false,
          isLoading: false,
        }))
      }
    },
    [clientId, conversationId, state.isStreaming]
  )

  // Stop streaming
  const stopStreaming = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }

    setState(prev => ({
      ...prev,
      isStreaming: false,
      isLoading: false,
    }))
  }, [])

  // Clear messages
  const clearMessages = useCallback(() => {
    setState(prev => ({
      ...prev,
      messages: [],
      streamingResponse: '',
      error: null,
    }))
  }, [])

  return {
    ...state,
    sendMessage,
    stopStreaming,
    clearMessages,
  } as UseChartState & UseChartActions
}
