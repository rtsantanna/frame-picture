<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useCatalogStore, type CatalogItem } from '../stores/catalog'

const store = useCatalogStore()

const PRIMARY = [
  { id: 'all', label: 'Todos' },
  { id: 'pending', label: 'Pendentes' },
  { id: 'approved', label: 'Aprovados' },
  { id: 'auto_location', label: 'Localidade automática' },
  { id: 'with_suggestion', label: 'Com sugestão' },
  { id: 'no_info', label: 'Sem informação' },
  { id: 'review', label: 'Revisar' },
  { id: 'hidden', label: 'Ocultos' }
]
const EXTRAS = [
  { id: 'with_gps', label: 'Com GPS' },
  { id: 'no_gps', label: 'Sem GPS' },
  { id: 'photos', label: 'Fotos' },
  { id: 'videos', label: 'Vídeos' },
  { id: 'visible', label: 'Visíveis' },
  { id: 'with_date', label: 'Com data' },
  { id: 'no_date', label: 'Sem data' },
  { id: 'edited', label: 'Editados' }
]
const SORTS = [
  { id: 'date_desc', label: 'Data (mais recente)' },
  { id: 'date_asc', label: 'Data (mais antiga)' },
  { id: 'name_asc', label: 'Nome (A-Z)' },
  { id: 'name_desc', label: 'Nome (Z-A)' },
  { id: 'status', label: 'Status' }
]

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

onMounted(() => { refreshAll(); store.fetchSettings() })

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
const statusLabel: Record<string, string> = { approved: 'Aprovado', pending: 'Pendente', review: 'Revisar' }
</script>

