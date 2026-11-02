<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { XMarkIcon } from '@heroicons/vue/24/outline'
import { usePlayerStore } from './stores/player'
import StatusBanner from './components/ui/StatusBanner.vue'

import { LOCALES, setLocale } from './i18n'

const { t, locale } = useI18n()
const playerStore = usePlayerStore()

// Language selector: a custom dropdown with real SVG flags (flag emoji render as
// "BR"/"US" text on Windows, so a native <select> cannot show proper flags).
const localeMenuOpen = ref(false)
const localeMenuRef = ref<HTMLElement | null>(null)
const currentLocale = computed(
  () => LOCALES.find(l => l.code === locale.value) ?? LOCALES[0]
)
function pickLocale(code: string) {
  setLocale(code)
  localeMenuOpen.value = false
}
function flagSvg(code: string): string {
  if (code === 'pt-BR') {
    return '<svg viewBox="0 0 24 16" class="h-4 w-6 rounded-sm shadow-sm"><rect width="24" height="16" fill="#009b3a"/><path d="M12 2 22 8 12 14 2 8Z" fill="#ffdf00"/><circle cx="12" cy="8" r="3.1" fill="#002776"/></svg>'
  }
  if (code === 'en-US') {
    return '<svg viewBox="0 0 24 16" class="h-4 w-6 rounded-sm shadow-sm"><rect width="24" height="16" fill="#fff"/><g fill="#b22234"><rect width="24" height="1.23" y="0"/><rect width="24" height="1.23" y="2.46"/><rect width="24" height="1.23" y="4.92"/><rect width="24" height="1.23" y="7.38"/><rect width="24" height="1.23" y="9.84"/><rect width="24" height="1.23" y="12.3"/><rect width="24" height="1.23" y="14.76"/></g><rect width="10" height="8.6" fill="#3c3b6e"/></svg>'
  }
  return ''
}
function onDocClick(e: MouseEvent) {
  if (localeMenuRef.value && !localeMenuRef.value.contains(e.target as Node)) {
    localeMenuOpen.value = false
  }
}

const navItems = computed(() => [
  { to: '/', label: t('nav.remote'), shortLabel: t('nav.remote') },
  { to: '/catalog', label: t('nav.fotos'), shortLabel: t('nav.fotos') },
  { to: '/appearance', label: t('nav.appearance'), shortLabel: t('nav.appearanceShort') },
  { to: '/settings', label: t('nav.settings'), shortLabel: t('nav.settings') },
  { to: '/optimizer', label: t('nav.optimizer'), shortLabel: t('nav.optimizerShort') },
  { to: '/agendador', label: t('nav.agendador'), shortLabel: t('nav.agendador') },
  { to: '/sistema', label: t('nav.sistema'), shortLabel: t('nav.sistema') }
])

onMounted(() => {
  playerStore.connect()
  document.addEventListener('click', onDocClick)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
})

const connectionIndicator = computed(() => {
  switch (playerStore.connectionStatus) {
    case 'connected':
      return {
        label: t('connection.live'),
        title: t('connection.liveTitle'),
        containerClass:
          'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300',
        dotClass: 'bg-emerald-500',
        pulse: false
      }
    case 'connecting':
      return {
        label: t('connection.connecting'),
        title: t('connection.connectingTitle'),
        containerClass:
          'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300',
        dotClass: 'bg-amber-500',
        pulse: true
      }
    case 'reconnecting':
      return {
        label: t('connection.reconnecting'),
        title: t('connection.reconnectingTitle'),
        containerClass:
          'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300',
        dotClass: 'bg-amber-500',
        pulse: true
      }
    default:
      return {
        label: t('connection.offline'),
        title: t('connection.offlineTitle'),
        containerClass:
          'border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300',
        dotClass: 'bg-red-500',
        pulse: false
      }
  }
})
</script>

