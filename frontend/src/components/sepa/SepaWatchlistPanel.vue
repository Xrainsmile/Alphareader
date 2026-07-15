<template>
  <view>
    <!-- 操作栏 -->
    <view class="sepa-card">
      <view class="sepa-btn-row">
        <view class="sepa-btn sepa-btn-brand sepa-btn-sm" style="flex:1" @click="openForm()">+ 添加标的</view>
        <view class="sepa-btn sepa-btn-ghost sepa-btn-sm" style="flex:1" @click="openBatch">批量导入</view>
        <view class="sepa-btn sepa-btn-ghost sepa-btn-sm" style="flex:1" @click="load">刷新</view>
      </view>
      <view class="sepa-filter-bar" style="margin-top:16rpx;margin-bottom:0;">
        <view class="sepa-filter-chip" :class="{ active: statusFilter === '' }" @click="setFilter('')">全部</view>
        <view class="sepa-filter-chip" :class="{ active: statusFilter === 'passed' }" @click="setFilter('passed')">已入池</view>
        <view class="sepa-filter-chip" :class="{ active: statusFilter === 'rejected' }" @click="setFilter('rejected')">未通过</view>
        <view class="sepa-filter-chip" :class="{ active: statusFilter === 'candidate' }" @click="setFilter('candidate')">待录入</view>
      </view>
    </view>

    <view v-if="loading" class="sepa-loading">加载中…</view>
    <view v-else-if="!items.length" class="sepa-empty">暂无标的，点击「添加标的」录入候选股</view>

    <view v-for="w in items" :key="w.id" class="sepa-card sepa-wl-item" style="margin-bottom:14rpx;">
      <view class="sepa-wl-head">
        <view>
          <text class="sepa-holding-name">{{ w.name || w.symbol }}</text>
          <text class="sepa-holding-code">{{ w.symbol }}</text>
        </view>
        <text class="sepa-wl-status" :class="w.status">{{ statusLabel(w.status) }}</text>
      </view>

      <view class="sepa-holding-meta">
        <view class="cell"><view class="k">现价</view><view class="v">{{ sym }}{{ w.price ?? '—' }}</view></view>
        <view class="cell"><view class="k">RS</view><view class="v">{{ w.rs ?? '—' }}</view></view>
        <view class="cell"><view class="k">枢轴</view><view class="v">{{ w.pivot_price ? sym + w.pivot_price : '—' }}</view></view>
        <view class="cell"><view class="k">VCP</view><view class="v" style="font-size:22rpx">{{ w.vcp_stage || '—' }}</view></view>
      </view>

      <!-- 8 条模板逐条 -->
      <view class="sepa-tmpl-grid" v-if="w.template_detail">
        <view v-for="d in w.template_detail" :key="d.no" class="sepa-tmpl-chip" :class="d.pass ? 'pass' : 'fail'">
          {{ d.pass ? '✓' : '✗' }} {{ d.desc }}
        </view>
      </view>

      <view v-if="w.fundamental_note" class="sepa-trade-note">基本面：{{ w.fundamental_note }}</view>

      <view class="sepa-btn-row">
        <view class="sepa-btn sepa-btn-ghost sepa-btn-sm" style="flex:1" @click="openForm(w)">编辑</view>
        <view class="sepa-btn sepa-btn-danger sepa-btn-sm" style="flex:1" @click="remove(w)">删除</view>
      </view>
    </view>

    <!-- 表单弹层 -->
    <view v-if="showForm" class="pwd-overlay" @click.self="showForm = false">
      <view class="sepa-form-modal">
        <view class="sepa-section-title">{{ editing ? '编辑标的' : '添加标的' }}</view>
        <scroll-view scroll-y class="sepa-form-scroll">
          <view class="sepa-row2">
            <view class="sepa-field"><text class="sepa-field-label">代码 *</text>
              <input class="sepa-input" :value="form.symbol" :disabled="editing" placeholder="如 NVDA / 300750" @input="form.symbol = $event.detail.value" /></view>
            <view class="sepa-field"><text class="sepa-field-label">名称</text>
              <input class="sepa-input" :value="form.name" placeholder="名称" @input="form.name = $event.detail.value" /></view>
          </view>
          <view style="margin:8rpx 0 12rpx;">
            <view class="sepa-btn sepa-btn-brand sepa-btn-sm" :style="{ opacity: (!form.symbol.trim() || autofilling) ? 0.5 : 1 }" @click="doAutofill">
              {{ autofilling ? '获取中...' : '自动获取指标' }}
            </view>
          </view>
          <view class="sepa-row2">
            <view class="sepa-field"><text class="sepa-field-label">现价</text>
              <input class="sepa-input" type="digit" :value="form.price" @input="form.price = $event.detail.value" /></view>
            <view class="sepa-field"><text class="sepa-field-label">RS（0-100）</text>
              <input class="sepa-input" type="digit" :value="form.rs" @input="form.rs = $event.detail.value" /></view>
          </view>
          <view class="sepa-row2">
            <view class="sepa-field"><text class="sepa-field-label">MA50</text>
              <input class="sepa-input" type="digit" :value="form.ma50" @input="form.ma50 = $event.detail.value" /></view>
            <view class="sepa-field"><text class="sepa-field-label">MA150</text>
              <input class="sepa-input" type="digit" :value="form.ma150" @input="form.ma150 = $event.detail.value" /></view>
          </view>
          <view class="sepa-row2">
            <view class="sepa-field"><text class="sepa-field-label">MA200</text>
              <input class="sepa-input" type="digit" :value="form.ma200" @input="form.ma200 = $event.detail.value" /></view>
            <view class="sepa-field" style="display:flex;flex-direction:column;justify-content:flex-end;">
              <view class="sepa-check-row" style="border:none;padding:0;">
                <text class="sepa-check-label">MA200 连升≥1月</text>
                <switch :checked="form.ma200_rising" color="#34c759" @change="form.ma200_rising = $event.detail.value" />
              </view>
            </view>
          </view>
          <view class="sepa-row2">
            <view class="sepa-field"><text class="sepa-field-label">52周高</text>
              <input class="sepa-input" type="digit" :value="form.high52w" @input="form.high52w = $event.detail.value" /></view>
            <view class="sepa-field"><text class="sepa-field-label">52周低</text>
              <input class="sepa-input" type="digit" :value="form.low52w" @input="form.low52w = $event.detail.value" /></view>
          </view>
          <view class="sepa-row2">
            <view class="sepa-field"><text class="sepa-field-label">枢轴价 Pivot</text>
              <input class="sepa-input" type="digit" :value="form.pivot_price" @input="form.pivot_price = $event.detail.value" /></view>
            <view class="sepa-field"><text class="sepa-field-label">VCP 阶段</text>
              <input class="sepa-input" :value="form.vcp_stage" placeholder="如 3次收缩" @input="form.vcp_stage = $event.detail.value" /></view>
          </view>
          <view class="sepa-field"><text class="sepa-field-label">基本面备注（EPS/营收/催化剂）</text>
            <input class="sepa-input" :value="form.fundamental_note" @input="form.fundamental_note = $event.detail.value" /></view>
        </scroll-view>
        <view class="sepa-btn-row">
          <view class="sepa-btn sepa-btn-ghost" style="flex:1" @click="showForm = false">取消</view>
          <view class="sepa-btn sepa-btn-primary" style="flex:1" @click="submit">{{ editing ? '保存（重判8条）' : '添加（自动判8条）' }}</view>
        </view>
      </view>
    </view>

    <!-- 批量导入弹层 -->
    <view v-if="showBatch" class="pwd-overlay" @click.self="showBatch = false">
      <view class="sepa-form-modal">
        <view class="sepa-section-title">批量导入 · {{ marketLabel }}</view>
        <view class="sepa-field-label" style="margin:4rpx 0 10rpx;line-height:1.5;">
          每行/逗号/空格分隔一个代码。示例：{{ batchPlaceholder }}
        </view>
        <textarea
          class="sepa-input sepa-batch-textarea"
          :value="batchText"
          :placeholder="batchPlaceholder"
          :disabled="batching"
          @input="batchText = $event.detail.value"
        />
        <view class="sepa-field-label" style="margin-top:8rpx;">
          识别到 <text style="color:var(--color-brand);font-weight:700;">{{ parsedCodes.length }}</text> 个代码，将自动拉取指标并判定 8 条模板
        </view>
        <view class="sepa-btn-row" style="margin-top:16rpx;">
          <view class="sepa-btn sepa-btn-ghost" style="flex:1" @click="showBatch = false">取消</view>
          <view
            class="sepa-btn sepa-btn-primary"
            style="flex:1"
            :style="{ opacity: (!parsedCodes.length || batching) ? 0.5 : 1 }"
            @click="submitBatch"
          >{{ batching ? '导入中…' : `导入 ${parsedCodes.length} 个` }}</view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { fetchSepaWatchlist, addSepaWatchlist, updateSepaWatchlist, deleteSepaWatchlist, autofillSepaMetrics, batchAddSepaWatchlist } from '@/utils/api'

