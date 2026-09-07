/**
 * Auth helpers - JWT token storage and header builders
 *
 * The backend issues access/refresh JWTs from `POST /api/auth/{register,login}`
 * and accepts the access token either as `Authorization: Bearer <token>` or,
 * for EventSource (which cannot set headers), as a `?token=` query param
 * (see `get_current_advisor` in backend/app/auth.py).
 *
 * **Demo flow:**
 * The dashboard has no login screen ("Demo account - No login required"), so
 * `ensureAuth()` transparently registers/logs in a demo advisor on first load
 * and reuses the stored token afterwards.
 */

import axios from 'axios'
import { AuthResponse, loginAdvisor, registerAdvisor, setAuthToken } from './api'

// ============================================================================
// STORAGE
// ============================================================================

const ACCESS_TOKEN_KEY = 'gs_access_token'
const REFRESH_TOKEN_KEY = 'gs_refresh_token'
const ADVISOR_ID_KEY = 'gs_advisor_id'
const ADVISOR_EMAIL_KEY = 'gs_advisor_email'

// Client/conversation ids created by Dashboard belong to one advisor;
// they must be dropped if we end up authenticated as a different advisor.
const SESSION_KEYS = ['gs_client_id', 'gs_conversation_id']

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_TOKEN_KEY)
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY)
}

export function getAdvisor(): { advisor_id: string; advisor_email: string } | null {
  const advisor_id = localStorage.getItem(ADVISOR_ID_KEY)
  const advisor_email = localStorage.getItem(ADVISOR_EMAIL_KEY)
  return advisor_id && advisor_email ? { advisor_id, advisor_email } : null
}

export function setTokens(auth: AuthResponse): void {
  const previousAdvisor = localStorage.getItem(ADVISOR_ID_KEY)
  if (previousAdvisor && previousAdvisor !== auth.advisor_id) {
    SESSION_KEYS.forEach((key) => localStorage.removeItem(key))
  }
  localStorage.setItem(ACCESS_TOKEN_KEY, auth.access_token)
  localStorage.setItem(REFRESH_TOKEN_KEY, auth.refresh_token)
  localStorage.setItem(ADVISOR_ID_KEY, auth.advisor_id)
  localStorage.setItem(ADVISOR_EMAIL_KEY, auth.advisor_email)
  setAuthToken(auth.access_token)
}

export function clearTokens(): void {
  ;[ACCESS_TOKEN_KEY, REFRESH_TOKEN_KEY, ADVISOR_ID_KEY, ADVISOR_EMAIL_KEY].forEach((key) =>
    localStorage.removeItem(key)
  )
  setAuthToken(null)
}

// ============================================================================
// HEADER / QUERY HELPERS
// ============================================================================

/**
 * `{ Authorization: 'Bearer <token>' }` for fetch/axios, or `{}` when logged out.
 */
export function getAuthHeaders(): Record<string, string> {
  const token = getAccessToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/**
 * `token=<jwt>` for EventSource URLs (no header support), or `''` when logged out.
 */
export function getAuthQueryParam(): string {
  const token = getAccessToken()
  return token ? `token=${encodeURIComponent(token)}` : ''
}

// ============================================================================
// TOKEN INSPECTION
// ============================================================================

/**
 * Read the `exp` claim without verifying the signature (the backend verifies).
 * Returns true if the token is missing, malformed, or expires within 60s.
 */
export function isTokenExpired(token: string | null): boolean {
  if (!token) return true
  try {
    const payload = token.split('.')[1]
    const json = atob(payload.replace(/-/g, '+').replace(/_/g, '/'))
    const { exp } = JSON.parse(json) as { exp?: number }
    if (!exp) return false
    return exp * 1000 <= Date.now() + 60_000
  } catch {
    return true
  }
}

// ============================================================================
// LOGIN / REGISTER / ENSURE
// ============================================================================

export async function login(email: string, password: string): Promise<AuthResponse> {
  const auth = await loginAdvisor(email, password)
  setTokens(auth)
  return auth
}

export async function register(
  email: string,
  password: string,
  fullName: string
): Promise<AuthResponse> {
  const auth = await registerAdvisor(email, password, fullName)
  setTokens(auth)
  return auth
}

export function logout(): void {
  clearTokens()
  SESSION_KEYS.forEach((key) => localStorage.removeItem(key))
}

const DEMO_EMAIL = (import.meta.env.VITE_DEMO_EMAIL as string | undefined) || 'demo@example.com'
const DEMO_PASSWORD =
  (import.meta.env.VITE_DEMO_PASSWORD as string | undefined) || 'demo-password-change-me'
const DEMO_NAME = 'Demo Financial Advisor'

/**
 * Make sure a valid access token is stored and applied to axios.
 *
 * 1. Reuse a stored, unexpired token.
 * 2. Otherwise log in as the demo advisor; if that account does not exist
 *    yet (401), register it (a 409 race means it now exists - log in again).
 */
export async function ensureAuth(): Promise<{ advisor_id: string; advisor_email: string }> {
  const stored = getAccessToken()
  const advisor = getAdvisor()
  if (stored && advisor && !isTokenExpired(stored)) {
    setAuthToken(stored)
    return advisor
  }

  clearTokens()

  try {
    const auth = await login(DEMO_EMAIL, DEMO_PASSWORD)
    return { advisor_id: auth.advisor_id, advisor_email: auth.advisor_email }
  } catch (error) {
    if (!axios.isAxiosError(error) || error.response?.status !== 401) {
      throw error
    }
  }

  try {
    const auth = await register(DEMO_EMAIL, DEMO_PASSWORD, DEMO_NAME)
    return { advisor_id: auth.advisor_id, advisor_email: auth.advisor_email }
  } catch (error) {
    if (axios.isAxiosError(error) && error.response?.status === 409) {
      const auth = await login(DEMO_EMAIL, DEMO_PASSWORD)
      return { advisor_id: auth.advisor_id, advisor_email: auth.advisor_email }
    }
    throw error
  }
}

// Apply any stored token as soon as the module loads so early axios calls
// (e.g. health polling) carry the bearer header.
setAuthToken(isTokenExpired(getAccessToken()) ? null : getAccessToken())