<template>
  <div class="min-h-screen bg-gray-100 text-gray-950 dark:bg-gray-900 dark:text-gray-100">
    <header
      class="sticky top-0 z-40 border-b border-gray-200 bg-white/95 shadow-sm backdrop-blur dark:border-gray-800 dark:bg-gray-900/95"
    >
      <nav class="mx-auto flex max-w-[1760px] items-center gap-1.5 px-2 py-2 sm:gap-2 sm:px-6 lg:px-8">
        <div
          class="hide-scrollbar flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto sm:gap-1"
          :aria-label="t('nav.primary')"
        >
          <RouterLink
            v-for="item in navItems"
            :key="item.to"
            :to="item.to"
            class="inline-flex h-9 flex-shrink-0 items-center whitespace-nowrap rounded-lg px-2 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-100 hover:text-gray-950 focus:outline-none focus:ring-2 focus:ring-sky-500/60 dark:text-gray-200 dark:hover:bg-gray-800 dark:hover:text-white sm:h-10 sm:px-3 sm:text-sm"
            active-class="bg-gray-200 text-gray-950 dark:bg-gray-800 dark:text-white"
          >
            <span class="sm:hidden">{{ item.shortLabel }}</span>
            <span class="hidden sm:inline">{{ item.label }}</span>
          </RouterLink>
        </div>
        <div class="flex shrink-0 items-center gap-1.5 sm:gap-2">
          <div
            class="inline-flex h-8 min-w-8 items-center justify-center gap-2 rounded-full border px-2 text-xs font-semibold transition-colors sm:h-9 sm:min-w-9 sm:px-3"
            :class="connectionIndicator.containerClass"
            :title="connectionIndicator.title"
            :aria-label="connectionIndicator.title"
            aria-live="polite"
          >
            <span
              class="h-2.5 w-2.5 rounded-full"
              :class="[
                connectionIndicator.dotClass,
                connectionIndicator.pulse ? 'animate-pulse' : ''
              ]"
            ></span>
            <span class="hidden sm:inline">{{ connectionIndicator.label }}</span>
          </div>
          <div ref="localeMenuRef" class="relative">
            <button
              type="button"
              :aria-label="t('nav.toggleLanguage')"
              :aria-expanded="localeMenuOpen"
              aria-haspopup="listbox"
              class="inline-flex h-9 items-center gap-1.5 rounded-lg border border-gray-300 bg-white px-2 text-xs font-medium text-gray-700 focus:outline-none focus:ring-2 focus:ring-sky-500/60 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200 sm:h-10 sm:text-sm"
              @click.stop="localeMenuOpen = !localeMenuOpen"
            >
              <span class="inline-flex" v-html="flagSvg(currentLocale.code)"></span>
              <span class="hidden md:inline">{{ currentLocale.label }}</span>
              <span class="md:hidden">{{ currentLocale.code }}</span>
              <svg class="h-3 w-3 opacity-60" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/></svg>
            </button>
            <ul
              v-if="localeMenuOpen"
              role="listbox"
              class="absolute right-0 z-50 mt-1 w-48 overflow-hidden rounded-lg border border-gray-200 bg-white py-1 shadow-xl dark:border-gray-700 dark:bg-gray-800"
            >
              <li v-for="l in LOCALES" :key="l.code">
                <button
                  type="button"
                  role="option"
                  :aria-selected="l.code === currentLocale.code"
                  class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-700"
                  :class="l.code === currentLocale.code ? 'font-semibold' : ''"
                  @click="pickLocale(l.code)"
                >
                  <span class="inline-flex" v-html="flagSvg(l.code)"></span>
                  <span>{{ l.label }}</span>
                </button>
              </li>
            </ul>
          </div>
        </div>
      </nav>
    </header>

    <div v-if="playerStore.systemError" class="mx-auto max-w-[1760px] px-3 pt-4 sm:px-6 lg:px-8">
      <StatusBanner
        tone="danger"
        :title="t('common.systemError')"
        :message="playerStore.systemError.message"
      >
        <template #actions>
          <button
            type="button"
            class="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-white px-3 py-2 text-sm font-semibold text-red-700 shadow-sm hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-red-500/60 dark:border-red-500/30 dark:bg-gray-900 dark:text-red-200 dark:hover:bg-red-500/10"
            @click="playerStore.clearError()"
          >
            <XMarkIcon class="h-4 w-4" />
            {{ t('common.dismiss') }}
          </button>
        </template>
      </StatusBanner>
    </div>

    <main class="mx-auto max-w-[1760px] px-3 py-4 sm:px-6 sm:py-6 lg:px-8">
      <RouterView />
    </main>
  </div>
</template>
