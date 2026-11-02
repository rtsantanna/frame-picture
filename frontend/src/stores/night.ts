import { defineStore } from 'pinia'
import { ref } from 'vue'
import axios from 'axios'
import { getApiErrorMessage } from '../utils/errors'

const api = axios.create({
  baseURL: import.meta.env.DEV ? `http://${window.location.hostname}:9000/api` : '/api'
})

export interface NightSettings {
  enabled: boolean
  off_time: string
  on_time: string
  in_off_window: boolean
  exception_active: boolean
  keep_on_until: number
  hdmi_on: boolean
  next_off: string
  next_on: string
  timezone: string
}

const EMPTY: NightSettings = {
  enabled: false, off_time: '00:00', on_time: '06:00', in_off_window: false,
  exception_active: false, keep_on_until: 0, hdmi_on: true,
  next_off: '', next_on: '', timezone: 'America/Sao_Paulo'
}

export const useNightStore = defineStore('night', () => {
  const settings = ref<NightSettings>({ ...EMPTY })
  const error = ref<string | null>(null)
  const loading = ref(false)

  async function fetch() {
    try {
      const { data } = await api.get<NightSettings>('/night/settings')
      settings.value = data
      error.value = null
    } catch (err) {
      error.value = getApiErrorMessage(err, 'Falha ao carregar o agendador')
    }
  }

  async function save(patch: Partial<NightSettings>) {
    loading.value = true
    try {
      const { data } = await api.put<NightSettings>('/night/settings', patch)
      settings.value = data
      error.value = null
    } catch (err) {
      error.value = getApiErrorMessage(err, 'Falha ao salvar o agendador')
      throw err
    } finally {
      loading.value = false
    }
  }

  async function keepOnTonight(enable: boolean) {
    const { data } = await api.post<NightSettings>('/night/keep-on-tonight', { enable })
    settings.value = data
  }

  return { settings, error, loading, fetch, save, keepOnTonight }
})
