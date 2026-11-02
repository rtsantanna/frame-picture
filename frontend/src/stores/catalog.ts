import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'
import { getApiErrorMessage } from '../utils/errors'

const api = axios.create({
  baseURL: import.meta.env.DEV ? `http://${window.location.hostname}:9000/api` : '/api'
})

export interface CatalogItem {
  rel_path: string
  filename: string
  media_type: string
  mime: string | null
  filetype: string | null
  capture_date: string | null
  date_source: string | null
  tz_offset: string | null
  gps_lat: number | null
  gps_lon: number | null
  gps_alt: number | null
  make: string | null
  model: string | null
  orientation: string | null
  width: number | null
  height: number | null
  duration_s: number | null
  suggestion: string | null
  suggestion_source: string | null
  suggestion_confidence: string | null
  approved_description: string | null
  status: string
  visible: number
  edited_manually: number
  manual_rotation?: number
}

export interface CatalogStats {
  total: number
  photos: number
  videos: number
  approved: number
  pending: number
  review: number
  with_gps: number
  no_gps: number
  with_suggestion: number
  no_info: number
  hidden: number
  approval_pct: number
}

export interface CatalogSettings {
  geocode_enabled: boolean
  show_unapproved_on_hdmi: boolean
  pic_dir: string
}

export interface BatchPreview {
  selected: number
  already_approved: number
  pending: number
  will_change: number
  ignored_protected: number
}

const EMPTY_STATS: CatalogStats = {
  total: 0, photos: 0, videos: 0, approved: 0, pending: 0, review: 0,
  with_gps: 0, no_gps: 0, with_suggestion: 0, no_info: 0, hidden: 0, approval_pct: 0
}

export const useCatalogStore = defineStore('catalog', () => {
  const items = ref<CatalogItem[]>([])
  const total = ref(0)
  const stats = ref<CatalogStats>({ ...EMPTY_STATS })
  const settings = ref<CatalogSettings>({ geocode_enabled: false, show_unapproved_on_hdmi: false, pic_dir: '' })
  const loading = ref(false)
  const error = ref<string | null>(null)
  const scanning = ref(false)

  async function fetchStats() {
    try {
      const { data } = await api.get<CatalogStats>('/catalog/stats')
      stats.value = data
    } catch (err) {
      error.value = getApiErrorMessage(err, 'Falha ao carregar estatísticas')
    }
  }

  async function fetchList(params: {
    filters?: string[]; search?: string; year?: number | null; sort?: string; page?: number; per_page?: number
  }) {
    loading.value = true
    try {
      const q = new URLSearchParams()
      ;(params.filters || []).forEach(f => q.append('filters', f))
      if (params.search) q.set('search', params.search)
      if (params.year) q.set('year', String(params.year))
      q.set('sort', params.sort || 'date_desc')
      q.set('page', String(params.page || 1))
      q.set('per_page', String(params.per_page || 25))
      const { data } = await api.get(`/catalog?${q.toString()}`)
      items.value = data.items
      total.value = data.total
      error.value = null
    } catch (err) {
      error.value = getApiErrorMessage(err, 'Falha ao carregar o catálogo')
    } finally {
      loading.value = false
    }
  }

  async function fetchSettings() {
    try {
      const { data } = await api.get<CatalogSettings>('/catalog/settings')
      settings.value = data
    } catch (err) {
      error.value = getApiErrorMessage(err, 'Falha ao carregar configurações')
    }
  }

  async function saveSettings(patch: Partial<CatalogSettings>) {
    const { data } = await api.put<CatalogSettings>('/catalog/settings', patch)
    settings.value = data
  }

  async function updateItem(relPath: string, patch: Record<string, unknown>) {
    const { data } = await api.put<CatalogItem>(`/catalog/item?rel_path=${encodeURIComponent(relPath)}`, patch)
    const idx = items.value.findIndex(i => i.rel_path === relPath)
    if (idx >= 0) items.value[idx] = data
    return data
  }

  async function rotateItem(relPath: string, action: string) {
    const { data } = await api.post<CatalogItem>(
      `/catalog/rotate?rel_path=${encodeURIComponent(relPath)}`,
      { action }
    )
    const idx = items.value.findIndex(i => i.rel_path === relPath)
    if (idx >= 0) items.value[idx] = data
    return data
  }

  async function batchPreview(payload: Record<string, unknown>): Promise<BatchPreview> {
    const { data } = await api.post<BatchPreview>('/catalog/batch/preview', payload)
    return data
  }

  async function batch(payload: Record<string, unknown>) {
    const { data } = await api.post('/catalog/batch', payload)
    return data
  }

  async function scan() {
    const { data } = await api.post('/catalog/scan')
    scanning.value = data.status === 'started'
    return data
  }

  async function scanStatus() {
    try {
      const { data } = await api.get('/catalog/scan/status')
      scanning.value = data.scanning
      return data
    } catch {
      return null
    }
  }

  function thumbUrl(relPath: string, rotation = 0): string {
    // Include the manual rotation so the browser refetches when it changes
    // (the server already keys its own cache on rotation).
    return `${api.defaults.baseURL}/catalog/thumbnail?rel_path=${encodeURIComponent(relPath)}&r=${rotation || 0}`
  }

  async function fetchHistory(relPath: string): Promise<Array<Record<string, unknown>>> {
    try {
      const { data } = await api.get(`/catalog/history?rel_path=${encodeURIComponent(relPath)}`)
      return Array.isArray(data.events) ? data.events : []
    } catch {
      return []
    }
  }

  // --- Dropbox sync ---
  const sync = ref<Record<string, unknown>>({ running: false, result: 'unknown' })
  const divergences = ref<Array<Record<string, unknown>>>([])

  async function fetchSync() {
    try {
      const { data } = await api.get('/sync/status')
      sync.value = data
    } catch { /* ignore */ }
  }
  async function syncNow() {
    const { data } = await api.post('/sync/now')
    await fetchSync()
    return data
  }
  async function fetchDivergences() {
    try {
      const { data } = await api.get('/sync/divergences')
      divergences.value = Array.isArray(data.items) ? data.items : []
    } catch { /* ignore */ }
  }

  return {
    items, total, stats, settings, loading, error, scanning,
    sync, divergences,
    fetchStats, fetchList, fetchSettings, saveSettings, updateItem, rotateItem,
    batchPreview, batch, scan, scanStatus, thumbUrl, fetchHistory,
    fetchSync, syncNow, fetchDivergences
  }
})
