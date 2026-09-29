<template>
  <section class="page" data-module="sanitation">
    <header class="page-head">
      <div>
        <h2>车辆消杀管理</h2>
        <p class="page-desc">维护消杀记录，围绕消杀编号、车辆编号、消杀方式、消杀区域做登记、定位与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记消杀记录</button>
        <button class="btn" type="button" @click="exportRows">导出车辆消杀清单</button>
      </div>
    </header>

    <!-- 消杀看板：数字全部来自 /stats，与列表、明细同源 -->
    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <div class="view-switch">
      <button
        class="btn"
        type="button"
        :class="{ primary: viewMode === 'list' }"
        @click="viewMode = 'list'"
      >明细列表</button>
      <button
        class="btn"
        type="button"
        :class="{ primary: viewMode === 'vehicle' }"
        @click="switchToVehicle"
      >车辆归属</button>
    </div>

    <form class="filter-bar" @submit.prevent="search">
      <label class="filter-item">
        <span>消杀编号</span>
        <input v-model="filters.code" placeholder="按消杀编号检索" />
      </label>
      <label class="filter-item">
        <span>车辆编号</span>
        <input v-model="filters.vehicle" placeholder="按车辆编号检索" />
      </label>
      <label class="filter-item">
        <span>消杀方式</span>
        <input v-model="filters.method" placeholder="按消杀方式检索" />
      </label>
      <label class="filter-item">
        <span>消杀区域</span>
        <input v-model="filters.area" placeholder="按消杀区域检索" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <!-- 明细列表 -->
    <table v-if="viewMode === 'list'" class="data-table">
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
          <td>v{{ row.version ?? 1 }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(row)">查看详情</button>
            <button class="link" type="button" @click="openReassign(row)">修正归属</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无符合条件的车辆消杀数据</td>
        </tr>
      </tbody>
    </table>

    <!-- 车辆归属视图：按车辆分组，数据与列表来自同一份消杀记录 -->
    <table v-else class="data-table">
      <thead>
        <tr>
          <th>车辆编号</th>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>版本</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="group in vehicleGroups" :key="group.vehicle">
          <tr class="group-row">
            <td :colspan="columns.length + 3">归属车辆 {{ group.vehicle }} · 共 {{ group.count }} 条消杀记录</td>
          </tr>
          <tr v-for="row in group.items" :key="`${group.vehicle}-${row.id}`">
            <td>{{ row['车辆编号'] }}</td>
            <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
            <td>v{{ row.version ?? 1 }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="openDetail(row)">查看详情</button>
              <button class="link" type="button" @click="openReassign(row)">修正归属</button>
            </td>
          </tr>
        </template>
        <tr v-if="!vehicleGroups.length">
          <td :colspan="columns.length + 3" class="empty-state">该车辆暂无消杀记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条消杀记录（已按消杀编号去重）</span>
      <span class="pager">
        <button class="btn" type="button" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
        第 {{ page }} 页
        <button class="btn" type="button" :disabled="page * size >= total" @click="changePage(page + 1)">下一页</button>
      </span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 详情：直接展示列表同一条记录 -->
    <div v-if="detail" class="modal-mask" @click.self="detail = null">
      <div class="modal">
        <h3>消杀记录详情</h3>
        <dl class="detail-list">
          <div v-for="column in columns" :key="column">
            <dt>{{ column }}</dt>
            <dd>{{ detail[column] ?? '—' }}</dd>
          </div>
          <div>
            <dt>记录版本</dt>
            <dd>v{{ detail.version ?? 1 }}</dd>
          </div>
        </dl>
        <div class="modal-actions">
          <button class="btn" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- 修正车辆归属（乐观锁：必须带上当前版本） -->
    <div v-if="reassignState.open" class="modal-mask" @click.self="reassignState.open = false">
      <div class="modal">
        <h3>修正车辆归属</h3>
        <p class="page-desc">消杀编号 {{ reassignState.code }}，当前版本 v{{ reassignState.version }}</p>
        <label class="filter-item">
          <span>车辆编号</span>
          <input v-model="reassignState.vehicle" placeholder="输入正确的车辆编号" />
        </label>
        <p v-if="reassignState.error" class="error-text">{{ reassignState.error }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="reassignState.open = false">取消</button>
          <button class="btn primary" type="button" :disabled="reassignState.saving" @click="submitReassign">提交修正</button>
        </div>
      </div>
    </div>

    <!-- 登记：同编号重复提交幂等返回，不会生成副本 -->
    <div v-if="createState.open" class="modal-mask" @click.self="createState.open = false">
      <div class="modal">
        <h3>登记消杀记录</h3>
        <label v-for="field in createFields" :key="field" class="filter-item">
          <span>{{ field }}</span>
          <input v-model="createState.form[field]" :placeholder="`请输入${field}`" />
        </label>
        <p v-if="createState.error" class="error-text">{{ createState.error }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="createState.open = false">取消</button>
          <button class="btn primary" type="button" :disabled="createState.saving" @click="submitCreate">提交登记</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null> & { id: number; version?: number }

const ENDPOINT = '/api/sanitation'
const columns = ["消杀编号", "车辆编号", "消杀方式", "消毒剂名称", "消杀区域", "操作人员", "消杀日期", "消杀状态"]
const createFields = ["消杀编号", "车辆编号", "消杀方式", "消毒剂名称", "消杀区域", "操作人员", "消杀日期"]
const actions = ["执行消杀", "安排复消"]

const rows = ref<Row[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const errorMessage = ref('')
const viewMode = ref<'list' | 'vehicle'>('list')
const vehicleGroups = ref<{ vehicle: string; count: number; items: Row[] }[]>([])
const stats = ref([
  { label: '待消杀车辆', value: 0 },
  { label: '已消杀车辆', value: 0 },
  { label: '本月消杀数', value: 0 },
  { label: '消杀记录总数', value: 0 },
])
const filters = reactive({ code: '', vehicle: '', method: '', area: '' })

const detail = ref<Row | null>(null)

const reassignState = reactive({
  open: false,
  saving: false,
  id: 0,
  code: '',
  vehicle: '',
  version: 1,
  error: '',
})

function emptyCreateForm() {
  return createFields.reduce<Record<string, string>>((acc, field) => {
    acc[field] = ''
    return acc
  }, {})
}

const createState = reactive({
  open: false,
  saving: false,
  form: emptyCreateForm(),
  error: '',
})

function buildQuery(extra: Record<string, string | number> = {}) {
  const params = new URLSearchParams()
  if (filters.code.trim()) params.set('code', filters.code.trim())
  if (filters.vehicle.trim()) params.set('vehicle', filters.vehicle.trim())
  if (filters.method.trim()) params.set('method', filters.method.trim())
  if (filters.area.trim()) params.set('area', filters.area.trim())
  for (const [key, value] of Object.entries(extra)) {
    if (value !== '' && value !== null && value !== undefined) {
      params.set(key, String(value))
    }
  }
  const query = params.toString()
  return query ? `?${query}` : ''
}

async function reloadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) return
    const data = await response.json()
    stats.value = [
      { label: '待消杀车辆', value: data.pending ?? 0 },
      { label: '已消杀车辆', value: data.done ?? 0 },
      { label: '本月消杀数', value: data.thisMonth ?? 0 },
      { label: '消杀记录总数', value: data.total ?? 0 },
    ]
  } catch {
    // 看板加载失败不阻断列表使用，错误由页脚统一提示
  }
}

async function reloadList() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}${buildQuery({ page: page.value, size: size.value })}`)
    if (!response.ok) {
      throw new Error('消杀记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    // 翻页总数以后端去重口径为准，不以前端条数兜底，避免对不上
    total.value = payload.total ?? 0
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '车辆消杀列表读取失败'
  }
}

async function reloadVehicleGroups() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/by-vehicle${buildQuery()}`)
    if (!response.ok) {
      throw new Error('车辆归属视图读取失败')
    }
    const payload = await response.json()
    vehicleGroups.value = payload.groups ?? []
    total.value = payload.total ?? 0
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '车辆归属视图读取失败'
  }
}

