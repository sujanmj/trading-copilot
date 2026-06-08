/**
 * API base URL resolution for AstraEdge GUI (Vite modules only for import.meta.env).
 */

export const LOCAL_API_BASE = 'http://127.0.0.1:8080'
export const FALLBACK_API_BASE = LOCAL_API_BASE
export const ASTRA_API_TARGET_STORAGE_KEY = 'ASTRAEDGE_API_TARGET'
export const ASTRA_RAILWAY_URL_STORAGE_KEY = 'ASTRAEDGE_API_BASE_URL'

const PLACEHOLDER = '%VITE_API_BASE_URL%'

export function normalizeBaseUrl(url) {
  return String(url || '').trim().replace(/\/$/, '')
}

export function readInjectedViteApiBaseUrl() {
  if (typeof window === 'undefined') return ''
  const env = window.__ASTRAEDGE_ENV__ || {}
  const raw = env.VITE_API_BASE_URL
  const v = normalizeBaseUrl(raw)
  if (!v || v.includes(PLACEHOLDER)) return ''
  return v
}

/** Vite module: import.meta.env; falls back to injected window env. */
export function readViteApiBaseUrl() {
  try {
    if (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_API_BASE_URL) {
      const v = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL)
      if (v) return v
    }
  } catch (_) { /* ignore */ }
  return readInjectedViteApiBaseUrl()
}

export function getStoredRailwayApiUrl() {
  try {
    return normalizeBaseUrl(localStorage.getItem(ASTRA_RAILWAY_URL_STORAGE_KEY))
  } catch (_) { /* ignore */ }
  return ''
}

export function getStoredApiTarget() {
  try {
    const raw = localStorage.getItem(ASTRA_API_TARGET_STORAGE_KEY)
    if (raw) {
      const target = raw.trim().toLowerCase()
      if (target === 'local' || target === 'railway') return target
    }
  } catch (_) { /* ignore */ }
  const injected = readInjectedViteApiBaseUrl()
  if (injected && !isLocalApiBase(injected)) return 'railway'
  const stored = getStoredRailwayApiUrl()
  if (stored && !isLocalApiBase(stored)) return 'railway'
  return 'local'
}

export function isLocalApiBase(base) {
  const b = String(base || '').toLowerCase()
  return b.includes('127.0.0.1') || b.includes('localhost')
}

export function isRailwayApiBase(base) {
  const b = String(base || '').toLowerCase()
  if (!b || isLocalApiBase(b)) return false
  return (
    b.includes('railway.app') ||
    b.includes('up.railway.app') ||
    b.includes('web-production')
  )
}

export function getApiMode(base) {
  const url = normalizeBaseUrl(base)
  if (!url || isLocalApiBase(url)) return 'LOCAL'
  if (isRailwayApiBase(url)) return 'RAILWAY'
  return 'RAILWAY'
}

/**
 * Priority when API target is Railway:
 * 1. localStorage ASTRAEDGE_API_BASE_URL
 * 2. import.meta.env.VITE_API_BASE_URL (module only)
 * 3. window.__ASTRAEDGE_ENV__.VITE_API_BASE_URL
 * 4. http://127.0.0.1:8080
 */
export function resolveRailwayApiBase() {
  const stored = getStoredRailwayApiUrl()
  if (stored) return stored
  const vite = readViteApiBaseUrl()
  if (vite) return vite
  const injected = readInjectedViteApiBaseUrl()
  if (injected) return injected
  return FALLBACK_API_BASE
}

export function resolveApiBase(opts = {}) {
  const isElectron = !!(opts.isElectron)
  const target = getStoredApiTarget()
  if (target === 'local') {
    if (isElectron) {
      const envBase = opts.electronApiBase || ''
      const explicit = normalizeBaseUrl(envBase)
      if (explicit) return explicit
    }
    return LOCAL_API_BASE
  }
  return resolveRailwayApiBase()
}

export function logApiTarget(base) {
  const resolved = normalizeBaseUrl(base)
  const mode = getApiMode(resolved)
  console.log('[API_TARGET] resolved=' + resolved + ' mode=' + mode)
}

const NON_JSON_ERROR = 'API returned HTML/non-JSON. Check API base/path.'

export function isJsonContentType(contentType) {
  return String(contentType || '').toLowerCase().includes('application/json')
}

/** Safe JSON parser — checks content-type and avoids tab crash on HTML responses. */
export async function parseApiJsonResponse(res, url = '') {
  const ct = (res.headers && res.headers.get) ? res.headers.get('content-type') : ''
  const text = await res.text()
  if (!isJsonContentType(ct)) {
    const preview = text.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120)
    const detail = preview ? `${NON_JSON_ERROR} Preview: ${preview}` : NON_JSON_ERROR
    throw new Error(detail)
  }
  try {
    return text ? JSON.parse(text) : {}
  } catch (err) {
    const preview = text.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120)
    throw new Error(`${NON_JSON_ERROR} ${url ? url + ' ' : ''}${preview}`)
  }
}

export async function fetchApiJson(url, options = {}, timeoutMs = 18000) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const res = await fetch(url, { ...options, signal: controller.signal })
    if (!res.ok) {
      throw new Error(`HTTP ${res.status} ${url}`)
    }
    return await parseApiJsonResponse(res, url)
  } catch (err) {
    if (err && err.name === 'AbortError') {
      throw new Error('Request timed out or was cancelled.')
    }
    throw err
  } finally {
    clearTimeout(timer)
  }
}
