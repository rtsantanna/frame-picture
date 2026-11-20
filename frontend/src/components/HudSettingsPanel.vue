<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowPathIcon, MagnifyingGlassIcon, MapPinIcon } from '@heroicons/vue/24/outline'
import {
  HUD_ANCHORS,
  HUD_ELEMENTS,
  useAppearanceStore,
  type Hud,
  type HudAnchor,
  type HudElementName,
  type HudPatch,
  type PlaceResult,
  type WeatherReading
} from '../stores/appearance'
import { useConfigStore } from '../stores/config'
import { useCatalogStore } from '../stores/catalog'
import ToggleSwitch from './settings/ToggleSwitch.vue'
import Panel from './ui/Panel.vue'

const { t } = useI18n()
const store = useAppearanceStore()
const configStore = useConfigStore()
const catalogStore = useCatalogStore()

// Local copy so sliders/colours preview instantly; persisted on change.
// (JSON copy: structuredClone cannot clone Vue's reactive proxies.)
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T
const draft = reactive<Hud>(clone(store.state.hud))
watch(
  () => store.state.hud,
  value => Object.assign(draft, clone(value)),
  { deep: true }
)

const saveError = ref('')
async function save(patch: HudPatch) {
  saveError.value = ''
  try {
    await store.save({ hud: patch })
  } catch {
    saveError.value = store.error || t('appearance.hud.saveFailed')
  }
}

function setElement(name: HudElementName, patch: Partial<Hud['elements'][HudElementName]>) {
  Object.assign(draft.elements[name], patch)
  void save({ elements: { [name]: patch } })
}

const FONTS = ['noto', 'noto_bold', 'dejavu', 'dejavu_bold'] as const
const FORMATTED: Partial<Record<HudElementName, keyof Hud['formats']>> = {
  clock: 'clock',
  today_date: 'today_date',
  photo_date: 'photo_date'
}
const PHOTO: HudElementName[] = ['description', 'location', 'photo_date']

// --- show text on video (legacy viewer key, still honoured by playback) ---
const showOnVideo = computed(() => Boolean(configStore.config?.viewer?.show_text_on_video))
async function setShowOnVideo(value: boolean) {
  await configStore.saveWorkflowConfig({ viewer: { show_text_on_video: value } })
}

// --- weather ---
const query = ref('')
const searching = ref(false)
const results = ref<PlaceResult[]>([])
const searchError = ref('')
const reading = ref<WeatherReading | null>(null)
const weatherError = ref('')

async function search() {
  if (query.value.trim().length < 2) return
  searching.value = true
  searchError.value = ''
  try {
    results.value = await store.searchPlaces(query.value.trim())
    if (!results.value.length) searchError.value = t('appearance.hud.weather.noResults')
  } catch {
    searchError.value = t('appearance.hud.weather.searchFailed')
  } finally {
    searching.value = false
  }
}

async function choosePlace(place: PlaceResult) {
  results.value = []
  query.value = ''
  draft.weather = { lat: place.lat, lon: place.lon, place: place.label }
  await save({ weather: { lat: place.lat, lon: place.lon, place: place.label } })
  await refreshWeather(true)
}

async function refreshWeather(force = false) {
  weatherError.value = ''
  if (draft.weather.lat == null) {
    reading.value = null
    return
  }
  try {
    const res = await store.fetchWeather(force)
    reading.value = res.data
    weatherError.value = res.data ? '' : res.error || t('appearance.hud.weather.noData')
  } catch {
    weatherError.value = t('appearance.hud.weather.noData')
  }
}

const fmtTemp = (v: number | null | undefined) => (v == null ? '--°' : `${Math.round(v)}°`)

// --- preview ---
const PREVIEW_H = 1080
const SAMPLE: Record<HudElementName, string[]> = {
  clock: ['18:25'],
  today_date: ['20/11/2026'],
  weather: ['☀ 27°', '↑31°  ↓19°'],
  description: ['Praia do Forte'],
  location: ['Mata de São João, Bahia'],
  photo_date: ['12/05/2019']
}
const STACK: HudElementName[] = ['weather', 'clock', 'today_date', 'description', 'location', 'photo_date']

