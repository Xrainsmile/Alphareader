<template>
  <view>
    <view class="sepa-card">
      <view class="sepa-filter-bar" style="margin-bottom:0;">
        <view v-for="f in filters" :key="f.k" class="sepa-filter-chip" :class="{ active: filter === f.k }" @click="setFilter(f.k)">{{ f.label }}</view>
      </view>
      <view class="sepa-btn-row" style="margin-top:16rpx;">
        <view class="sepa-btn sepa-btn-ghost sepa-btn-sm" style="flex:1" @click="exportCsv">导出 CSV</view>
        <view class="sepa-btn sepa-btn-ghost sepa-btn-sm" style="flex:1" @click="load">刷新</view>
      </view>
    </view>

    <view v-if="loading" class="sepa-loading">加载中…</view>
    <view v-else-if="!items.length" class="sepa-empty">暂无交易记录</view>

    <view v-for="t in items" :key="t.id" class="sepa-card sepa-trade"
          :class="{ violation: t.status === 'closed' && t.followed_rule === false }" style="margin-bottom:14rpx;">
      <view class="sepa-trade-head">
        <view>
          <text class="sepa-trade-title">{{ t.name || t.symbol }}</text>
          <text class="sepa-holding-code">{{ t.symbol }}</text>
          <text class="sepa-trade-badge" :class="t.status">{{ t.status === 'open' ? '持仓中' : '已平仓' }}</text>
          <text v-if="t.status === 'closed' && t.followed_rule === false" class="sepa-trade-badge viol">违纪</text>
        </view>
        <text v-if="t.status === 'closed'" class="sepa-holding-pnl" :class="pnlClass(t.pnl_pct)">{{ fmtPct(t.pnl_pct) }}</text>
      </view>

      <view class="sepa-trade-meta">
        买入 {{ t.entry_date }} @ {{ sym }}{{ t.entry_price }} × {{ t.shares }}股（{{ sym }}{{ fmt(t.amount) }}）
        ｜止损 {{ sym }}{{ t.stop_price }}｜最大风险 {{ sym }}{{ fmt(t.max_risk) }}（{{ t.max_risk_pct }}%）
        <template v-if="t.risky_entry">｜<text class="pnl-up">⚠️追高</text></template>
        <template v-if="t.status === 'closed'">
          <br />卖出 {{ t.exit_date }} @ {{ sym }}{{ t.exit_price }}｜原因 {{ t.exit_reason }}｜盈亏 {{ sym }}{{ fmt(t.pnl_amount) }}
          ｜{{ t.followed_rule ? '✓ 守纪律' : '✗ 违纪' }}
        </template>
      </view>
      <view v-if="t.entry_reason" class="sepa-trade-note">买入理由：{{ t.entry_reason }}</view>
      <view v-if="t.review_note" class="sepa-trade-note">复盘：{{ t.review_note }}</view>

      <view class="sepa-btn-row" v-if="unlocked">
        <view class="sepa-btn sepa-btn-ghost sepa-btn-sm" style="flex:1" @click="remove(t)">撤销该笔</view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, watch } from 'vue'
import { fetchSepaTrades, deleteSepaTrade, sepaTradesExportUrl } from '@/utils/api'

const props = defineProps({
  market: { type: String, required: true },
  currencySymbol: { type: String, default: '' },
  unlocked: { type: Boolean, default: false },
})
const emit = defineEmits(['need-unlock', 'changed'])

const sym = props.currencySymbol
const loading = ref(false)
const items = ref([])
const filter = ref('all')
const filters = [
  { k: 'all', label: '全部' }, { k: 'open', label: '持仓中' }, { k: 'closed', label: '已平仓' },
  { k: 'win', label: '盈利' }, { k: 'loss', label: '亏损' }, { k: 'violation', label: '违纪' },
]

const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString())
const fmtPct = (v) => (v == null ? '—' : (v > 0 ? '+' : '') + v + '%')
const pnlClass = (v) => (v == null || v === 0 ? 'pnl-flat' : v > 0 ? 'pnl-up' : 'pnl-down')

const load = async () => {
  loading.value = true
  try {
    const r = await fetchSepaTrades(props.market, filter.value)
    items.value = r.items || []
  } catch (e) {
    uni.showToast({ title: '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

const setFilter = (k) => { filter.value = k; load() }

const exportCsv = () => {
  const url = sepaTradesExportUrl(props.market)
  // #ifdef H5
  window.open(url, '_blank')
  return
  // #endif
  // eslint-disable-next-line no-unreachable
  uni.setClipboardData({ data: url, success: () => uni.showToast({ title: '导出链接已复制', icon: 'none' }) })
}

const remove = (t) => {
  if (!props.unlocked) { emit('need-unlock'); return }
  uni.showModal({
    title: '撤销交易', content: `确认删除 ${t.name || t.symbol} 这笔记录？`,
    success: async (res) => {
      if (!res.confirm) return
      try {
        await deleteSepaTrade(t.id)
        await load()
        emit('changed')
      } catch (e) { uni.showToast({ title: e.message || '撤销失败', icon: 'none' }) }
    },
  })
}

watch(() => props.market, () => { filter.value = 'all'; load() })
defineExpose({ load })
load()
</script>
