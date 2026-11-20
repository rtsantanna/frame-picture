import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'
import { getApiErrorMessage } from '../utils/errors'

const api = axios.create({
  baseURL: import.meta.env.DEV ? `http://${window.location.hostname}:9000/api` : '/api'
})

export type HudAnchor = 'TL' | 'TC' | 'TR' | 'BL' | 'BC' | 'BR'
export type HudElementName =
  | 'weather'
  | 'clock'
  | 'today_date'
  | 'description'
  | 'location'
  | 'photo_date'
export type HudFont = 'noto' | 'noto_bold' | 'dejavu' | 'dejavu_bold'

export interface HudElement {
  enabled: boolean
  size: number
  position: HudAnchor
}

export interface Hud {
  style: { font: HudFont; color: string; opacity: number; bg_color: string; bg_opacity: number }
  elements: Record<HudElementName, HudElement>
  formats: { clock: string; today_date: string; photo_date: string }
  weather: {
    lat: number | null
    lon: number | null
    place: string
    icon_style: 'color' | 'mono'
    max_color: string
    min_color: string
    /** null = follow the shared style opacity */
    opacity: number | null
  }
  margin_pct: number
  lang: 'pt' | 'en'
}

/** Patch shape accepted by the API (every level is optional). */
export interface HudPatch {
  style?: Partial<Hud['style']>
  elements?: Partial<Record<HudElementName, Partial<HudElement>>>
  formats?: Partial<Hud['formats']>
  weather?: Partial<Hud['weather']>
  margin_pct?: number
  lang?: Hud['lang']
}

export interface OverlayAppearance {
  hud: Hud
  video_scaling: string
  video_margin_pct: number
}

export interface WeatherReading {
  temp: number | null
  tmax: number | null
  tmin: number | null
  icon: string
  kind?: string
  code: number | null
  fetched_at: number
}

export interface PlaceResult {
  label: string
  name: string
  lat: number
  lon: number
}

export const HUD_ELEMENTS: HudElementName[] = [
  'clock',
  'today_date',
  'weather',
  'description',
  'location',
  'photo_date'
]
export const HUD_ANCHORS: HudAnchor[] = ['TL', 'TC', 'TR', 'BL', 'BC', 'BR']

const DEFAULT_HUD: Hud = {
  style: { font: 'noto', color: '#f8fafc', opacity: 0.4, bg_color: '#000000', bg_opacity: 0 },
  elements: {
    description: { enabled: true, size: 40, position: 'BL' },
    location: { enabled: false, size: 32, position: 'BL' },
    photo_date: { enabled: true, size: 32, position: 'BL' },
    clock: { enabled: true, size: 120, position: 'BR' },
    today_date: { enabled: false, size: 36, position: 'BR' },
    weather: { enabled: false, size: 48, position: 'TR' }
  },
  formats: { clock: '%H:%M', today_date: '%d/%m/%Y', photo_date: '%d/%m/%Y' },
  weather: {
    lat: null,
    lon: null,
    place: '',
    icon_style: 'color',
    max_color: '#ef4444',
    min_color: '#3b82f6',
    opacity: null
  },
  margin_pct: 3,
  lang: 'pt'
}

const DEFAULTS: OverlayAppearance = {
  hud: DEFAULT_HUD,
  video_scaling: 'margin',
  video_margin_pct: 6
}

export const useAppearanceStore = defineStore('appearance', () => {
  const state = ref<OverlayAppearance>(structuredClone(DEFAULTS))
  const error = ref<string | null>(null)
  const saving = ref(false)

  function apply(data: Partial<OverlayAppearance>) {
    state.value = {
      ...structuredClone(DEFAULTS),
      ...data,
      hud: { ...structuredClone(DEFAULT_HUD), ...(data.hud || {}) } as Hud
    }
  }

  async function fetch() {
    try {
      const { data } = await api.get<OverlayAppearance>('/overlay/appearance')
      apply(data)
      error.value = null
    } catch (err) {
      error.value = getApiErrorMessage(err, 'Falha ao carregar aparência')
    }
  }

  async function save(patch: Partial<Omit<OverlayAppearance, 'hud'>> & { hud?: HudPatch }) {
    saving.value = true
    try {
      const { data } = await api.put<OverlayAppearance>('/overlay/appearance', patch)
      apply(data)
      error.value = null
    } catch (err) {
      error.value = getApiErrorMessage(err, 'Falha ao salvar aparência')
      throw err
    } finally {
      saving.value = false
    }
  }

  async function searchPlaces(q: string): Promise<PlaceResult[]> {
    const { data } = await api.get<{ results: PlaceResult[] }>('/weather/search', { params: { q } })
    return data.results || []
  }

  function iconUrl(kind: string, size = 64): string {
    return `${api.defaults.baseURL}/weather/icon/${encodeURIComponent(kind)}.png?size=${size}`
  }

  async function fetchWeather(refresh = false): Promise<{
    place: string
    data: WeatherReading | null
    error: string | null
  }> {
    const { data } = await api.get('/weather/current', { params: { refresh } })
    return data
  }

  return { state, error, saving, fetch, save, searchPlaces, fetchWeather, iconUrl }
})