const previewStacks = computed(() => {
  const stacks: Record<HudAnchor, Array<{ key: string; text: string; size: number }>> = {
    TL: [], TC: [], TR: [], BL: [], BC: [], BR: []
  }
  for (const name of STACK) {
    const el = draft.elements[name]
    if (!el.enabled) continue
    SAMPLE[name].forEach((text, i) => {
      const size = name === 'weather' && i === 1 ? Math.max(12, el.size * 0.6) : el.size
      stacks[el.position].push({ key: `${name}-${i}`, text, size })
    })
  }
  return stacks
})

const previewStyle = computed(() => ({
  color: draft.style.color,
  opacity: String(Math.max(0.15, draft.style.opacity)),
  fontWeight: draft.style.font.endsWith('bold') ? '700' : '400',
  fontFamily: draft.style.font.startsWith('dejavu') ? 'DejaVu Sans, Verdana, sans-serif' : 'Noto Sans, system-ui, sans-serif'
}))

function anchorClass(anchor: HudAnchor) {
  const v = anchor[0] === 'T' ? 'top-0' : 'bottom-0'
  const h = anchor[1] === 'L' ? 'left-0 items-start' : anchor[1] === 'R' ? 'right-0 items-end' : 'left-1/2 -translate-x-1/2 items-center'
  return `${v} ${h}`
}

const locationHint = computed(
  () => draft.elements.location.enabled && !catalogStore.settings.geocode_enabled
)

onMounted(async () => {
  await store.fetch()
  void catalogStore.fetchSettings()
  if (!configStore.config?.viewer) void configStore.fetchWorkflowConfig()
  void refreshWeather()
})
</script>

