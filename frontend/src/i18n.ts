import { createI18n } from 'vue-i18n'
import en from './locales/en.json'
import de from './locales/de.json'
import ptBR from './locales/pt-BR.json'
import esES from './locales/es-ES.json'

// Missao 06 item 4: public locale codes are regional (pt-BR, en-US, es-ES,
// de-DE). The existing en/de catalogs are reused as the en-US/de-DE base; pt-BR
// and es-ES add the translated chrome and fall back through pt-BR -> en-US for
// any key not yet translated (so the UI never shows a raw key).
export const LOCALES: Array<{ code: string; label: string }> = [
  { code: 'pt-BR', label: 'Português (Brasil)' },
  { code: 'en-US', label: 'English (United States)' },
  { code: 'es-ES', label: 'Español (España)' },
  { code: 'de-DE', label: 'Deutsch (Deutschland)' }
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
    'en-US': en,
    'es-ES': esES,
    'de-DE': de
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
