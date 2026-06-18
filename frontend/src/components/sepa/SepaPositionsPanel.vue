<template>
  <view>
    <view v-if="loading" class="sepa-loading">加载中…</view>

    <template v-else-if="state">
      <!-- 止损触发提醒 -->
      <view class="sepa-breaker-banner" v-for="h in stopHits" :key="'sh' + h.id" style="border-color:var(--color-up)">
        <text class="icon">🔔</text>
        <text class="txt">{{ h.name || h.symbol }} 现价 {{ sym }}{{ h.current_price }} 已触及止损价 {{ sym }}{{ h.stop_price }}，请无条件执行止损！</text>
      </view>

      <view class="sepa-card">
        <view class="sepa-section-title">持仓列表 <text class="sepa-section-sub">共 {{ state.holdings.length }} 笔</text></view>
        <view v-if="!state.holdings.length" class="sepa-empty">当前无持仓</view>

        <view v-for="h in state.holdings" :key="h.id" class="sepa-holding" :class="{ 'stop-hit': h.stop_triggered }">
          <view class="sepa-holding-head">
            <view>
              <text class="sepa-holding-name">{{ h.name || h.symbol }}</text>
              <text class="sepa-holding-code">{{ h.symbol }}</text>
            </view>
            <text class="sepa-holding-pnl" :class="pnlClass(h.float_pnl_pct)">{{ fmtPct(h.float_pnl_pct) }}</text>
          </view>
          <view class="sepa-holding-meta">
            <view class="cell"><view class="k">买入价</view><view class="v">{{ sym }}{{ h.entry_price }}</view></view>
            <view class="cell"><view class="k">现价</view><view class="v">{{ sym }}{{ h.current_price }}</view></view>
            <view class="cell"><view class="k">止损价</view><view class="v">{{ sym }}{{ h.stop_price }}</view></view>
            <view class="cell"><view class="k">距止损</view><view class="v" :class="h.dist_to_stop_pct < 3 ? 'pnl-up' : ''">{{ h.dist_to_stop_pct ?? '—' }}%</view></view>
            <view class="cell"><view class="k">股数</view><view class="v">{{ h.shares }}</view></view>
            <view class="cell"><view class="k">市值</view><view class="v">{{ sym }}{{ fmt(h.market_value) }}</view></view>
            <view class="cell"><view class="k">浮动盈亏</view><view class="v" :class="pnlClass(h.float_pnl)">{{ sym }}{{ fmt(h.float_pnl) }}</view></view>
            <view class="cell"><view class="k">买入日</view><view class="v" style="font-size:22rpx">{{ h.entry_date }}</view></view>
          </view>
          <view class="sepa-stop-alert" v-if="h.stop_triggered">⚠️ 已触及止损价，止损不是失败，是系统正常运转</view>
          <view class="sepa-btn-row">
            <view class="sepa-btn sepa-btn-danger sepa-btn-sm" style="flex:1" @click="openClose(h)">平仓</view>
          </view>
        </view>
      </view>
    </template>

    <!-- 平仓弹层 -->
    <view v-if="showClose" class="pwd-overlay" @click.self="showClose = false">
      <view class="sepa-form-modal">
        <view class="sepa-section-title">平仓 — {{ closing?.name || closing?.symbol }}</view>
        <view class="sepa-field"><text class="sepa-field-label">卖出价 *</text>
          <input class="sepa-input" type="digit" :value="cf.exit_price" @input="cf.exit_price = $event.detail.value" /></view>
        <view class="sepa-field"><text class="sepa-field-label">卖出原因 *</text>
          <view class="sepa-filter-bar" style="margin-bottom:0;">
            <view v-for="r in reasons" :key="r" class="sepa-filter-chip" :class="{ active: cf.exit_reason === r }" @click="cf.exit_reason = r">{{ r }}</view>
          </view>
        </view>
        <view class="sepa-check-row" style="border:none;">
          <text class="sepa-check-label" style="font-weight:700">是否按规则止损？（KPI 核心）</text>
        </view>
        <view class="sepa-btn-row" style="margin-bottom:14rpx;">
          <view class="sepa-btn sepa-btn-sm" :class="cf.followed_rule === true ? 'sepa-btn-brand' : 'sepa-btn-ghost'" style="flex:1" @click="cf.followed_rule = true">✓ 守纪律</view>
          <view class="sepa-btn sepa-btn-sm" :class="cf.followed_rule === false ? 'sepa-btn-danger' : 'sepa-btn-ghost'" style="flex:1" @click="cf.followed_rule = false">✗ 违纪</view>
        </view>
        <view class="sepa-field"><text class="sepa-field-label">复盘备注</text>
          <input class="sepa-input" :value="cf.review_note" placeholder="本笔执行得失" @input="cf.review_note = $event.detail.value" /></view>
        <view class="sepa-mindcard">未标注「是否守纪律」无法完成平仓 — 复盘时面对真实数据。</view>
        <view class="sepa-btn-row">
          <view class="sepa-btn sepa-btn-ghost" style="flex:1" @click="showClose = false">取消</view>
          <view class="sepa-btn sepa-btn-primary" style="flex:1" @click="submitClose">确认平仓</view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { fetchSepaAccount, closeSepaTrade } from '@/utils/api'