<template>
  <Panel padded>
    <div class="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-lg font-semibold text-gray-950 dark:text-white">{{ t('appearance.hud.title') }}</h2>
        <p class="mt-1 text-sm text-gray-600 dark:text-gray-300">{{ t('appearance.hud.subtitle') }}</p>
      </div>
      <span v-if="store.saving" class="text-xs text-gray-400">{{ t('appearance.saving') }}</span>
    </div>

    <p v-if="saveError" class="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-500/10 dark:text-red-300">
      {{ saveError }}
    </p>

    <div class="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
      <div class="space-y-6">
        <!-- Shared style -->
        <section>
          <h3 class="mb-2 text-sm font-semibold text-gray-900 dark:text-white">{{ t('appearance.hud.styleTitle') }}</h3>
          <div class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <label class="hud-field">
              <span>{{ t('appearance.hud.font') }}</span>
              <select v-model="draft.style.font" class="hud-input" @change="save({ style: { font: draft.style.font } })">
                <option v-for="f in FONTS" :key="f" :value="f">{{ t('appearance.hud.fonts.' + f) }}</option>
              </select>
            </label>
            <label class="hud-field">
              <span>{{ t('appearance.hud.color') }}</span>
              <input v-model="draft.style.color" type="color" class="hud-color" @change="save({ style: { color: draft.style.color } })" />
            </label>
            <label class="hud-field">
              <span>{{ t('appearance.hud.opacity') }} · {{ Math.round(draft.style.opacity * 100) }}%</span>
              <input v-model.number="draft.style.opacity" type="range" min="0.1" max="1" step="0.05" class="mt-2 w-full accent-indigo-600"
                @change="save({ style: { opacity: draft.style.opacity } })" />
            </label>
            <label class="hud-field">
              <span>{{ t('appearance.hud.bgColor') }}</span>
              <input v-model="draft.style.bg_color" type="color" class="hud-color" @change="save({ style: { bg_color: draft.style.bg_color } })" />
            </label>
            <label class="hud-field">
              <span>{{ t('appearance.hud.bgOpacity') }} · {{ draft.style.bg_opacity ? Math.round(draft.style.bg_opacity * 100) + '%' : t('appearance.hud.none') }}</span>
              <input v-model.number="draft.style.bg_opacity" type="range" min="0" max="0.9" step="0.05" class="mt-2 w-full accent-indigo-600"
                @change="save({ style: { bg_opacity: draft.style.bg_opacity } })" />
            </label>
          </div>
        </section>

        <!-- Elements -->
        <section>
          <h3 class="mb-2 text-sm font-semibold text-gray-900 dark:text-white">{{ t('appearance.hud.elementsTitle') }}</h3>
          <div class="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <table class="w-full text-sm">
              <thead class="bg-gray-50 text-left text-xs uppercase text-gray-500 dark:bg-gray-900/50 dark:text-gray-400">
                <tr>
                  <th class="px-3 py-2">{{ t('appearance.hud.element') }}</th>
                  <th class="px-3 py-2">{{ t('appearance.hud.size') }}</th>
                  <th class="px-3 py-2">{{ t('appearance.hud.position') }}</th>
                  <th class="px-3 py-2">{{ t('appearance.hud.format') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="name in HUD_ELEMENTS" :key="name" class="border-t border-gray-100 dark:border-gray-700/60"
                  :class="draft.elements[name].enabled ? '' : 'opacity-60'">
                  <td class="px-3 py-2">
                    <div class="flex items-center gap-3">
                      <ToggleSwitch :model-value="draft.elements[name].enabled" :label="t('appearance.hud.elements.' + name)"
                        @update:model-value="v => setElement(name, { enabled: v })" />
                      <div>
                        <div class="font-medium text-gray-900 dark:text-white">{{ t('appearance.hud.elements.' + name) }}</div>
                        <div class="text-[11px] text-gray-400">
                          {{ PHOTO.includes(name) ? t('appearance.hud.perPhoto') : t('appearance.hud.always') }}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td class="px-3 py-2">
                    <input v-model.number="draft.elements[name].size" type="number" min="12" max="400" step="2"
                      class="hud-input w-20" @change="setElement(name, { size: draft.elements[name].size })" />
                  </td>
                  <td class="px-3 py-2">
                    <select v-model="draft.elements[name].position" class="hud-input w-40"
                      @change="setElement(name, { position: draft.elements[name].position })">
                      <option v-for="a in HUD_ANCHORS" :key="a" :value="a">{{ t('appearance.hud.anchors.' + a) }}</option>
                    </select>
                  </td>
                  <td class="px-3 py-2">
                    <input v-if="FORMATTED[name]" v-model="draft.formats[FORMATTED[name]!]" type="text" maxlength="40"
                      class="hud-input w-28 font-mono text-xs"
                      @change="save({ formats: { [FORMATTED[name]!]: draft.formats[FORMATTED[name]!] } })" />
                    <span v-else class="text-xs text-gray-400">—</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="mt-2 text-xs text-gray-500 dark:text-gray-400">{{ t('appearance.hud.formatHelp') }}</p>
          <p v-if="locationHint" class="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-500/10 dark:text-amber-300">
            {{ t('appearance.hud.locationHint') }}
          </p>
          <div class="mt-3 flex items-center justify-between gap-4 rounded-lg border border-gray-200 px-3 py-2 dark:border-gray-700">
            <div>
              <div class="text-sm font-medium text-gray-900 dark:text-white">{{ t('appearance.hud.showOnVideo') }}</div>
              <div class="text-xs text-gray-500 dark:text-gray-400">{{ t('appearance.hud.showOnVideoHelp') }}</div>
            </div>
            <ToggleSwitch :model-value="showOnVideo" :label="t('appearance.hud.showOnVideo')" @update:model-value="setShowOnVideo" />
          </div>
        </section>

        <!-- Weather -->
        <section>
          <h3 class="mb-1 text-sm font-semibold text-gray-900 dark:text-white">{{ t('appearance.hud.weather.title') }}</h3>
          <p class="mb-3 text-xs text-gray-500 dark:text-gray-400">{{ t('appearance.hud.weather.help') }}</p>
          <div class="flex flex-wrap items-center gap-2">
            <div class="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 dark:border-gray-600 dark:bg-gray-700">
              <MagnifyingGlassIcon class="h-4 w-4 flex-shrink-0 text-gray-400" />
              <input v-model="query" type="search" :placeholder="t('appearance.hud.weather.placeholder')"
                class="min-w-0 flex-1 border-0 bg-transparent py-2 text-sm focus:ring-0 dark:text-white" @keydown.enter.prevent="search" />
            </div>
            <button type="button" class="rounded-lg bg-indigo-600 px-3 py-2 text-sm font-semibold text-white hover:bg-indigo-500 disabled:opacity-60"
              :disabled="searching || query.trim().length < 2" @click="search">
              {{ searching ? t('appearance.hud.weather.searching') : t('appearance.hud.weather.search') }}
            </button>
          </div>
          <p v-if="searchError" class="mt-2 text-xs text-red-600 dark:text-red-400">{{ searchError }}</p>
          <ul v-if="results.length" class="mt-2 divide-y divide-gray-100 overflow-hidden rounded-lg border border-gray-200 dark:divide-gray-700 dark:border-gray-700">
            <li v-for="r in results" :key="`${r.lat},${r.lon}`">
              <button type="button" class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-gray-50 dark:hover:bg-gray-700/50" @click="choosePlace(r)">
                <MapPinIcon class="h-4 w-4 flex-shrink-0 text-gray-400" />
                <span class="text-gray-900 dark:text-white">{{ r.label }}</span>
                <span class="ml-auto font-mono text-[11px] text-gray-400">{{ r.lat.toFixed(2) }}, {{ r.lon.toFixed(2) }}</span>
              </button>
            </li>
          </ul>
          <div class="mt-3 flex flex-wrap items-center gap-3 rounded-lg bg-gray-50 px-3 py-2 text-sm dark:bg-gray-900/40">
            <MapPinIcon class="h-4 w-4 text-gray-400" />
            <span v-if="draft.weather.place" class="font-medium text-gray-900 dark:text-white">{{ draft.weather.place }}</span>
            <span v-else class="text-gray-500">{{ t('appearance.hud.weather.noPlace') }}</span>
            <span v-if="reading" class="text-gray-700 dark:text-gray-200">
              {{ reading.icon }} {{ fmtTemp(reading.temp) }} · ↑{{ fmtTemp(reading.tmax) }} ↓{{ fmtTemp(reading.tmin) }}
            </span>
            <span v-else-if="weatherError && draft.weather.place" class="text-xs text-amber-600 dark:text-amber-400">{{ weatherError }}</span>
            <button v-if="draft.weather.place" type="button" class="ml-auto inline-flex items-center gap-1 text-xs font-medium text-indigo-600 hover:underline dark:text-indigo-400"
              @click="refreshWeather(true)">
              <ArrowPathIcon class="h-3.5 w-3.5" /> {{ t('appearance.hud.weather.refresh') }}
            </button>
          </div>
          <p v-if="draft.elements.weather.enabled && !draft.weather.place" class="mt-2 text-xs text-amber-700 dark:text-amber-400">
            {{ t('appearance.hud.weather.needPlace') }}
          </p>
        </section>
      </div>

      <!-- Preview -->
      <aside class="xl:sticky xl:top-20 xl:self-start">
        <h3 class="mb-2 text-sm font-semibold text-gray-900 dark:text-white">{{ t('appearance.hud.preview') }}</h3>
        <div class="hud-preview relative aspect-video w-full overflow-hidden rounded-lg bg-gradient-to-br from-slate-600 via-slate-500 to-amber-700 shadow-inner"
          :style="{ containerType: 'inline-size' }">
          <div v-if="draft.style.bg_opacity > 0" class="absolute inset-x-0 bottom-0 h-1/4"
            :style="{ background: `linear-gradient(to top, ${draft.style.bg_color}${Math.round(draft.style.bg_opacity * 255).toString(16).padStart(2, '0')}, transparent)` }"></div>
          <div v-for="a in HUD_ANCHORS" :key="a" class="absolute flex flex-col"
            :class="anchorClass(a)" :style="{ padding: `${draft.margin_pct * 0.5625}cqw ${draft.margin_pct}cqw` }">
            <span v-for="line in previewStacks[a]" :key="line.key" class="whitespace-nowrap leading-tight"
              :style="{ ...previewStyle, fontSize: `${(line.size / PREVIEW_H) * 56.25}cqw`, textShadow: '0 0 3px #000' }">{{ line.text }}</span>
          </div>
        </div>
        <p class="mt-2 text-xs text-gray-500 dark:text-gray-400">{{ t('appearance.hud.previewHelp') }}</p>
      </aside>
    </div>
  </Panel>
</template>

<style scoped>
.hud-field {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.75rem;
  font-weight: 500;
  color: rgb(75 85 99);
}
:global(.dark) .hud-field {
  color: rgb(209 213 219);
}
.hud-input {
  border-radius: 0.5rem;
  border: 1px solid rgb(209 213 219);
  background: white;
  padding: 0.375rem 0.5rem;
  font-size: 0.875rem;
  color: rgb(17 24 39);
}
:global(.dark) .hud-input {
  border-color: rgb(75 85 99);
  background: rgb(55 65 81);
  color: white;
}
.hud-color {
  height: 2.25rem;
  width: 100%;
  border-radius: 0.5rem;
  border: 1px solid rgb(209 213 219);
  background: white;
  padding: 0.125rem;
}
</style>