const props = defineProps({
  market: { type: String, required: true },
  currencySymbol: { type: String, default: '' },
  unlocked: { type: Boolean, default: false },
})
const emit = defineEmits(['need-unlock', 'changed'])

const sym = props.currencySymbol
const loading = ref(false)
const items = ref([])
const statusFilter = ref('')
const showForm = ref(false)
const editing = ref(null)
const autofilling = ref(false)

// 批量导入
const showBatch = ref(false)
const batchText = ref('')
const batching = ref(false)
const marketLabel = computed(() => ({ CN: 'A股', HK: '港股', US: '美股' }[props.market] || props.market))
const batchPlaceholder = computed(() => ({
  CN: '300750, 600519\n000001',
  HK: '00700, 09988\n03690',
  US: 'NVDA, AAPL\nMSFT',
}[props.market] || 'NVDA, AAPL'))
const parsedCodes = computed(() => {
  const set = new Set()
  const out = []
  for (const raw of String(batchText.value).split(/[\s,，;；、]+/)) {
    const s = raw.trim().toUpperCase()
    if (!s || s.length > 16 || set.has(s)) continue
    set.add(s)
    out.push(s)
  }
  return out
})

const emptyForm = () => ({
  symbol: '', name: '', price: '', rs: '', ma50: '', ma150: '', ma200: '',
  ma200_rising: false, high52w: '', low52w: '', pivot_price: '', vcp_stage: '', fundamental_note: '',
})
const form = reactive(emptyForm())

