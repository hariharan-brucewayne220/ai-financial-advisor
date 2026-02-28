/**
 * Document Upload Component
 *
 * Professional UI for uploading portfolio documents (PDF, Excel, CSV)
 * Shows upload progress and document list.
 */

import React, { useState, useRef, useEffect } from 'react'
import { Upload, File, Trash2, CheckCircle, Clock, AlertCircle } from 'lucide-react'
import { getApiBase } from '@/lib/api'
import { getAuthHeaders } from '@/lib/auth'

interface Document {
  document_id: string
  file_name: string
  status: 'pending' | 'processing' | 'indexed' | 'error'
  uploaded_at?: string
  chunk_count?: number
  pii_detected?: boolean
  error_message?: string | null
}

interface DocumentUploadProps {
  clientId: string
}

const DocumentUpload: React.FC<DocumentUploadProps> = ({ clientId }) => {
  const [documents, setDocuments] = useState<Document[]>([])
  const [uploading, setUploading] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const apiBase = getApiBase()

  const loadDocuments = async () => {
    if (!clientId) return
    try {
      const res = await fetch(`${apiBase}/documents/${clientId}`, {
        headers: getAuthHeaders(),
      })
      if (!res.ok) return
      const data = await res.json()
      setDocuments(
        (data || []).map((d: any) => ({
          document_id: d.id || d.document_id,
          file_name: d.file_name,
          status: d.status,
          chunk_count: d.chunk_count,
          pii_detected: d.pii_detected,
          error_message: d.error_message,
        }))
      )
    } catch {
      // ignore
    }
  }

  const refreshDocumentStatus = async (docId: string) => {
    try {
      const res = await fetch(
        `${apiBase}/documents/${clientId}/${docId}/status`,
        { headers: getAuthHeaders() }
      )
      if (!res.ok) return
      const data = await res.json()
      setDocuments((prev) =>
        prev.map((d) =>
          d.document_id === docId
            ? {
                ...d,
                status: data.status,
                chunk_count: data.chunk_count,
                pii_detected: data.pii_detected,
                error_message: data.error_message,
              }
            : d
        )
      )
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    loadDocuments()
  }, [clientId])

  useEffect(() => {
    const pending = documents.filter(
      (d) => d.status === 'pending' || d.status === 'processing'
    )
    if (pending.length === 0) return
    const interval = setInterval(() => {
      pending.forEach((d) => refreshDocumentStatus(d.document_id))
    }, 2000)
    return () => clearInterval(interval)
  }, [documents])

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true)
    } else if (e.type === 'dragleave') {
      setDragActive(false)
    }
  }

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleFile(e.dataTransfer.files[0])
    }
  }

  const handleFile = async (file: File) => {
    // Validate file type
    const validTypes = [
      'application/pdf',
      'text/csv',
      'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      'text/plain',
      'image/jpeg',
      'image/png',
      'image/gif',
      'image/webp',
    ]
    const validExts = ['pdf', 'csv', 'xlsx', 'txt', 'jpg', 'jpeg', 'png', 'gif', 'webp']
    const fileExt = file.name.split('.').pop()?.toLowerCase()

    if (!validTypes.includes(file.type) && !validExts.includes(fileExt || '')) {
      alert('Please upload a PDF, CSV, Excel, TXT, or image file (JPG, PNG, GIF)')
      return
    }

    // Validate file size (max 10MB)
    if (file.size > 10 * 1024 * 1024) {
      alert('File size must be less than 10MB')
      return
    }

    setUploading(true)

    try {
      const formData = new FormData()
      formData.append('file', file)

      const response = await fetch(`${apiBase}/documents/${clientId}/upload`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: formData,
      })

      if (!response.ok) {
        throw new Error('Upload failed')
      }

      const data = await response.json()
      setDocuments([...documents, {
        document_id: data.document_id,
        file_name: data.file_name,
        status: data.status,
      }])

      refreshDocumentStatus(data.document_id)

      // Reset input
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
    } catch (error) {
      console.error('Upload error:', error)
      alert('Failed to upload document')
    } finally {
      setUploading(false)
    }
  }

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      handleFile(e.target.files[0])
    }
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'indexed':
        return <CheckCircle className="w-5 h-5 text-green-600" />
      case 'pending':
      case 'processing':
        return <Clock className="w-5 h-5 text-blue-600 animate-spin" />
      case 'error':
        return <AlertCircle className="w-5 h-5 text-red-600" />
      default:
        return <File className="w-5 h-5 text-slate-400" />
    }
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'indexed':
        return 'bg-green-50 border-green-200'
      case 'pending':
      case 'processing':
        return 'bg-blue-50 border-blue-200'
      case 'error':
        return 'bg-red-50 border-red-200'
      default:
        return 'bg-slate-50 border-slate-200'
    }
  }

  const getStatusText = (status: string) => {
    switch (status) {
      case 'indexed':
        return 'Ready'
      case 'pending':
        return 'Uploading...'
      case 'processing':
        return 'Processing...'
      case 'error':
        return 'Error'
      default:
        return 'Unknown'
    }
  }

  return (
    <div className="space-y-6">
      {/* Upload Area */}
      <div
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-all ${
          dragActive
            ? 'border-blue-500 bg-blue-50'
            : 'border-slate-300 bg-white hover:border-blue-400'
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          onChange={handleFileInput}
          disabled={uploading}
          className="hidden"
          accept=".pdf,.csv,.xlsx,.txt,.jpg,.jpeg,.png,.gif,.webp"
        />

        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          className="inline-block"
        >
          <div className="flex flex-col items-center gap-3">
            <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
              <Upload className="w-6 h-6 text-blue-600" />
            </div>
            <div>
              <p className="font-semibold text-slate-900">
                {uploading ? 'Uploading & Processing...' : 'Drag & drop your portfolio documents'}
              </p>
              <p className="text-sm text-slate-600 mt-1">
                PDF, CSV, Excel, TXT, or Images (JPG, PNG, GIF) • Max 10MB
              </p>
              <p className="text-xs text-slate-500 mt-2">
                💡 Screenshot your stock portfolio and gains!
              </p>
            </div>
          </div>
        </button>
      </div>

      {/* Documents List */}
      {documents.length > 0 && (
        <div className="space-y-3">
          <h3 className="font-semibold text-slate-900">Uploaded Documents ({documents.length})</h3>
          <div className="space-y-2">
            {documents.map((doc) => (
              <div
                key={doc.document_id}
                className={`border rounded-lg p-4 flex items-center justify-between ${getStatusColor(doc.status)}`}
              >
                <div className="flex items-center gap-3 flex-1">
                  {getStatusIcon(doc.status)}
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-slate-900 truncate">{doc.file_name}</p>
                    <p className="text-sm text-slate-600">
                      {getStatusText(doc.status)}
                      {doc.chunk_count !== undefined && (
                        <span className="ml-2">• Chunks: {doc.chunk_count}</span>
                      )}
                      {doc.pii_detected !== undefined && (
                        <span className="ml-2">
                          • PII: {doc.pii_detected ? 'Detected' : 'None'}
                        </span>
                      )}
                    </p>
                    {doc.error_message && (
                      <p className="text-xs text-red-600 mt-1">{doc.error_message}</p>
                    )}
                  </div>
                </div>
                <button
                  disabled={doc.status === 'pending' || doc.status === 'processing'}
                  className="ml-3 p-2 hover:bg-red-100 rounded-lg text-red-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Empty State */}
      {documents.length === 0 && !uploading && (
        <div className="text-center py-8 text-slate-500">
          <p className="text-sm">No documents uploaded yet. Start by uploading your portfolio documents.</p>
        </div>
      )}
    </div>
  )
}

export default DocumentUpload
