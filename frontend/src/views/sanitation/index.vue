<template>
  <section class="page" data-module="sanitation">
    <header class="page-head">
      <div>
        <h2>车辆消杀管理</h2>
        <p class="page-desc">维护消杀记录，按编号、车辆、方式、区域定位；看板、明细与车辆归属视图共用同一份数据。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记消杀记录</button>
        <button class="btn" type="button" @click="exportRows">导出车辆消杀清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in statCards" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="tabs">
      <button :class="['tab', { active: view === 'list' }]" type="button" @click="switchView('list')">消杀明细</button>
      <button :class="['tab', { active: view === 'vehicle' }]" type="button" @click="switchView('vehicle')">车辆归属</button>
    </div>

    <form class="filter-bar" @submit.prevent="submitFilters">
      <label v-for="field in filterFields" :key="field.key" class="filter-item">
        <span>{{ field.label }}</span>
        <input v-model="filters[field.key]" :placeholder="`按${field.label}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <!-- 消杀明细列表 -->
    <table v-if="view === 'list'" class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>版本</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.version ?? 1 }}</td>
          <td class="row-actions">
            <button v-for="action in actions" :key="action" class="link" type="button" @click="runAction(action, row)">{{ action }}</button>
            <button class="link" type="button" @click="openDetail(row)">详情</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无车辆消杀数据，可先登记消杀记录</td>
        </tr>
      </tbody>
    </table>

    <!-- 车辆归属视图：与明细同源，按车辆编号分组 -->
    <div v-else class="vehicle-view">
      <div v-for="group in vehicleGroups" :key="group.车辆编号" class="vehicle-group">
        <h3 class="vehicle-group-head">
          <span class="vehicle-name">{{ group.车辆编号 }}</span>
          <span class="vehicle-count">{{ group.count }} 条消杀记录</span>
        </h3>
        <table class="data-table">
          <thead>
            <tr>
              <th v-for="column in columns" :key="column">{{ column }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in group.items" :key="String(row.id)">
              <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="!vehicleGroups.length" class="empty-state">暂无车辆归属数据</div>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条车辆消杀记录（已去重）</span>
      <span class="pagination">
        <button class="btn" type="button" :disabled="page <= 1" @click="prevPage">上一页</button>
        <span>第 {{ page }} 页 / 每页 {{ size }} 条</span>
        <button class="btn" type="button" :disabled="rows.length < size" @click="nextPage">下一页</button>
      </span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 明细弹窗：同一条消杀记录 + 归属修正 -->
    <div v-if="detail" class="modal-mask" @click.self="closeDetail">
      <div class="modal">
        <header class="modal-head">
          <h3>消杀记录明细</h3>
          <button class="link" type="button" @click="closeDetail">关闭</button>
        </header>
        <dl class="detail-grid">
          <div v-for="column in columns" :key="column" class="detail-item">
            <dt>{{ column }}</dt>
            <dd>{{ detail[column] ?? '—' }}</dd>
          </div>
          <div class="detail-item">
            <dt>版本</dt>
            <dd>{{ detail.version ?? 1 }}</dd>
          </div>
        </dl>
        <form class="attribution-form" @submit.prevent="submitAttribution">
          <h4>修正车辆归属</h4>
          <label class="filter-item">
            <span>车辆编号</span>
            <input v-model="attributionForm.vehicle" placeholder="输入归属车辆编号" />
          </label>
          <button class="btn primary" type="submit">提交修正</button>
          <span v-if="attributionError" class="error-text">{{ attributionError }}</span>
          <span v-if="attributionSuccess" class="success-text">{{ attributionSuccess }}</span>
        </form>
      </div>
    </div>

    <!-- 登记弹窗：同一消杀编号重复提交不生成副本 -->
    <div v-if="createVisible" class="modal-mask" @click.self="closeCreate">
      <div class="modal">
        <header class="modal-head">
          <h3>登记消杀记录</h3>
          <button class="link" type="button" @click="closeCreate">关闭</button>
        </header>
        <form class="create-form" @submit.prevent="submitCreate">
          <label v-for="field in createFields" :key="field" class="filter-item">
            <span>{{ field }}</span>
            <input v-model="createForm[field]" :placeholder="`请输入${field}`" />
          </label>
          <button class="btn primary" type="submit">提交登记</button>
          <span v-if="createError" class="error-text">{{ createError }}</span>
        </form>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>
type Stats = { total: number; pending: number; done: number; recheck: number; monthly: number }
type VehicleGroup = { 车辆编号: string; count: number; items: Row[] }

const ENDPOINT = '/api/sanitation'
const columns = ["消杀编号", "车辆编号", "消杀方式", "消毒剂名称", "消杀区域", "操作人员", "消杀日期", "消杀状态"]
const actions = ["执行消杀", "安排复消"]
const filterFields = [
  { key: 'keyword', label: '消杀编号' },
  { key: 'vehicle', label: '车辆编号' },
  { key: 'method', label: '消杀方式' },
  { key: 'area', label: '消杀区域' },
]
const createFields = ["消杀编号", "车辆编号", "消杀方式", "消毒剂名称", "消杀区域", "操作人员", "消杀日期"]

const view = ref<'list' | 'vehicle'>('list')
const rows = ref<Row[]>([])
const vehicleGroups = ref<VehicleGroup[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const stats = ref<Stats>({ total: 0, pending: 0, done: 0, recheck: 0, monthly: 0 })
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})

const detail = ref<Row | null>(null)
const attributionForm = ref({ vehicle: '' })
const attributionError = ref('')
const attributionSuccess = ref('')

const createVisible = ref(false)
const createForm = ref<Record<string, string>>({})
const createError = ref('')