const statusLabel = (s) => ({ passed: '✅ 入池', rejected: '✗ 未过', candidate: '待录入' }[s] || s)

const load = async () => {
  loading.value = true
  try {
    const r = await fetchSepaWatchlist(props.market, statusFilter.value)
    items.value = r.items || []
  } catch (e) {
    uni.showToast({ title: '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

const setFilter = (s) => { statusFilter.value = s; load() }

const doAutofill = async () => {
  if (!form.symbol.trim() || autofilling.value) return
  autofilling.value = true
  try {
    const data = await autofillSepaMetrics(props.market, form.symbol.trim())
    if (data.name != null) form.name = data.name
    if (data.price != null) form.price = String(data.price)
    if (data.rs != null) form.rs = String(data.rs)
    if (data.ma50 != null) form.ma50 = String(data.ma50)
    if (data.ma150 != null) form.ma150 = String(data.ma150)
    if (data.ma200 != null) form.ma200 = String(data.ma200)
    if (data.ma200_rising != null) form.ma200_rising = data.ma200_rising
    if (data.high52w != null) form.high52w = String(data.high52w)
    if (data.low52w != null) form.low52w = String(data.low52w)
    uni.showToast({ title: '指标已获取', icon: 'success' })
  } catch (e) {
    uni.showToast({ title: e.message || '获取失败', icon: 'none' })
  } finally {
    autofilling.value = false
  }
}

const openBatch = () => {
  if (!props.unlocked) { emit('need-unlock'); return }
  batchText.value = ''
  showBatch.value = true
}

const submitBatch = async () => {
  if (!props.unlocked) { emit('need-unlock'); return }
  const symbols = parsedCodes.value
  if (!symbols.length || batching.value) return
  batching.value = true
  try {
    const r = await batchAddSepaWatchlist({ market: props.market, symbols })
    const nAdd = (r.added || []).length
    const nSkip = (r.skipped || []).length
    const nFail = (r.failed || []).length
    showBatch.value = false
    await load()
    emit('changed')
    const parts = [`成功 ${nAdd}`]
    if (nSkip) parts.push(`已存在 ${nSkip}`)
    if (nFail) parts.push(`失败 ${nFail}`)
    uni.showModal({
      title: '批量导入完成',
      content: parts.join(' · ') + (nFail ? `\n失败代码：${(r.failed || []).map(f => f.symbol).join('、')}` : ''),
      showCancel: false,
    })
  } catch (e) {
    uni.showToast({ title: e.message || '导入失败', icon: 'none' })
  } finally {
    batching.value = false
  }
}

const openForm = (w) => {
  if (!props.unlocked) { emit('need-unlock'); return }
  Object.assign(form, emptyForm())
  editing.value = null
  if (w) {
    editing.value = w
    Object.assign(form, {
      symbol: w.symbol, name: w.name || '', price: w.price ?? '', rs: w.rs ?? '',
      ma50: w.ma50 ?? '', ma150: w.ma150 ?? '', ma200: w.ma200 ?? '', ma200_rising: !!w.ma200_rising,
      high52w: w.high52w ?? '', low52w: w.low52w ?? '', pivot_price: w.pivot_price ?? '',
      vcp_stage: w.vcp_stage || '', fundamental_note: w.fundamental_note || '',
    })
  }
  showForm.value = true
}

const numOrNull = (v) => (v === '' || v == null ? null : Number(v))

const submit = async () => {
  if (!form.symbol && !editing.value) { uni.showToast({ title: '请填写代码', icon: 'none' }); return }
  const payload = {
    name: form.name,
    price: numOrNull(form.price), rs: numOrNull(form.rs),
    ma50: numOrNull(form.ma50), ma150: numOrNull(form.ma150), ma200: numOrNull(form.ma200),
    ma200_rising: form.ma200_rising,
    high52w: numOrNull(form.high52w), low52w: numOrNull(form.low52w),
    pivot_price: numOrNull(form.pivot_price),
    vcp_stage: form.vcp_stage || null, fundamental_note: form.fundamental_note || null,
  }
  try {
    if (editing.value) {
      await updateSepaWatchlist(editing.value.id, payload)
    } else {
      await addSepaWatchlist({ market: props.market, symbol: form.symbol, ...payload })
    }
    showForm.value = false
    uni.showToast({ title: '已保存', icon: 'success' })
    await load()
    emit('changed')
  } catch (e) {
    uni.showToast({ title: e.message || '保存失败', icon: 'none' })
  }
}

const remove = (w) => {
  if (!props.unlocked) { emit('need-unlock'); return }
  uni.showModal({
    title: '删除标的', content: `确认从股池删除 ${w.name || w.symbol}？`,
    success: async (res) => {
      if (!res.confirm) return
      try {
        await deleteSepaWatchlist(w.id)
        await load()
        emit('changed')
      } catch (e) { uni.showToast({ title: e.message || '删除失败', icon: 'none' }) }
    },
  })
}

watch(() => props.market, () => { statusFilter.value = ''; showBatch.value = false; load() })
defineExpose({ load })
load()
</script>

<style scoped>
.pwd-overlay {
  position: fixed; inset: 0;
  background: rgba(26, 26, 46, 0.5);
  display: flex; align-items: center; justify-content: center;
  z-index: 9999;
}
.sepa-form-modal {
  width: 660rpx; max-width: 92vw;
  background: var(--color-bg-card);
  border-radius: 20rpx; padding: 32rpx;
}
.sepa-form-scroll { max-height: 60vh; }
.sepa-batch-textarea {
  width: 100%;
  box-sizing: border-box;
  height: 240rpx;
  min-height: 240rpx;
}
@media (min-width: 750px) {
  .sepa-form-modal { width: 460px; padding: 24px; }
}
</style>
