<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCatalogStore, type CatalogItem } from '../stores/catalog'

const { t, locale } = useI18n()
const store = useCatalogStore()

const PRIMARY = ['all', 'pending', 'approved', 'auto_location', 'with_suggestion', 'no_info', 'review', 'hidden']
const EXTRAS = ['with_gps', 'no_gps', 'photos', 'videos', 'visible', 'with_date', 'no_date', 'edited']
const SORTS = ['date_desc', 'date_asc', 'name_asc', 'name_desc', 'status']

const primary = ref('all')
const extras = reactive<Set<string>>(new Set())
const search = ref('')
const year = ref<number | null>(null)
const sort = ref('date_desc')
const page = ref(1)
const perPage = ref(25)

const selected = reactive<Set<string>>(new Set())
const selectAllResults = ref(false)
const drafts = reactive<Record<string, string>>({})

const activeFilters = computed(() => [primary.value, ...Array.from(extras)])
const totalPages = computed(() => Math.max(1, Math.ceil(store.total / perPage.value)))

async function refresh() {
  await store.fetchList({
    filters: activeFilters.value,
    search: search.value || undefined,
    year: year.value,
    sort: sort.value,
    page: page.value,
    per_page: perPage.value
  })
  for (const it of store.items) {
    if (!(it.rel_path in drafts)) drafts[it.rel_path] = it.approved_description || ''
  }
}

async function refreshAll() {
  await Promise.all([refresh(), store.fetchStats()])
}

watch([primary, sort, perPage, year], () => { page.value = 1; selectAllResults.value = false; refresh() })
watch(extras, () => { page.value = 1; selectAllResults.value = false; refresh() }, { deep: true })
watch(page, () => refresh())

let searchTimer: number | undefined
watch(search, () => {
  if (searchTimer) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => { page.value = 1; refresh() }, 350)
})

onMounted(() => {
  refreshAll()
  store.fetchSettings()
})

async function toggleGeocode(v: boolean) {
  await store.saveSettings({ geocode_enabled: v })
}
async function toggleUnapproved(v: boolean) {
  await store.saveSettings({ show_unapproved_on_hdmi: v })
}

function toggleExtra(id: string) {
  if (extras.has(id)) extras.delete(id)
  else extras.add(id)
}

function toggleRow(relPath: string) {
  if (selected.has(relPath)) selected.delete(relPath)
  else selected.add(relPath)
  selectAllResults.value = false
}
function selectPage() {
  store.items.forEach(i => selected.add(i.rel_path))
  selectAllResults.value = false
}
function selectAll() {
  store.items.forEach(i => selected.add(i.rel_path))
  selectAllResults.value = true
}
function clearSelection() {
  selected.clear()
  selectAllResults.value = false
}
const selectionCount = computed(() => (selectAllResults.value ? store.total : selected.size))

async function approveRow(it: CatalogItem) {
  const desc = (drafts[it.rel_path] ?? '').trim() || it.suggestion || ''
  if (!desc) return
  await store.updateItem(it.rel_path, { approved_description: desc, status: 'approved' })
  await store.fetchStats()
}
async function acceptSuggestion(it: CatalogItem) {
  if (!it.suggestion) return
  drafts[it.rel_path] = it.suggestion
  await store.updateItem(it.rel_path, { approved_description: it.suggestion, status: 'approved' })
  await store.fetchStats()
}
async function markReview(it: CatalogItem) {
  await store.updateItem(it.rel_path, { status: 'review' })
  await store.fetchStats()
}
async function toggleVisible(it: CatalogItem) {
  await store.updateItem(it.rel_path, { visible: it.visible === 1 ? false : true })
  await store.fetchStats()
}

// --- batch ---
const batchDesc = ref('')
const overwriteApproved = ref(false)
const showBatchModal = ref(false)
const preview = ref<Awaited<ReturnType<typeof store.batchPreview>> | null>(null)

function batchPayload(action: string, extra: Record<string, unknown> = {}) {
  if (selectAllResults.value) {
    return {
      select_all: true,
      filters: activeFilters.value,
      search: search.value || undefined,
      year: year.value,
      action,
      ...extra
    }
  }
  return { rel_paths: Array.from(selected), action, ...extra }
}