const statCards = computed(() => [
  { label: '待消杀车辆', value: stats.value.pending },
  { label: '已消杀车辆', value: stats.value.done },
  { label: '本月消杀数', value: stats.value.monthly },
])

function buildQuery(): string {
  const params = new URLSearchParams()
  for (const field of filterFields) {
    const value = filters.value[field.key]
    if (value && value.trim()) params.set(field.key, value.trim())
  }
  return params.toString()
}

async function reloadStats() {
  const response = await request(`${ENDPOINT}/stats?${buildQuery()}`)
  if (!response.ok) throw new Error('看板统计读取失败')
  stats.value = await response.json()
}

async function reloadList() {
  const params = new URLSearchParams(buildQuery())
  params.set('page', String(page.value))
  params.set('size', String(size.value))
  const response = await request(`${ENDPOINT}?${params.toString()}`)
  if (!response.ok) throw new Error('消杀记录列表读取失败')
  const payload = await response.json()
  rows.value = payload.items ?? []
  total.value = payload.total ?? rows.value.length
}

async function reloadVehicle() {
  const response = await request(`${ENDPOINT}/by-vehicle?${buildQuery()}`)
  if (!response.ok) throw new Error('车辆归属视图读取失败')
  const payload = await response.json()
  vehicleGroups.value = payload.groups ?? []
}

async function reloadAll() {
  errorMessage.value = ''
  try {
    await Promise.all([reloadStats(), reloadList(), reloadVehicle()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '数据读取失败'
  }
}

function switchView(mode: 'list' | 'vehicle') {
  view.value = mode
}

function submitFilters() {
  page.value = 1
  void reloadAll()
}

function resetFilters() {
  filters.value = {}
  page.value = 1
  void reloadAll()
}

function exportRows() {
  window.open(`${ENDPOINT}/export?${buildQuery()}`, '_blank')
}

function prevPage() {
  if (page.value > 1) {
    page.value -= 1
    void reloadList()
  }
}

function nextPage() {
  if (rows.value.length >= size.value) {
    page.value += 1
    void reloadList()
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '车辆消杀动作未生效，请稍后重试')
    }
    await reloadAll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '车辆消杀操作失败'
  }
}

async function openDetail(row: Row) {
  errorMessage.value = ''
  attributionError.value = ''
  attributionSuccess.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) throw new Error('消杀记录明细读取失败')
    const data = await response.json()
    detail.value = data
    attributionForm.value.vehicle = data['车辆编号'] ?? ''
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '明细读取失败'
  }
}

function closeDetail() {
  detail.value = null
}

async function submitAttribution() {
  const current = detail.value
  if (!current) return
  attributionError.value = ''
  attributionSuccess.value = ''
  try {
    const response = await request(`${ENDPOINT}/${current.id}/attribution`, {
      method: 'PATCH',
      body: JSON.stringify({
        values: {
          车辆编号: attributionForm.value.vehicle,
          version: current.version ?? 1,
        },
      }),
    })
    if (response.status === 409) {
      const payload = await response.json().catch(() => ({}))
      attributionError.value = (payload as { detail?: string }).detail ?? '记录已被他人修正，请刷新后重试'
      await openDetail(current)
      return
    }
    if (!response.ok) throw new Error('归属修正未生效')
    const payload = await response.json()
    attributionSuccess.value = payload.message ?? '归属已修正'
    detail.value = payload.entry
    await reloadAll()
  } catch (error) {
    attributionError.value = error instanceof Error ? error.message : '归属修正失败'
  }
}

function openCreate() {
  createError.value = ''
  createForm.value = {}
  createVisible.value = true
}

function closeCreate() {
  createVisible.value = false
}

async function submitCreate() {
  createError.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: createForm.value }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      createError.value = payload.message ?? '消杀记录登记失败'
      return
    }
    closeCreate()
    await reloadAll()
  } catch (error) {
    createError.value = error instanceof Error ? error.message : '登记失败'
  }
}

onMounted(reloadAll)
</script>

<style scoped>
.tabs { display: flex; gap: 4px; margin-bottom: 12px; border-bottom: 1px solid var(--border); }
.tab { border: none; background: none; padding: 8px 14px; cursor: pointer; color: var(--muted); font-size: 13px; border-bottom: 2px solid transparent; }
.tab.active { color: var(--brand); border-bottom-color: var(--brand); }
.pagination { display: inline-flex; align-items: center; gap: 8px; }
.pagination .btn { padding: 2px 8px; }
.vehicle-view { display: flex; flex-direction: column; gap: 16px; }
.vehicle-group-head { display: flex; align-items: baseline; gap: 10px; margin: 0 0 6px; font-size: 14px; }
.vehicle-name { font-weight: 600; }
.vehicle-count { color: var(--muted); font-size: 12px; }
.modal-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: center; justify-content: center; z-index: 50; }
.modal { background: #fff; border-radius: 10px; padding: 18px 20px; width: 560px; max-width: 92vw; max-height: 88vh; overflow-y: auto; }
.modal-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
.modal-head h3 { margin: 0; font-size: 16px; }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; margin: 0 0 16px; }
.detail-item dt { color: var(--muted); font-size: 12px; }
.detail-item dd { margin: 2px 0 0; font-size: 13px; }
.attribution-form, .create-form { display: flex; flex-direction: column; gap: 10px; border-top: 1px solid var(--border); padding-top: 12px; }
.attribution-form h4 { margin: 0; font-size: 14px; }
.attribution-form .btn, .create-form .btn { align-self: flex-start; }
.success-text { color: #15803d; font-size: 12px; }
</style>