const props = defineProps({
  market: { type: String, required: true },
  currencySymbol: { type: String, default: '' },
  unlocked: { type: Boolean, default: false },
})
const emit = defineEmits(['need-unlock', 'changed'])

const sym = props.currencySymbol
const loading = ref(false)
const state = ref(null)
const showClose = ref(false)
const closing = ref(null)
const reasons = ['止损', '止盈', '趋势坏', '时间止损']
const cf = reactive({ exit_price: '', exit_reason: '', followed_rule: null, review_note: '' })

const stopHits = computed(() => (state.value?.holdings || []).filter(h => h.stop_triggered))

const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString())
const fmtPct = (v) => (v == null ? '—' : (v > 0 ? '+' : '') + v + '%')
const pnlClass = (v) => (v == null || v === 0 ? 'pnl-flat' : v > 0 ? 'pnl-up' : 'pnl-down')

const load = async () => {
  loading.value = true
  try {
    state.value = await fetchSepaAccount(props.market)
  } catch (e) {
    uni.showToast({ title: '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

const openClose = (h) => {
  if (!props.unlocked) { emit('need-unlock'); return }
  closing.value = h
  cf.exit_price = String(h.current_price ?? '')
  cf.exit_reason = ''
  cf.followed_rule = null
  cf.review_note = ''
  showClose.value = true
}

const submitClose = async () => {
  if (!cf.exit_price) { uni.showToast({ title: '请填卖出价', icon: 'none' }); return }
  if (!cf.exit_reason) { uni.showToast({ title: '请选卖出原因', icon: 'none' }); return }
  if (cf.followed_rule === null) { uni.showToast({ title: '必须标注是否守纪律', icon: 'none' }); return }
  const today = new Date().toISOString().slice(0, 10)
  try {
    await closeSepaTrade(closing.value.id, {
      exit_date: today, exit_price: Number(cf.exit_price),
      exit_reason: cf.exit_reason, followed_rule: cf.followed_rule,
      review_note: cf.review_note || null,
    })
    showClose.value = false
    uni.showToast({ title: '已平仓', icon: 'success' })
    await load()
    emit('changed')
  } catch (e) {
    uni.showToast({ title: e.message || '平仓失败', icon: 'none' })
  }
}

watch(() => props.market, load)
defineExpose({ load })
load()
</script>

<style scoped>
.pwd-overlay { position: fixed; inset: 0; background: rgba(26,26,46,0.5); display: flex; align-items: center; justify-content: center; z-index: 9999; }
.sepa-form-modal { width: 640rpx; max-width: 92vw; background: var(--color-bg-card); border-radius: 20rpx; padding: 32rpx; }
@media (min-width: 750px) { .sepa-form-modal { width: 440px; padding: 24px; } }
</style>