async function openBatchDescription() {
  const base = selectAllResults.value
    ? { select_all: true, filters: activeFilters.value, search: search.value || undefined, year: year.value }
    : { rel_paths: Array.from(selected) }
  preview.value = await store.batchPreview({ ...base, overwrite_approved: overwriteApproved.value })
  showBatchModal.value = true
}
async function confirmBatchDescription() {
  await store.batch(batchPayload('set_description', {
    description: batchDesc.value,
    overwrite_approved: overwriteApproved.value
  }))
  showBatchModal.value = false
  batchDesc.value = ''
  clearSelection()
  await refreshAll()
}
async function runBatch(action: string) {
  await store.batch(batchPayload(action, { overwrite_approved: overwriteApproved.value }))
  clearSelection()
  await refreshAll()
}

async function doScan() {
  await store.scan()
  const poll = window.setInterval(async () => {
    const s = await store.scanStatus()
    if (s && !s.scanning) {
      window.clearInterval(poll)
      await refreshAll()
    }
  }, 1500)
}

function fmtDate(d: string | null): string {
  if (!d) return '—'
  const m = /^(\d{4}):(\d{2}):(\d{2})/.exec(d)
  return m ? `${m[3]}/${m[2]}/${m[1]}` : d
}
function fmtGps(it: CatalogItem): string {
  if (it.gps_lat == null || it.gps_lon == null) return '—'
  return `${it.gps_lat.toFixed(4)}, ${it.gps_lon.toFixed(4)}`
}
const statusChip: Record<string, string> = {
  approved: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300',
  pending: 'bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300',
  review: 'bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300'
}
// --- histórico ---
const showHistoryModal = ref(false)
const historyItems = ref<Array<Record<string, unknown>>>([])
const historyFile = ref('')
async function openHistory(it: CatalogItem) {
  historyFile.value = it.filename
  historyItems.value = await store.fetchHistory(it.rel_path)
  showHistoryModal.value = true
}
const EVENT_KEYS = new Set([
  'description_created', 'description_edited', 'approved', 'marked_review', 'unapproved',
  'hidden', 'shown', 'suggestion_changed', 'status_changed', 'rotation_changed', 'rotation_reset'
])

// --- rotação manual (não destrutiva) ---
const showRotateModal = ref(false)
const rotateItemRef = ref<CatalogItem | null>(null)
const rotateSaved = ref(0)
const rotatePreview = ref(0)
const rotateSaving = ref(false)
function openRotate(it: CatalogItem) {
  rotateItemRef.value = it
  rotateSaved.value = ((it.manual_rotation || 0) % 360 + 360) % 360
  rotatePreview.value = rotateSaved.value
  showRotateModal.value = true
}
function rotateBy(delta: number) {
  rotatePreview.value = ((rotatePreview.value + delta) % 360 + 360) % 360
}
function rotateAuto() { rotatePreview.value = 0 }
const rotatePreviewDelta = computed(
  () => ((rotatePreview.value - rotateSaved.value) % 360 + 360) % 360
)
async function confirmRotate() {
  if (!rotateItemRef.value) return
  rotateSaving.value = true
  try {
    await store.rotateItem(rotateItemRef.value.rel_path, String(rotatePreview.value))
  } finally {
    rotateSaving.value = false
    showRotateModal.value = false
  }
}
function eventLabel(e: unknown): string {
  const key = String(e)
  return EVENT_KEYS.has(key) ? t('catalog.events.' + key) : key
}
function fmtTs(ts: unknown): string {
  const n = Number(ts)
  return n ? new Date(n * 1000).toLocaleString(locale.value) : '—'
}
</script>

