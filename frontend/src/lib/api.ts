/**
 * API Client
 *
 * Central place for the backend base URL and a pre-configured axios
 * instance that carries the JWT bearer header. Typed helpers mirror the
 * FastAPI routers in `backend/app/api/*`.
 *
 * **Why a shared instance?**
 * - One base URL (`VITE_API_BASE_URL`, default `/api` behind the Vite/Nginx proxy)
 * - Bearer token applied once via `setAuthToken` instead of on every call
 * - Components that stream via `EventSource` or upload via `fetch` still use
 *   `getApiBase()` + `getAuthHeaders()` from `@/lib/auth`
 */

/// <reference types="vite/client" />

import axios, { AxiosInstance } from 'axios'

// ============================================================================
// BASE URL
// ============================================================================

const DEFAULT_API_BASE = '/api'

/**
 * Resolve the API base URL (no trailing slash).
 *
 * docker-compose sets `VITE_API_BASE_URL=/api`; Vite (dev) and Nginx (prod)
 * both proxy `/api` to the FastAPI backend.
 */
export function getApiBase(): string {
  const configured = import.meta.env.VITE_API_BASE_URL as string | undefined
  const base = (configured && configured.trim()) || DEFAULT_API_BASE
  return base.replace(/\/+$/, '')
}

// ============================================================================
// AXIOS INSTANCE
// ============================================================================

export const api: AxiosInstance = axios.create({
  baseURL: getApiBase(),
  headers: { 'Content-Type': 'application/json' },
})

/**
 * Apply (or clear) the JWT bearer header.
 *
 * Also sets the global axios default because some components call `axios`
 * directly (e.g. Dashboard session bootstrap and health polling).
 */
export function setAuthToken(token: string | null): void {
  if (token) {
    const value = `Bearer ${token}`
    api.defaults.headers.common['Authorization'] = value
    axios.defaults.headers.common['Authorization'] = value
  } else {
    delete api.defaults.headers.common['Authorization']
    delete axios.defaults.headers.common['Authorization']
  }
}

// ============================================================================
// TYPES (match backend/app/api/* response shapes)
// ============================================================================

export interface AuthResponse {
  access_token: string
  refresh_token: string
  token_type: string
  advisor_id: string
  advisor_email: string
}

export interface ClientCreate {
  name: string
  email?: string | null
  risk_profile?: string // low, moderate, high, aggressive
  portfolio_value?: number | null
}

export interface ClientResponse {
  id: string
  name: string
  email: string | null
  risk_profile: string
  portfolio_value: number | null
  created_at: string
}

export interface ConversationResponse {
  id: string
  title: string
  created_at: string
  updated_at: string
  messages: Array<{
    id?: string
    role: 'user' | 'assistant'
    content: string
    created_at?: string
  }>
}

export type DocumentStatus = 'pending' | 'processing' | 'indexed' | 'error'

export interface DocumentListItem {
  id: string
  file_name: string
  file_type: string
  status: DocumentStatus
  chunk_count?: number
  pii_detected?: boolean
  created_at: string
  error_message?: string | null
}

export interface DocumentUploadResponse {
  document_id: string
  file_name: string
  status: DocumentStatus
}

export interface DocumentStatusResponse {
  status: DocumentStatus
  chunk_count?: number
  pii_detected?: boolean
  error_message?: string | null
}

export type ReportStatus = 'draft' | 'generating' | 'final' | 'failed'

export interface ReportListItem {
  id: string
  report_type: string
  title: string
  status: ReportStatus
  created_at: string
  finalized_at?: string | null
}

export interface ReportDetail extends ReportListItem {
  content: string
  content_html: string
  metadata?: Record<string, unknown>
}

export interface HealthFull {
  status: 'healthy' | 'degraded'
  database: boolean
  redis: boolean
}

export interface HealthMarketData {
  status: 'healthy' | 'degraded'
  market_data: { available: boolean; mode?: string; reason?: string }
}

// ============================================================================
// AUTH  (POST /api/auth/*)
// ============================================================================

export async function loginAdvisor(email: string, password: string): Promise<AuthResponse> {
  const res = await api.post<AuthResponse>('/auth/login', { email, password })
  return res.data
}

export async function registerAdvisor(
  email: string,
  password: string,
  fullName: string
): Promise<AuthResponse> {
  const res = await api.post<AuthResponse>('/auth/register', {
    email,
    password,
    full_name: fullName,
  })
  return res.data
}

// ============================================================================
// CLIENTS  (/api/clients)
// ============================================================================

export async function createClient(data: ClientCreate): Promise<ClientResponse> {
  const res = await api.post<ClientResponse>('/clients', data)
  return res.data
}

export async function listClients(): Promise<ClientResponse[]> {
  const res = await api.get<ClientResponse[]>('/clients')
  return res.data
}

// ============================================================================
// CONVERSATIONS  (/api/conversations/{client}/conversations[/{id}])
// SSE streaming is done with EventSource in hooks/useChat.ts.
// ============================================================================

export async function createConversation(
  clientId: string,
  title: string
): Promise<ConversationResponse> {
  const res = await api.post<ConversationResponse>(
    `/conversations/${clientId}/conversations`,
    { title }
  )
  return res.data
}

export async function getConversation(
  clientId: string,
  conversationId: string
): Promise<ConversationResponse> {
  const res = await api.get<ConversationResponse>(
    `/conversations/${clientId}/conversations/${conversationId}`
  )
  return res.data
}

// ============================================================================
// DOCUMENTS  (/api/documents/{client}[/upload | /{doc}/status])
// ============================================================================

export async function listDocuments(clientId: string): Promise<DocumentListItem[]> {
  const res = await api.get<DocumentListItem[]>(`/documents/${clientId}`)
  return res.data
}

export async function uploadDocument(
  clientId: string,
  file: File
): Promise<DocumentUploadResponse> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await api.post<DocumentUploadResponse>(
    `/documents/${clientId}/upload`,
    formData,
    // Let the browser set the multipart boundary
    { headers: { 'Content-Type': undefined } }
  )
  return res.data
}

export async function getDocumentStatus(
  clientId: string,
  documentId: string
): Promise<DocumentStatusResponse> {
  const res = await api.get<DocumentStatusResponse>(
    `/documents/${clientId}/${documentId}/status`
  )
  return res.data
}

export async function deleteDocument(clientId: string, documentId: string): Promise<void> {
  await api.delete(`/documents/${clientId}/${documentId}`)
}

// ============================================================================
// REPORTS  (/api/reports/{client}[/generate | /{id}])
// ============================================================================

export async function listReports(clientId: string): Promise<ReportListItem[]> {
  const res = await api.get<ReportListItem[]>(`/reports/${clientId}`)
  return res.data
}

export async function generateReport(
  clientId: string,
  reportType: string = 'portfolio_summary'
): Promise<unknown> {
  const res = await api.post(`/reports/${clientId}/generate`, {}, {
    params: { report_type: reportType },
  })
  return res.data
}

export async function getReport(clientId: string, reportId: string): Promise<ReportDetail> {
  const res = await api.get<ReportDetail>(`/reports/${clientId}/${reportId}`)
  return res.data
}

// ============================================================================
// HEALTH  (/api/health/*)
// ============================================================================

export async function getHealthFull(): Promise<HealthFull> {
  const res = await api.get<HealthFull>('/health/full')
  return res.data
}

export async function getHealthMarketData(): Promise<HealthMarketData> {
  const res = await api.get<HealthMarketData>('/health/market-data')
  return res.data
}