function reload() {
  void reloadStats()
  if (viewMode.value === 'list') {
    void reloadList()
  } else {
    void reloadVehicleGroups()
  }
}

function search() {
  page.value = 1
  reload()
}

function resetFilters() {
  filters.code = ''
  filters.vehicle = ''
  filters.method = ''
  filters.area = ''
  page.value = 1
  reload()
}

function changePage(next: number) {
  page.value = next
  void reloadList()
}

function switchToVehicle() {
  viewMode.value = 'vehicle'
  void reloadVehicleGroups()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('车辆消杀动作未生效，请稍后重试')
    }
    reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '车辆消杀操作失败'
  }
}

function openDetail(row: Row) {
  detail.value = row
}

function openReassign(row: Row) {
  reassignState.open = true
  reassignState.saving = false
  reassignState.id = row.id
  reassignState.code = String(row['消杀编号'] ?? '')
  reassignState.vehicle = String(row['车辆编号'] ?? '')
  reassignState.version = row.version ?? 1
  reassignState.error = ''
}

async function submitReassign() {
  reassignState.error = ''
  if (!reassignState.vehicle.trim()) {
    reassignState.error = '车辆编号不能为空'
    return
  }
  reassignState.saving = true
  try {
    const response = await request(`${ENDPOINT}/${reassignState.id}/reassign`, {
      method: 'POST',
      body: JSON.stringify({ vehicle: reassignState.vehicle.trim(), version: reassignState.version }),
    })
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) {
      // 409：版本过期，并发的其它修正已落库，本次拒绝，需要刷新拿到新版本
      throw new Error(payload.detail ?? '车辆归属修正失败，请刷新后重试')
    }
    reassignState.open = false
    reload()
  } catch (error) {
    reassignState.error = error instanceof Error ? error.message : '车辆归属修正失败'
  } finally {
    reassignState.saving = false
  }
}