<template>
  <div class="mx-auto max-w-full space-y-5 p-4 sm:p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">{{ t('catalog.title') }}</h1>
        <p class="text-sm text-gray-500 dark:text-gray-400">
          {{ t('catalog.description') }}
        </p>
      </div>
      <button
        type="button"
        class="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
        :disabled="store.scanning"
        @click="doScan"
      >
        {{ store.scanning ? t('catalog.scanning') : t('catalog.rescan') }}
      </button>
    </div>

    <!-- Dashboard -->
    <section class="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
      <div v-for="card in [
        { k: 'total', c: 'text-gray-900 dark:text-white' },
        { k: 'photos', c: 'text-indigo-600 dark:text-indigo-400' },
        { k: 'videos', c: 'text-fuchsia-600 dark:text-fuchsia-400' },
        { k: 'approved', c: 'text-emerald-600 dark:text-emerald-400' },
        { k: 'pending', c: 'text-amber-600 dark:text-amber-400' },
        { k: 'review', c: 'text-sky-600 dark:text-sky-400' },
        { k: 'with_gps', c: 'text-teal-600 dark:text-teal-400' },
        { k: 'no_gps', c: 'text-gray-500 dark:text-gray-400' },
        { k: 'with_suggestion', c: 'text-violet-600 dark:text-violet-400' },
        { k: 'no_info', c: 'text-rose-600 dark:text-rose-400' },
        { k: 'hidden', c: 'text-gray-500 dark:text-gray-400' }
      ]" :key="card.k" class="rounded-lg border border-gray-200 bg-white p-3 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
        <p class="text-2xl font-bold" :class="card.c">{{ (store.stats as any)[card.k] }}</p>
        <p class="text-xs text-gray-500 dark:text-gray-400">{{ t('catalog.stats.' + card.k) }}</p>
      </div>
    </section>

    <!-- Progress -->
    <section class="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
      <div class="mb-2 flex items-center justify-between text-sm">
        <span class="font-semibold text-gray-900 dark:text-white">
          {{ t('catalog.approvedProgress', { approved: store.stats.approved, total: store.stats.total }) }}
        </span>
        <span class="text-gray-500 dark:text-gray-400">{{ store.stats.approval_pct }}%</span>
      </div>
      <div class="h-2.5 w-full overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
        <div class="h-full rounded-full bg-emerald-500 transition-all" :style="{ width: `${store.stats.approval_pct}%` }"></div>
      </div>
    </section>

    <div v-if="store.error" class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
      {{ store.error }}
    </div>

    <!-- Ajustes do catálogo (sincronização foi movida para Agendador → Dropbox) -->
    <section class="flex flex-wrap gap-5 rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
      <label class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
        <input type="checkbox" :checked="store.settings.geocode_enabled" @change="toggleGeocode(($event.target as HTMLInputElement).checked)" />
        {{ t('catalog.geocodeToggle') }}
      </label>
      <label class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
        <input type="checkbox" :checked="store.settings.show_unapproved_on_hdmi" @change="toggleUnapproved(($event.target as HTMLInputElement).checked)" />
        {{ t('catalog.showUnapprovedToggle') }}
      </label>
    </section>

    <!-- Filters -->
    <section class="space-y-3 rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
      <div class="flex flex-wrap gap-1.5">
        <button v-for="f in PRIMARY" :key="f" type="button"
          class="rounded-full px-3 py-1 text-xs font-medium transition-colors"
          :class="primary === f ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-200'"
          @click="primary = f">{{ t('catalog.filters.' + f) }}</button>
      </div>
      <div class="flex flex-wrap items-center gap-1.5">
        <span class="text-xs text-gray-400">{{ t('catalog.combine') }}</span>
        <button v-for="f in EXTRAS" :key="f" type="button"
          class="rounded-full border px-2.5 py-1 text-xs font-medium transition-colors"
          :class="extras.has(f) ? 'border-indigo-500 bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300' : 'border-gray-300 text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-300'"
          @click="toggleExtra(f)">{{ t('catalog.filters.' + f) }}</button>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <input v-model="search" type="search" :placeholder="t('catalog.searchPlaceholder')"
          class="w-56 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
        <input v-model.number="year" type="number" :placeholder="t('catalog.year')" min="1990" max="2100"
          class="w-24 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
        <select v-model="sort" class="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
          <option v-for="s in SORTS" :key="s" :value="s">{{ t('catalog.sorts.' + s) }}</option>
        </select>
        <select v-model.number="perPage" class="rounded-lg border border-gray-300 bg-white px-2 py-2 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
          <option :value="25">25</option><option :value="50">50</option><option :value="100">100</option>
        </select>
      </div>
    </section>

    <!-- Batch bar -->
    <section v-if="selectionCount > 0"
      class="sticky top-16 z-20 flex flex-wrap items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 p-3 shadow-sm dark:border-indigo-500/30 dark:bg-indigo-500/15">
      <span class="text-sm font-semibold text-indigo-800 dark:text-indigo-200">
        {{ t('catalog.selectedCount', { n: selectionCount }) }}
        <span v-if="selectAllResults" class="font-normal">{{ t('catalog.allFilterResults') }}</span>
      </span>
      <button type="button" class="rounded bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-emerald-700" @click="openBatchDescription">{{ t('catalog.batch.setDescription') }}</button>
      <button type="button" class="rounded bg-indigo-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-700" @click="runBatch('approve_suggestion')">{{ t('catalog.batch.approveSuggestions') }}</button>
      <button type="button" class="rounded bg-sky-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-sky-700" @click="runBatch('mark_review')">{{ t('catalog.actions.review') }}</button>
      <button type="button" class="rounded bg-gray-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-gray-700" @click="runBatch('hide')">{{ t('catalog.batch.hide') }}</button>
      <button type="button" class="rounded bg-gray-500 px-2.5 py-1 text-xs font-medium text-white hover:bg-gray-600" @click="runBatch('show')">{{ t('catalog.batch.show') }}</button>
      <button type="button" class="ml-auto rounded px-2.5 py-1 text-xs font-medium text-indigo-700 underline dark:text-indigo-300" @click="clearSelection">{{ t('catalog.clear') }}</button>
    </section>

    <!-- Table -->
    <section class="rounded-lg border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
      <div class="flex items-center gap-3 border-b border-gray-200 px-3 py-2 text-xs dark:border-gray-700">
        <button type="button" class="font-medium text-indigo-600 hover:underline dark:text-indigo-400" @click="selectPage">{{ t('catalog.selectPage') }}</button>
        <button type="button" class="font-medium text-indigo-600 hover:underline dark:text-indigo-400" @click="selectAll">{{ t('catalog.selectAllResults', { n: store.total }) }}</button>
      </div>
      <table class="w-full text-left text-sm">
        <thead class="sticky top-14 z-20 bg-gray-50 text-xs uppercase text-gray-500 shadow-sm dark:bg-gray-900 dark:text-gray-400">
          <tr>
            <th class="w-8 p-2"></th>
            <th class="w-16 p-2">{{ t('catalog.columns.thumb') }}</th>
            <th class="p-2">{{ t('catalog.columns.name') }}</th>
            <th class="p-2">{{ t('catalog.columns.type') }}</th>
            <th class="p-2">{{ t('catalog.columns.date') }}</th>
            <th class="p-2">{{ t('catalog.columns.gps') }}</th>
            <th class="p-2">{{ t('catalog.columns.suggestion') }}</th>
            <th class="p-2">{{ t('catalog.columns.description') }}</th>
            <th class="p-2">{{ t('catalog.columns.status') }}</th>
            <th class="p-2">{{ t('catalog.columns.slideshow') }}</th>
            <th class="p-2">{{ t('catalog.columns.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="it in store.items" :key="it.rel_path" class="border-t border-gray-100 align-middle dark:border-gray-700/60">
            <td class="p-2"><input type="checkbox" :checked="selected.has(it.rel_path) || selectAllResults" @change="toggleRow(it.rel_path)" /></td>
            <td class="p-2">
              <div class="relative h-12 w-12">
                <img :src="store.thumbUrl(it.rel_path, it.manual_rotation)" loading="lazy"
                  class="h-12 w-12 rounded bg-gray-100 object-cover dark:bg-gray-700" alt=""
                  @error="($event.target as HTMLImageElement).style.visibility='hidden'" />
                <span v-if="it.media_type === 'video'"
                  class="absolute inset-0 flex items-center justify-center text-white drop-shadow">
                  <span class="rounded-full bg-black/50 px-1 text-[10px]">▶</span>
                </span>
              </div>
            </td>
            <td class="max-w-[180px] truncate p-2 font-mono text-xs" :title="it.rel_path">{{ it.filename }}</td>
            <td class="p-2 text-xs">{{ it.media_type === 'video' ? t('catalog.type.video') : t('catalog.type.photo') }}</td>
            <td class="p-2 text-xs">{{ fmtDate(it.capture_date) }}</td>
            <td class="p-2 text-xs">{{ fmtGps(it) }}</td>
            <td class="max-w-[140px] p-2 text-xs">
              <span v-if="it.suggestion" class="text-gray-700 dark:text-gray-300">{{ it.suggestion }}</span>
              <span v-else class="italic text-gray-400">{{ t('catalog.notFound') }}</span>
              <span v-if="it.suggestion_source && it.suggestion_source !== 'none'" class="ml-1 text-[10px] text-gray-400">({{ it.suggestion_source }})</span>
            </td>
            <td class="p-2">
              <input v-model="drafts[it.rel_path]" type="text" placeholder="—"
                class="w-40 rounded border border-gray-300 bg-white px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            </td>
            <td class="p-2"><span class="rounded-full px-2 py-0.5 text-[11px] font-semibold" :class="statusChip[it.status]">{{ t('catalog.status.' + it.status) }}</span></td>
            <td class="p-2 text-center">
              <input type="checkbox" class="h-4 w-4 cursor-pointer accent-emerald-600"
                :checked="it.visible === 1"
                :title="it.visible === 1 ? t('catalog.visibleTitle') : t('catalog.hiddenTitle')"
                @change="toggleVisible(it)" />
            </td>
            <td class="p-2">
              <div class="flex gap-1">
                <button type="button" class="rounded bg-emerald-600 px-2 py-1 text-[11px] text-white hover:bg-emerald-700" @click="approveRow(it)">{{ t('catalog.actions.approve') }}</button>
                <button v-if="it.suggestion" type="button" class="rounded bg-indigo-600 px-2 py-1 text-[11px] text-white hover:bg-indigo-700" @click="acceptSuggestion(it)">{{ t('catalog.actions.accept') }}</button>
                <button type="button" class="rounded bg-sky-600 px-2 py-1 text-[11px] text-white hover:bg-sky-700" @click="markReview(it)">{{ t('catalog.actions.review') }}</button>
                <button type="button" class="rounded bg-amber-600 px-2 py-1 text-[11px] text-white hover:bg-amber-700" @click="openRotate(it)" :title="t('catalog.actions.rotateTitle')">{{ t('catalog.actions.rotate') }}<span v-if="it.manual_rotation" class="ml-0.5">({{ it.manual_rotation }}°)</span></button>
                <button type="button" class="rounded bg-gray-500 px-2 py-1 text-[11px] text-white hover:bg-gray-600" @click="openHistory(it)">{{ t('catalog.actions.history') }}</button>
              </div>
            </td>
          </tr>
          <tr v-if="!store.items.length">
            <td colspan="11" class="p-8 text-center text-sm text-gray-400">{{ t('catalog.empty') }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- Pagination -->
    <div class="flex items-center justify-between text-sm">
      <span class="text-gray-500 dark:text-gray-400">{{ t('catalog.pageInfo', { total: store.total, page, pages: totalPages }) }}</span>
      <div class="flex gap-2">
        <button type="button" class="rounded border border-gray-300 px-3 py-1 disabled:opacity-50 dark:border-gray-600" :disabled="page <= 1" @click="page--">{{ t('catalog.prev') }}</button>
        <button type="button" class="rounded border border-gray-300 px-3 py-1 disabled:opacity-50 dark:border-gray-600" :disabled="page >= totalPages" @click="page++">{{ t('catalog.next') }}</button>
      </div>
    </div>

    <!-- História modal -->
    <div v-if="showHistoryModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showHistoryModal = false">
      <div class="w-full max-w-lg space-y-3 rounded-xl bg-white p-5 shadow-xl dark:bg-gray-800">
        <h3 class="text-lg font-bold text-gray-900 dark:text-white">{{ t('catalog.history.title') }} — <span class="font-mono text-sm">{{ historyFile }}</span></h3>
        <div class="max-h-96 overflow-y-auto">
          <ol v-if="historyItems.length" class="space-y-2">
            <li v-for="(h, i) in historyItems" :key="i" class="border-l-2 border-indigo-300 pl-3 text-sm dark:border-indigo-500/40">
              <div class="text-xs text-gray-400">{{ fmtTs((h as any).ts) }} · {{ (h as any).origin }}</div>
              <div class="text-gray-800 dark:text-gray-200">
                {{ eventLabel((h as any).event) }}
                <span v-if="(h as any).old_value || (h as any).new_value" class="text-gray-500">
                  — {{ (h as any).old_value ? `"${(h as any).old_value}" → ` : '' }}"{{ (h as any).new_value }}"
                </span>
                <span v-if="(h as any).batch_id" class="ml-1 rounded bg-gray-100 px-1 text-[10px] text-gray-500 dark:bg-gray-700">{{ t('catalog.history.batch') }}</span>
              </div>
            </li>
          </ol>
          <p v-else class="text-sm text-gray-400">{{ t('catalog.history.empty') }}</p>
        </div>
        <div class="flex justify-end">
          <button type="button" class="rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700" @click="showHistoryModal = false">{{ t('common.close') }}</button>
        </div>
      </div>
    </div>

    <!-- Batch description modal -->
    <div v-if="showBatchModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showBatchModal = false">
      <div class="w-full max-w-md space-y-4 rounded-xl bg-white p-5 shadow-xl dark:bg-gray-800">
        <h3 class="text-lg font-bold text-gray-900 dark:text-white">{{ t('catalog.batch.modalTitle') }}</h3>
        <input v-model="batchDesc" type="text" :placeholder="t('catalog.batch.placeholder')"
          class="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
        <label class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
          <input v-model="overwriteApproved" type="checkbox" /> {{ t('catalog.batch.overwriteApproved') }}
        </label>
        <div v-if="preview" class="rounded-lg bg-gray-50 p-3 text-xs text-gray-600 dark:bg-gray-900/40 dark:text-gray-300">
          <div>{{ t('catalog.batch.selected') }}: <b>{{ preview.selected }}</b></div>
          <div>{{ t('catalog.batch.alreadyApproved') }}: <b>{{ preview.already_approved }}</b></div>
          <div>{{ t('catalog.batch.pending') }}: <b>{{ preview.pending }}</b></div>
          <div>{{ t('catalog.batch.willChange') }}: <b>{{ preview.will_change }}</b></div>
          <div>{{ t('catalog.batch.ignoredProtected') }}: <b>{{ preview.ignored_protected }}</b></div>
        </div>
        <div class="flex justify-end gap-2">
          <button type="button" class="rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700" @click="showBatchModal = false">{{ t('common.cancel') }}</button>
          <button type="button" class="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50" :disabled="!batchDesc.trim()" @click="confirmBatchDescription">{{ t('catalog.batch.apply') }}</button>
        </div>
      </div>
    </div>

    <!-- Rotacionar (rotação manual não destrutiva) -->
    <div v-if="showRotateModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showRotateModal = false">
      <div class="w-full max-w-md rounded-2xl bg-white p-5 shadow-xl dark:bg-gray-800">
        <h3 class="text-lg font-bold text-gray-900 dark:text-white">{{ t('catalog.actions.rotate') }} — <span class="font-mono text-sm">{{ rotateItemRef?.filename }}</span></h3>
        <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">{{ t('catalog.rotateModal.hint') }}</p>
        <div class="mt-4 flex h-56 items-center justify-center overflow-hidden rounded-lg bg-gray-100 dark:bg-gray-900">
          <img v-if="rotateItemRef" :src="store.thumbUrl(rotateItemRef.rel_path, rotateSaved)"
            class="max-h-48 max-w-[90%] object-contain transition-transform duration-200"
            :style="{ transform: 'rotate(' + rotatePreviewDelta + 'deg)' }" alt="" />
        </div>
        <div class="mt-3 text-center text-xs text-gray-500 dark:text-gray-400">
          {{ t('catalog.rotateModal.rotation') }}: <strong>{{ rotatePreview }}°</strong>
          <span v-if="rotatePreview !== rotateSaved"> {{ t('catalog.rotateModal.currentSaved', { deg: rotateSaved }) }}</span>
        </div>
        <div class="mt-4 grid grid-cols-2 gap-2">
          <button type="button" class="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-700" @click="rotateBy(270)">↺ {{ t('catalog.rotateModal.left') }}</button>
          <button type="button" class="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-700" @click="rotateBy(90)">↻ {{ t('catalog.rotateModal.right') }}</button>
          <button type="button" class="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-700" @click="rotateBy(180)">180°</button>
          <button type="button" class="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-200 dark:hover:bg-gray-700" @click="rotateAuto">{{ t('catalog.rotateModal.auto') }}</button>
        </div>
        <div class="mt-5 flex justify-end gap-2">
          <button type="button" class="rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700" @click="showRotateModal = false">{{ t('common.cancel') }}</button>
          <button type="button" class="rounded-lg bg-amber-600 px-3 py-2 text-sm font-semibold text-white hover:bg-amber-700 disabled:opacity-50" :disabled="rotateSaving || rotatePreview === rotateSaved" @click="confirmRotate">{{ t('catalog.rotateModal.confirm') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
