/**
 * Reports Component
 *
 * Generate and view grounded portfolio reports.
 */

import React, { useEffect, useState } from 'react'
import axios from 'axios'
import { getApiBase } from '@/lib/api'
import { getAuthHeaders } from '@/lib/auth'
import { FileText, RefreshCw, Play, Eye } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

type ReportStatus = 'draft' | 'generating' | 'final' | 'failed'

interface ReportListItem {
  id: string
  report_type: string
  title: string
  status: ReportStatus
  created_at: string
  finalized_at?: string | null
}

interface ReportDetail {
  id: string
  report_type: string
  title: string
  content: string
  content_html: string
  status: ReportStatus
  created_at: string
  finalized_at?: string | null
  metadata?: Record<string, unknown>
}

interface ReportsProps {
  clientId: string
}

const Reports: React.FC<ReportsProps> = ({ clientId }) => {
  const apiBase = getApiBase()
  const [reports, setReports] = useState<ReportListItem[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [selectedReport, setSelectedReport] = useState<ReportDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [activeView, setActiveView] = useState<'markdown' | 'html'>('markdown')
  const [documentCount, setDocumentCount] = useState(0)

  const fetchReports = async () => {
    if (!clientId) return
    setIsLoading(true)
    setError(null)
    try {
      const res = await axios.get(`${apiBase}/reports/${clientId}`, {
        headers: getAuthHeaders(),
      })
      setReports(res.data || [])
    } catch (err) {
      setError('Failed to load reports')
    } finally {
      setIsLoading(false)
    }
  }

  const fetchDocuments = async () => {
    if (!clientId) return
    try {
      const res = await axios.get(`${apiBase}/documents/${clientId}`, {
        headers: getAuthHeaders(),
      })
      setDocumentCount((res.data || []).length)
    } catch {
      setDocumentCount(0)
    }
  }

  const generateReport = async (reportType: string) => {
    if (!clientId) return
    setError(null)
    try {
      await axios.post(
        `${apiBase}/reports/${clientId}/generate?report_type=${encodeURIComponent(
          reportType
        )}`,
        {},
        { headers: getAuthHeaders() }
      )
      await fetchReports()
    } catch (err) {
      setError('Failed to start report generation')
    }
  }

  const viewReport = async (reportId: string) => {
    setError(null)
    try {
      const res = await axios.get(`${apiBase}/reports/${clientId}/${reportId}`, {
        headers: getAuthHeaders(),
      })
      setSelectedReport(res.data)
    } catch (err) {
      setError('Failed to load report')
    }
  }

  useEffect(() => {
    fetchReports()
    fetchDocuments()
  }, [clientId])

  return (
    <div className="flex flex-col h-full bg-gradient-to-br from-slate-50 to-slate-100 overflow-auto">
      {/* Header */}
      <div className="border-b border-slate-200 px-6 py-4 bg-white shadow-sm">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Reports</h1>
            <p className="text-sm text-slate-600 mt-1">
              Generate grounded portfolio reports from uploaded documents
            </p>
          </div>
          <button
            onClick={fetchReports}
            className="inline-flex items-center gap-2 px-3 py-2 text-sm bg-slate-100 rounded-lg hover:bg-slate-200 transition-colors"
          >
            <RefreshCw size={16} />
            Refresh
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto p-6 space-y-6">
        {/* Actions */}
        <div className="bg-white rounded-lg p-4 border border-slate-200 shadow-sm">
          <div className="flex items-center gap-3">
            <FileText className="text-blue-600" size={20} />
            <div className="flex-1">
              <p className="font-medium text-slate-900">Portfolio Summary</p>
              <p className="text-sm text-slate-600">
                Grounded summary based on uploaded documents
              </p>
            </div>
            <button
              onClick={() => generateReport('portfolio_summary')}
              disabled={documentCount === 0}
              className="inline-flex items-center gap-2 px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
            >
              <Play size={16} />
              Generate
            </button>
          </div>
          {documentCount === 0 && (
            <div className="mt-3 text-xs text-slate-600">
              Upload at least one document before generating a report.
            </div>
          )}
        </div>

        {/* Errors */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Report List */}
        <div className="bg-white rounded-lg border border-slate-200 shadow-sm">
          <div className="px-4 py-3 border-b border-slate-200 font-semibold text-slate-900">
            Report History
          </div>
          <div className="divide-y divide-slate-200">
            {isLoading ? (
              <div className="p-4 text-slate-600">Loading...</div>
            ) : reports.length === 0 ? (
              <div className="p-4 text-slate-600">No reports yet.</div>
            ) : (
              reports.map((r) => (
                <div key={r.id} className="p-4 flex items-center gap-4">
                  <div className="flex-1">
                    <div className="font-medium text-slate-900">{r.title}</div>
                    <div className="text-xs text-slate-500">
                      {r.report_type} • {new Date(r.created_at).toLocaleString()}
                    </div>
                  </div>
                  <span
                    className={`text-xs px-2 py-1 rounded-full ${
                      r.status === 'final'
                        ? 'bg-green-100 text-green-800'
                        : r.status === 'failed'
                        ? 'bg-red-100 text-red-800'
                        : 'bg-blue-100 text-blue-800'
                    }`}
                  >
                    {r.status}
                  </span>
                  <button
                    onClick={() => viewReport(r.id)}
                    className="inline-flex items-center gap-2 px-3 py-2 text-sm bg-slate-100 rounded-lg hover:bg-slate-200 transition-colors"
                  >
                    <Eye size={16} />
                    View
                  </button>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Report Viewer */}
        {selectedReport && (
          <div className="bg-white rounded-lg border border-slate-200 shadow-sm">
            <div className="px-4 py-3 border-b border-slate-200 flex items-center justify-between">
              <div>
                <div className="font-semibold text-slate-900">{selectedReport.title}</div>
                <div className="text-xs text-slate-500">
                  {selectedReport.report_type} •{' '}
                  {new Date(selectedReport.created_at).toLocaleString()}
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setActiveView('markdown')}
                  className={`px-3 py-1 text-xs rounded-lg ${
                    activeView === 'markdown'
                      ? 'bg-blue-600 text-white'
                      : 'bg-slate-100 text-slate-700'
                  }`}
                >
                  Markdown
                </button>
                <button
                  onClick={() => setActiveView('html')}
                  className={`px-3 py-1 text-xs rounded-lg ${
                    activeView === 'html'
                      ? 'bg-blue-600 text-white'
                      : 'bg-slate-100 text-slate-700'
                  }`}
                >
                  HTML
                </button>
              </div>
            </div>
            <div className="p-4">
              {activeView === 'markdown' ? (
                <div className="prose prose-sm max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {selectedReport.content || ''}
                  </ReactMarkdown>
                </div>
              ) : (
                <div
                  className="prose prose-sm max-w-none"
                  dangerouslySetInnerHTML={{ __html: selectedReport.content_html }}
                />
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default Reports
