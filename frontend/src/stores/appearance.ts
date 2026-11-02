import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.DEV ? `http://${window.location.hostname}:9000/api` : '/api'
})

export interface OverlayAppearance {
  clock_enabled: boolean
  clock_color: string
  clock_size: number
  clock_opacity: number
  description_enabled: boolean
  date_enabled: boolean
  text_color: string
  text_size: number
  text_opacity: number
  text_bg_color: string
  text_bg_opacity: number
}

const DEFAULTS: OverlayAppearance = {
  clock_enabled: true, clock_color: '#f8fafc', clock_size: 120, clock_opacity: 1,
  description_enabled: true, date_enabled: true,
  text_color: '#f8fafc', text_size: 40, text_opacity: 1,
  text_bg_color: '#000000', text_bg_opacity: 0.35
}

export const useAppearanceStore = defineStore('appearance', () => {
  const state = ref<OverlayAppearance>({ ...DEFAULTS })
  const error = ref<string | null>(null)

  async function fetch() {
    try {
      const { data } = await api.get<OverlayAppearance>('/overlay/appearance')
      state.value = { ...DEFAULTS, ...data }
    } catch {
      error.value = 'Falha ao carregar aparência'
    }
  }
  async function save(patch: Partial<OverlayAppearance>) {
    const { data } = await api.put<OverlayAppearance>('/overlay/appearance', patch)
    state.value = { ...DEFAULTS, ...data }
  }
  return { state, error, fetch, save }
})
