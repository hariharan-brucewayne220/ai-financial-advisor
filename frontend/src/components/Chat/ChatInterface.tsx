/**
 * ChatInterface Component
 *
 * Professional chat UI with streaming, sources, and agent progress.
 */

import React, { useRef, useEffect } from 'react'
import { useChat } from '@/hooks/useChat'
import ChatMessage from './ChatMessage'
import SourcesCitations from './SourcesCitations'
import FaithfulnessScore from './FaithfulnessScore'
import AgentProgressTracker from './AgentProgressTracker'
import { Send, AlertCircle } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface ChatInterfaceProps {
  clientId: string
  conversationId: string
}

const ChatInterface: React.FC<ChatInterfaceProps> = ({ clientId, conversationId }) => {
  const {
    messages,
    isStreaming,
    currentStep,
    streamingResponse,
    faithfulness,
    error,
    sendMessage,
    stopStreaming,
  } = useChat(clientId, conversationId)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [inputValue, setInputValue] = React.useState('')

  // Auto-scroll to latest message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingResponse])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!inputValue.trim() || isStreaming) return

    await sendMessage(inputValue)
    setInputValue('')
    inputRef.current?.focus()
  }

  return (
    <div className="flex flex-col h-full bg-gradient-to-br from-slate-50 to-slate-100">
      {/* Header */}
      <div className="border-b border-slate-200 px-6 py-4 bg-white shadow-sm">
        <h1 className="text-2xl font-bold text-slate-900">AI Financial Advisor</h1>
        <p className="text-sm text-slate-600 mt-1">Ask questions about your portfolio, holdings, and financial analysis</p>
      </div>

      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {messages.length === 0 && !isStreaming && (
          <div className="flex items-center justify-center h-full">
            <div className="text-center max-w-md">
              <div className="text-5xl mb-4">📊</div>
              <h2 className="text-xl font-semibold text-slate-900 mb-2">Welcome to AI Financial Advisor</h2>
              <p className="text-slate-600 mb-6">
                Ask any questions about your portfolio, investment strategy, or financial planning. I'll analyze your data using advanced RAG technology.
              </p>
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-left text-sm text-slate-700">
                <p className="font-medium text-blue-900 mb-2">Try asking:</p>
                <ul className="space-y-1 text-blue-800">
                  <li>• What's my portfolio allocation?</li>
                  <li>• What's my risk profile?</li>
                  <li>• How should I rebalance my portfolio?</li>
                </ul>
              </div>
            </div>
          </div>
        )}

        {/* Render message history */}
        {messages.map((message, idx) => (
          <div key={idx} className="animate-fadeIn">
            <ChatMessage message={message} />
            {message.role === 'assistant' && message.sources && (
              <div className="mt-3 space-y-2">
                <SourcesCitations sources={message.sources} />
                {message.faithfulness !== undefined && (
                  <FaithfulnessScore score={message.faithfulness} />
                )}
              </div>
            )}
          </div>
        ))}

        {/* Streaming response */}
        {isStreaming && (
          <div className="space-y-4">
            {/* Agent progress tracker */}
            <AgentProgressTracker currentStep={currentStep} />

            {/* Streaming response preview */}
            {streamingResponse && (
              <div className="bg-white rounded-lg p-4 border border-slate-200 shadow-sm">
                <div className="prose prose-sm max-w-none text-slate-700">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {streamingResponse}
                  </ReactMarkdown>
                  <span className="animate-pulse ml-1 inline-block">▊</span>
                </div>
                <div className="mt-4 flex justify-between items-center pt-4 border-t border-slate-200">
                  <FaithfulnessScore score={faithfulness} showLabel={true} />
                  <button
                    onClick={stopStreaming}
                    className="px-4 py-2 text-sm bg-red-100 text-red-700 rounded-lg hover:bg-red-200 transition-colors font-medium"
                  >
                    Stop
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Error display */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex gap-3">
            <AlertCircle className="text-red-600 flex-shrink-0 w-5 h-5 mt-0.5" />
            <div>
              <p className="font-semibold text-red-900">Error</p>
              <p className="text-sm text-red-700 mt-1">{error}</p>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="border-t border-slate-200 bg-white p-4">
        <form onSubmit={handleSubmit} className="flex gap-3 max-w-4xl">
          <input
            ref={inputRef}
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Ask about your portfolio, risk analysis, rebalancing strategies..."
            disabled={isStreaming}
            className="flex-1 px-4 py-3 border border-slate-300 rounded-lg focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:bg-slate-50 disabled:text-slate-500 transition-all"
          />
          <button
            type="submit"
            disabled={isStreaming || !inputValue.trim()}
            className="px-6 py-3 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-700 hover:to-blue-800 disabled:from-slate-400 disabled:to-slate-400 font-medium transition-all flex items-center gap-2 disabled:cursor-not-allowed"
          >
            <Send size={18} />
            <span className="hidden sm:inline">{isStreaming ? 'Analyzing...' : 'Send'}</span>
          </button>
        </form>
        <p className="text-xs text-slate-500 mt-2 text-center">Powered by advanced RAG + LLM technology</p>
      </div>
    </div>
  )
}

export default ChatInterface