function openCreate() {
  createState.open = true
  createState.saving = false
  createState.form = emptyCreateForm()
  createState.error = ''
}

async function submitCreate() {
  createState.error = ''
  const values = createFields.reduce<Record<string, string>>((acc, field) => {
    acc[field] = createState.form[field].trim()
    return acc
  }, {})
  createState.saving = true
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload) {
      throw new Error('消杀记录登记失败，可直接重试，不会产生重复记录')
    }
    if (payload.ok === false) {
      throw new Error(payload.message || '消杀记录登记失败')
    }
    // ok=true：新建或幂等回显都视为成功，后端保证没有副本
    createState.open = false
    page.value = 1
    reload()
  } catch (error) {
    createState.error = error instanceof Error ? error.message : '消杀记录登记失败'
  } finally {
    createState.saving = false
  }
}

onMounted(reload)
</script>

<style scoped>
.page-actions { display: flex; gap: 8px; }
.view-switch { display: flex; gap: 8px; margin-bottom: 12px; }
.pager { display: inline-flex; gap: 8px; align-items: center; }
.pager .btn:disabled { opacity: 0.5; cursor: not-allowed; }
.group-row td { background: #eef4ff; font-weight: 600; }
.modal-mask {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45);
  display: flex; align-items: center; justify-content: center; z-index: 20;
}
.modal {
  background: #fff; border-radius: 8px; padding: 18px 20px;
  width: 480px; max-width: calc(100vw - 32px); max-height: 82vh; overflow: auto;
}
.modal h3 { margin: 0 0 12px; }
.modal .filter-item { margin-bottom: 10px; }
.modal .filter-item input { width: 100%; padding: 6px 8px; }
.detail-list { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; margin: 0 0 12px; }
.detail-list dt { font-size: 12px; color: var(--muted); }
.detail-list dd { margin: 2px 0 0; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; }
</style>
