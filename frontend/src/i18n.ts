import { createI18n } from 'vue-i18n'
import en from './locales/en.json'
import ptBR from './locales/pt-BR.json'

// Missao 06 (atualizada): only two public locales are offered — pt-BR (default)
// and en-US. es-ES / de-DE were dropped. Any key missing from pt-BR falls back
// to en-US so the UI never shows a raw key.
export const LOCALES: Array<{ code: string; label: string }> = [
  { code: 'pt-BR', label: 'Português (Brasil)' },
  { code: 'en-US', label: 'English (United States)' }
]

const STORAGE_KEY = 'framepicture.locale'

function initialLocale(): string {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved && LOCALES.some(l => l.code === saved)) return saved
  } catch {
    /* storage unavailable */
  }
  return 'pt-BR'
}

const i18n = createI18n({
  legacy: false,
  locale: initialLocale(),
  fallbackLocale: ['pt-BR', 'en-US'],
  messages: {
    'pt-BR': ptBR,
    'en-US': en
  }
})

export function setLocale(code: string): void {
  if (!LOCALES.some(l => l.code === code)) return
  // @ts-expect-error vue-i18n composition global is a ref in legacy:false
  i18n.global.locale.value = code
  try {
    localStorage.setItem(STORAGE_KEY, code)
  } catch {
    /* ignore */
  }
}

export default i18n
