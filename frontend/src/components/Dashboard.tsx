/**
 * Dashboard Component - Main App Container
 *
 * Professional financial advisor interface with sidebar and chat.
 */

import React, { useState, useEffect } from 'react'
import axios from 'axios'
import ChatInterface from './Chat/ChatInterface'
import DocumentUpload from './DocumentUpload'
import { Menu, LogOut, Settings, MessageSquare, FileUp, FileText } from 'lucide-react'
import { getApiBase } from '@/lib/api'
import { ensureAuth } from '@/lib/auth'
import Reports from './Reports'

interface DashboardProps {}

const Dashboard: React.FC<DashboardProps> = () => {
  const [isLoggedIn, setIsLoggedIn] = useState(true)
  const [clientId, setClientId] = useState<string>('')
  const [conversationId, setConversationId] = useState<string>('')
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [activeTab, setActiveTab] = useState<'chat' | 'upload' | 'reports'>('chat')
  const [isInitializing, setIsInitializing] = useState(true)
  const [healthFull, setHealthFull] = useState<{
    status: 'healthy' | 'degraded'
    database: boolean
    redis: boolean
  } | null>(null)
  const [marketHealth, setMarketHealth] = useState<{
    status: 'healthy' | 'degraded'
    market_data: { available: boolean; mode?: string; reason?: string }
  } | null>(null)
  const apiBase = getApiBase()

  // Initialize client and conversation on mount
  useEffect(() => {
    const initializeSession = async () => {
      try {
        await ensureAuth()

        const storedClientId = localStorage.getItem('gs_client_id')
        const storedConvId = localStorage.getItem('gs_conversation_id')
        if (storedClientId && storedConvId) {
          setClientId(storedClientId)
          setConversationId(storedConvId)
          setIsInitializing(false)
          return
        }

        // Create client
        const clientRes = await axios.post(`${apiBase}/clients`, {
          name: 'Demo Financial Advisor Session'
        })
        const newClientId = clientRes.data.id
        setClientId(newClientId)

        // Create conversation
        const convRes = await axios.post(
          `${apiBase}/conversations/${newClientId}/conversations`,
          { title: 'Portfolio Analysis' }
        )
        const newConvId = convRes.data.id
        setConversationId(newConvId)
        localStorage.setItem('gs_client_id', newClientId)
        localStorage.setItem('gs_conversation_id', newConvId)

        setIsInitializing(false)
      } catch (error) {
        console.error('Failed to initialize session:', error)
        setIsInitializing(false)
      }
    }

    initializeSession()
  }, [apiBase])

  useEffect(() => {
    let isMounted = true
    const fetchHealth = async () => {
      try {
        const [fullRes, marketRes] = await Promise.all([
          axios.get(`${apiBase}/health/full`),
          axios.get(`${apiBase}/health/market-data`)
        ])
        if (!isMounted) return
        setHealthFull(fullRes.data)
        setMarketHealth(marketRes.data)
      } catch (error) {
        if (!isMounted) return
        setHealthFull(null)
        setMarketHealth(null)
      }
    }
    fetchHealth()
    const interval = window.setInterval(fetchHealth, 30000)
    return () => {
      isMounted = false
      window.clearInterval(interval)
    }
  }, [apiBase])

  if (!isLoggedIn) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-gradient-to-br from-slate-900 via-blue-900 to-slate-900">
        <div className="text-center max-w-md mx-auto px-6">
          <div className="mb-8">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-blue-500/20 border border-blue-400/30">
              <span className="text-2xl">💼</span>
            </div>
          </div>
          <h1 className="text-4xl font-bold mb-2 text-white">AI Financial Advisor</h1>
          <p className="text-blue-200 mb-8 leading-relaxed">
            Advanced RAG + LangGraph for intelligent portfolio analysis and financial guidance
          </p>
          <button
            onClick={() => setIsLoggedIn(true)}
            className="w-full px-6 py-3 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-700 hover:to-blue-800 font-medium transition-all transform hover:scale-105 active:scale-95"
          >
            Enter Dashboard
          </button>
          <p className="text-sm text-slate-400 mt-6">
            Demo account • No login required
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-screen bg-slate-50">
      {/* Sidebar */}
      <div className={`${sidebarOpen ? 'w-64' : 'w-20'} bg-gradient-to-b from-slate-900 to-slate-800 text-white transition-all duration-300 flex flex-col border-r border-slate-700`}>
        {/* Logo */}
        <div className="p-4 border-b border-slate-700">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-blue-400 to-blue-600 flex items-center justify-center flex-shrink-0">
              <span className="text-lg">💼</span>
            </div>
            {sidebarOpen && <h1 className="font-bold text-lg">Ayco AI</h1>}
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-4 space-y-2">
          <button
            onClick={() => setActiveTab('chat')}
            className={`w-full p-3 rounded-lg font-medium transition-all flex items-center gap-3 ${
              activeTab === 'chat'
                ? 'bg-blue-500/20 border border-blue-400/30 text-blue-100'
                : 'hover:bg-slate-700/50 text-slate-300'
            }`}
          >
            <MessageSquare size={20} />
            {sidebarOpen && <span>Chat</span>}
          </button>
          <button
            onClick={() => setActiveTab('upload')}
            className={`w-full p-3 rounded-lg font-medium transition-all flex items-center gap-3 ${
              activeTab === 'upload'
                ? 'bg-blue-500/20 border border-blue-400/30 text-blue-100'
                : 'hover:bg-slate-700/50 text-slate-300'
            }`}
          >
            <FileUp size={20} />
            {sidebarOpen && <span>Documents</span>}
          </button>
          <button
            onClick={() => setActiveTab('reports')}
            className={`w-full p-3 rounded-lg font-medium transition-all flex items-center gap-3 ${
              activeTab === 'reports'
                ? 'bg-blue-500/20 border border-blue-400/30 text-blue-100'
                : 'hover:bg-slate-700/50 text-slate-300'
            }`}
          >
            <FileText size={20} />
            {sidebarOpen && <span>Reports</span>}
          </button>
        </nav>

        {/* Footer */}
        <div className="p-4 border-t border-slate-700 space-y-2">
          <button className="w-full flex items-center gap-3 p-2 rounded-lg hover:bg-slate-700/50 transition-colors text-sm">
            <Settings size={20} />
            {sidebarOpen && <span>Settings</span>}
          </button>
          <button
            onClick={() => {
              localStorage.removeItem('gs_client_id')
              localStorage.removeItem('gs_conversation_id')
              setIsLoggedIn(false)
            }}
            className="w-full flex items-center gap-3 p-2 rounded-lg hover:bg-red-500/20 text-red-300 transition-colors text-sm"
          >
            <LogOut size={20} />
            {sidebarOpen && <span>Logout</span>}
          </button>
        </div>

        {/* Toggle */}
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="p-4 hover:bg-slate-700/50 transition-colors border-t border-slate-700"
        >
          <Menu size={20} />
        </button>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-6 py-2 bg-white border-b border-slate-200 text-xs text-slate-600">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span
                className={`inline-block h-2 w-2 rounded-full ${
                  healthFull?.status === 'healthy'
                    ? 'bg-emerald-500'
                    : healthFull?.status === 'degraded'
                    ? 'bg-amber-500'
                    : 'bg-slate-300'
                }`}
              ></span>
              <span>
                System {healthFull ? (healthFull.status === 'healthy' ? 'Healthy' : 'Degraded') : 'Unknown'}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span
                className={`inline-block h-2 w-2 rounded-full ${
                  marketHealth?.market_data?.available
                    ? 'bg-emerald-500'
                    : marketHealth?.status === 'degraded'
                    ? 'bg-amber-500'
                    : 'bg-slate-300'
                }`}
              ></span>
              <span>
                Market Data{' '}
                {marketHealth
                  ? marketHealth.market_data?.available
                    ? `Healthy (${marketHealth.market_data?.mode ?? 'unknown'})`
                    : `Degraded (${marketHealth.market_data?.reason ?? 'unavailable'})`
                  : 'Unknown'}
              </span>
            </div>
          </div>
          <div className="text-slate-400">
            {healthFull ? `DB: ${healthFull.database ? 'OK' : 'Down'} • Redis: ${healthFull.redis ? 'OK' : 'Down'}` : ''}
          </div>
        </div>
        {isInitializing ? (
          <div className="flex items-center justify-center h-full bg-gradient-to-br from-slate-50 to-slate-100">
            <div className="text-center">
              <div className="animate-spin mb-4 inline-block">
                <div className="w-8 h-8 border-4 border-blue-500 border-t-transparent rounded-full"></div>
              </div>
              <p className="text-slate-600">Initializing your session...</p>
            </div>
          </div>
        ) : activeTab === 'chat' ? (
          <ChatInterface clientId={clientId} conversationId={conversationId} />
        ) : activeTab === 'upload' ? (
          <div className="flex flex-col h-full bg-gradient-to-br from-slate-50 to-slate-100 overflow-auto">
            {/* Header */}
            <div className="border-b border-slate-200 px-6 py-4 bg-white shadow-sm">
              <h1 className="text-2xl font-bold text-slate-900">Portfolio Documents</h1>
              <p className="text-sm text-slate-600 mt-1">Upload and manage your financial documents for AI analysis</p>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-auto p-6">
              <div className="max-w-4xl">
                <DocumentUpload clientId={clientId} />
              </div>
            </div>
          </div>
        ) : (
          <Reports clientId={clientId} />
        )}
      </div>
    </div>
  )
}

export default Dashboard
