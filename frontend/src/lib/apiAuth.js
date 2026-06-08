/**
 * API key resolution and auth headers for AstraEdge GUI (Railway / remote API).
 */

export const ASTRAEDGE_API_KEY_STORAGE_KEY = 'ASTRAEDGE_API_KEY'

const PLACEHOLDER_ASTRAEDGE = '%VITE_ASTRAEDGE_API_KEY%'
const PLACEHOLDER_API = '%VITE_API_KEY%'

function normalizeKey(raw) {
  const v = String(raw || '').trim()
  if (!v) return ''
  if (v.includes(PLACEHOLDER_ASTRAEDGE) || v.includes(PLACEHOLDER_API)) return ''
  if (v.startsWith('%VITE_') && v.endsWith('%')) return ''
  return v
}

export function readInjectedViteApiKey(field) {
  if (typeof window === 'undefined') return ''
  const env = window.__ASTRAEDGE_ENV__ || {}
  return normalizeKey(env[field])
}

/** Vite module: import.meta.env; falls back to injected window env. */
export function readViteAstraedgeApiKey() {
  try {
    if (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_ASTRAEDGE_API_KEY) {
      const v = normalizeKey(import.meta.env.VITE_ASTRAEDGE_API_KEY)
      if (v) return v
    }
  } catch (_) { /* ignore */ }
  return readInjectedViteApiKey('VITE_ASTRAEDGE_API_KEY')
}

export function readViteApiKey() {
  try {
    if (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_API_KEY) {
      const v = normalizeKey(import.meta.env.VITE_API_KEY)
      if (v) return v
    }
  } catch (_) { /* ignore */ }
  return readInjectedViteApiKey('VITE_API_KEY')
}

export function getStoredApiKey() {
  try {
    return normalizeKey(localStorage.getItem(ASTRAEDGE_API_KEY_STORAGE_KEY))
  } catch (_) { /* ignore */ }
  return ''
}

/**
 * Priority:
 * 1. localStorage ASTRAEDGE_API_KEY
 * 2. import.meta.env.VITE_ASTRAEDGE_API_KEY (module only)
 * 3. import.meta.env.VITE_API_KEY
 * 4. window.__ASTRAEDGE_ENV__.VITE_ASTRAEDGE_API_KEY
 * 5. window.__ASTRAEDGE_ENV__.VITE_API_KEY
 */
export function resolveApiKey() {
  const stored = getStoredApiKey()
  if (stored) return stored
  const astra = readViteAstraedgeApiKey()
  if (astra) return astra
  const vite = readViteApiKey()
  if (vite) return vite
  const injectedAstra = readInjectedViteApiKey('VITE_ASTRAEDGE_API_KEY')
  if (injectedAstra) return injectedAstra
  const injected = readInjectedViteApiKey('VITE_API_KEY')
  if (injected) return injected
  return ''
}

export function isApiAuthEnabled() {
  return !!resolveApiKey()
}

export function buildAuthHeaders(existing = {}) {
  const headers = { ...(existing || {}) }
  const key = resolveApiKey()
  if (key) {
    headers['X-API-Key'] = key
    headers['Authorization'] = 'Bearer ' + key
  }
  return headers
}

export function logApiAuth() {
  console.log('[API_AUTH] enabled=' + (isApiAuthEnabled() ? 'true' : 'false'))
}

export function setAstraEdgeApiKey(key) {
  try {
    const v = normalizeKey(key)
    if (v) localStorage.setItem(ASTRAEDGE_API_KEY_STORAGE_KEY, v)
    else localStorage.removeItem(ASTRAEDGE_API_KEY_STORAGE_KEY)
  } catch (_) { /* ignore */ }
  if (typeof window !== 'undefined') window.location.reload()
}

export { parseApiJsonResponse, fetchApiJson, isJsonContentType } from './apiTarget.js'