<template>
  <div class="mx-auto max-w-[1400px] space-y-5 p-4 sm:p-6">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-2xl font-bold text-gray-900 dark:text-white">Catálogo de Memórias</h1>
        <p class="text-sm text-gray-500 dark:text-gray-400">
          Organize, identifique, aprove e controle suas fotos e vídeos.
        </p>
      </div>
      <button
        type="button"
        class="inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-60 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-200"
        :disabled="store.scanning"
        @click="doScan"
      >
        {{ store.scanning ? 'Analisando…' : 'Reanalisar biblioteca' }}
      </button>
    </div>

    <!-- Dashboard -->
    <section class="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
      <div v-for="card in [
        { k: 'total', label: 'Mídias', c: 'text-gray-900 dark:text-white' },
        { k: 'photos', label: 'Fotos', c: 'text-indigo-600 dark:text-indigo-400' },
        { k: 'videos', label: 'Vídeos', c: 'text-fuchsia-600 dark:text-fuchsia-400' },
        { k: 'approved', label: 'Aprovadas', c: 'text-emerald-600 dark:text-emerald-400' },
        { k: 'pending', label: 'Pendentes', c: 'text-amber-600 dark:text-amber-400' },
        { k: 'review', label: 'Revisar', c: 'text-sky-600 dark:text-sky-400' },
        { k: 'with_gps', label: 'Com GPS', c: 'text-teal-600 dark:text-teal-400' },
        { k: 'no_gps', label: 'Sem GPS', c: 'text-gray-500 dark:text-gray-400' },
        { k: 'with_suggestion', label: 'Com sugestão', c: 'text-violet-600 dark:text-violet-400' },
        { k: 'no_info', label: 'Sem informação', c: 'text-rose-600 dark:text-rose-400' },
        { k: 'hidden', label: 'Ocultas', c: 'text-gray-500 dark:text-gray-400' }
      ]" :key="card.k" class="rounded-lg border border-gray-200 bg-white p-3 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
        <p class="text-2xl font-bold" :class="card.c">{{ (store.stats as any)[card.k] }}</p>
        <p class="text-xs text-gray-500 dark:text-gray-400">{{ card.label }}</p>
      </div>
    </section>

    <!-- Progress -->
    <section class="rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
      <div class="mb-2 flex items-center justify-between text-sm">
        <span class="font-semibold text-gray-900 dark:text-white">
          {{ store.stats.approved }} de {{ store.stats.total }} memórias aprovadas
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

    <!-- Filters -->
    <section class="space-y-3 rounded-lg border border-gray-200 bg-white p-4 shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
      <div class="flex flex-wrap gap-1.5">
        <button v-for="f in PRIMARY" :key="f.id" type="button"
          class="rounded-full px-3 py-1 text-xs font-medium transition-colors"
          :class="primary === f.id ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-200'"
          @click="primary = f.id">{{ f.label }}</button>
      </div>
      <div class="flex flex-wrap items-center gap-1.5">
        <span class="text-xs text-gray-400">Combinar:</span>
        <button v-for="f in EXTRAS" :key="f.id" type="button"
          class="rounded-full border px-2.5 py-1 text-xs font-medium transition-colors"
          :class="extras.has(f.id) ? 'border-indigo-500 bg-indigo-50 text-indigo-700 dark:bg-indigo-500/10 dark:text-indigo-300' : 'border-gray-300 text-gray-600 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-300'"
          @click="toggleExtra(f.id)">{{ f.label }}</button>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <input v-model="search" type="search" placeholder="Pesquisar nome/descrição…"
          class="w-56 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
        <input v-model.number="year" type="number" placeholder="Ano" min="1990" max="2100"
          class="w-24 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
        <select v-model="sort" class="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white">
          <option v-for="s in SORTS" :key="s.id" :value="s.id">{{ s.label }}</option>
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
        {{ selectionCount }} selecionada(s)
        <span v-if="selectAllResults" class="font-normal">(todos os resultados do filtro)</span>
      </span>
      <button type="button" class="rounded bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-emerald-700" @click="openBatchDescription">Definir descrição</button>
      <button type="button" class="rounded bg-indigo-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-indigo-700" @click="runBatch('approve_suggestion')">Aprovar sugestões</button>
      <button type="button" class="rounded bg-sky-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-sky-700" @click="runBatch('mark_review')">Revisar</button>
      <button type="button" class="rounded bg-gray-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-gray-700" @click="runBatch('hide')">Ocultar</button>
      <button type="button" class="rounded bg-gray-500 px-2.5 py-1 text-xs font-medium text-white hover:bg-gray-600" @click="runBatch('show')">Reexibir</button>
      <button type="button" class="ml-auto rounded px-2.5 py-1 text-xs font-medium text-indigo-700 underline dark:text-indigo-300" @click="clearSelection">Limpar</button>
    </section>

    <!-- Table -->
    <section class="overflow-x-auto rounded-lg border border-gray-200 bg-white shadow-sm dark:border-gray-700 dark:bg-gray-800/90">
      <div class="flex items-center gap-3 border-b border-gray-200 px-3 py-2 text-xs dark:border-gray-700">
        <button type="button" class="font-medium text-indigo-600 hover:underline dark:text-indigo-400" @click="selectPage">Selecionar página</button>
        <button type="button" class="font-medium text-indigo-600 hover:underline dark:text-indigo-400" @click="selectAll">Selecionar todos os {{ store.total }} resultados</button>
      </div>
      <table class="w-full text-left text-sm">
        <thead class="bg-gray-50 text-xs uppercase text-gray-500 dark:bg-gray-900/40 dark:text-gray-400">
          <tr>
            <th class="w-8 p-2"></th>
            <th class="w-16 p-2">Thumb</th>
            <th class="p-2">Nome</th>
            <th class="p-2">Tipo</th>
            <th class="p-2">Data</th>
            <th class="p-2">GPS</th>
            <th class="p-2">Sugestão</th>
            <th class="p-2">Descrição aprovada</th>
            <th class="p-2">Status</th>
            <th class="p-2">Slideshow</th>
            <th class="p-2">Ações</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="it in store.items" :key="it.rel_path" class="border-t border-gray-100 align-middle dark:border-gray-700/60">
            <td class="p-2"><input type="checkbox" :checked="selected.has(it.rel_path) || selectAllResults" @change="toggleRow(it.rel_path)" /></td>
            <td class="p-2">
              <img v-if="it.media_type === 'photo'" :src="store.thumbUrl(it.rel_path)" loading="lazy"
                class="h-12 w-12 rounded object-cover" alt="" />
              <div v-else class="flex h-12 w-12 items-center justify-center rounded bg-gray-100 text-lg dark:bg-gray-700">🎬</div>
            </td>
            <td class="max-w-[180px] truncate p-2 font-mono text-xs" :title="it.rel_path">{{ it.filename }}</td>
            <td class="p-2 text-xs">{{ it.media_type === 'video' ? 'Vídeo' : 'Foto' }}</td>
            <td class="p-2 text-xs">{{ fmtDate(it.capture_date) }}</td>
            <td class="p-2 text-xs">{{ fmtGps(it) }}</td>
            <td class="max-w-[140px] p-2 text-xs">
              <span v-if="it.suggestion" class="text-gray-700 dark:text-gray-300">{{ it.suggestion }}</span>
              <span v-else class="italic text-gray-400">Dado não encontrado</span>
              <span v-if="it.suggestion_source && it.suggestion_source !== 'none'" class="ml-1 text-[10px] text-gray-400">({{ it.suggestion_source }})</span>
            </td>
            <td class="p-2">
              <input v-model="drafts[it.rel_path]" type="text" placeholder="—"
                class="w-40 rounded border border-gray-300 bg-white px-2 py-1 text-xs dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
            </td>
            <td class="p-2"><span class="rounded-full px-2 py-0.5 text-[11px] font-semibold" :class="statusChip[it.status]">{{ statusLabel[it.status] }}</span></td>
            <td class="p-2">
              <button type="button" class="text-xs font-medium" :class="it.visible === 1 ? 'text-emerald-600' : 'text-gray-400'" @click="toggleVisible(it)">
                {{ it.visible === 1 ? 'ON' : 'OFF' }}
              </button>
            </td>
            <td class="p-2">
              <div class="flex gap-1">
                <button type="button" class="rounded bg-emerald-600 px-2 py-1 text-[11px] text-white hover:bg-emerald-700" @click="approveRow(it)">Aprovar</button>
                <button v-if="it.suggestion" type="button" class="rounded bg-indigo-600 px-2 py-1 text-[11px] text-white hover:bg-indigo-700" @click="acceptSuggestion(it)">Aceitar</button>
                <button type="button" class="rounded bg-sky-600 px-2 py-1 text-[11px] text-white hover:bg-sky-700" @click="markReview(it)">Revisar</button>
              </div>
            </td>
          </tr>
          <tr v-if="!store.items.length">
            <td colspan="11" class="p-8 text-center text-sm text-gray-400">Nenhuma mídia para este filtro.</td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- Pagination -->
    <div class="flex items-center justify-between text-sm">
      <span class="text-gray-500 dark:text-gray-400">{{ store.total }} mídia(s) · página {{ page }}/{{ totalPages }}</span>
      <div class="flex gap-2">
        <button type="button" class="rounded border border-gray-300 px-3 py-1 disabled:opacity-50 dark:border-gray-600" :disabled="page <= 1" @click="page--">Anterior</button>
        <button type="button" class="rounded border border-gray-300 px-3 py-1 disabled:opacity-50 dark:border-gray-600" :disabled="page >= totalPages" @click="page++">Próxima</button>
      </div>
    </div>

    <!-- Batch description modal -->
    <div v-if="showBatchModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" @click.self="showBatchModal = false">
      <div class="w-full max-w-md space-y-4 rounded-xl bg-white p-5 shadow-xl dark:bg-gray-800">
        <h3 class="text-lg font-bold text-gray-900 dark:text-white">Descrição em lote</h3>
        <input v-model="batchDesc" type="text" placeholder="Ex.: Cancun Xcaret 2013"
          class="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm dark:border-gray-600 dark:bg-gray-700 dark:text-white" />
        <label class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-300">
          <input v-model="overwriteApproved" type="checkbox" /> Também substituir descrições aprovadas
        </label>
        <div v-if="preview" class="rounded-lg bg-gray-50 p-3 text-xs text-gray-600 dark:bg-gray-900/40 dark:text-gray-300">
          <div>Selecionadas: <b>{{ preview.selected }}</b></div>
          <div>Já aprovadas: <b>{{ preview.already_approved }}</b></div>
          <div>Pendentes: <b>{{ preview.pending }}</b></div>
          <div>Serão alteradas: <b>{{ preview.will_change }}</b></div>
          <div>Ignoradas (protegidas): <b>{{ preview.ignored_protected }}</b></div>
        </div>
        <div class="flex justify-end gap-2">
          <button type="button" class="rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700" @click="showBatchModal = false">Cancelar</button>
          <button type="button" class="rounded-lg bg-emerald-600 px-3 py-2 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50" :disabled="!batchDesc.trim()" @click="confirmBatchDescription">Aplicar</button>
        </div>
      </div>
    </div>
  </div>
</template>
