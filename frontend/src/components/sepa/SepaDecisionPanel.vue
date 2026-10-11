<template>
  <view>
    <view class="sepa-card">
      <view class="sepa-section-title">📝 Buy Decision Assistant <text class="sepa-section-sub">Checklist must be completed before placing an order</text></view>

      <view class="sepa-row2">
        <view class="sepa-field sepa-combo-field"><text class="sepa-field-label">Ticker *</text>
          <view class="sepa-combo">
            <input class="sepa-input" :value="form.symbol" placeholder="从股池选择或输入" @input="onSymbol" @focus="onComboFocus" @blur="onComboBlur" />
            <view class="sepa-combo-list" v-if="comboOpen && filteredSymbols.length">
              <view class="sepa-combo-item" v-for="w in filteredSymbols" :key="w.symbol" @click="pickSymbol(w)">
                <text class="sepa-combo-name">{{ w.name || '—' }}</text>
                <text class="sepa-combo-code">{{ w.symbol }}</text>
              </view>
            </view>
          </view>
        </view>
        <view class="sepa-field"><text class="sepa-field-label">Name</text>
          <input class="sepa-input" :value="form.name" placeholder="选代码后自动带出" @input="form.name = $event.detail.value" /></view>
      </view>

      <view class="sepa-row2">
        <view class="sepa-field"><text class="sepa-field-label">Buy Price *</text>
          <input class="sepa-input" type="digit" :value="form.entry_price" @input="onNum('entry_price', $event)" /></view>
        <view class="sepa-field"><text class="sepa-field-label">Shares *</text>
          <input class="sepa-input" type="number" :value="form.shares" @input="onNum('shares', $event)" /></view>
      </view>

      <view class="sepa-row2">
        <view class="sepa-field"><text class="sepa-field-label">Stop-Loss % * (e.g. -7, required)</text>
          <input class="sepa-input" type="text" :value="form.stop_pct" placeholder="如 -7" @input="onStopPct" /></view>
        <view class="sepa-field"><text class="sepa-field-label">Pivot Price</text>
          <input class="sepa-input" type="digit" :value="form.pivot_price" placeholder="留空取股池" @input="onNum('pivot_price', $event)" /></view>
      </view>

      <view class="sepa-check-row">
        <text class="sepa-check-label">VCP confirmed (contraction count, declining volatility)</text>
        <switch :checked="form.vcp_confirmed" color="var(--color-down)" @change="onVcp" />
      </view>

      <view class="sepa-field" style="margin-top:14rpx;">
        <text class="sepa-field-label">Buy Thesis</text>
        <input class="sepa-input" :value="form.entry_reason" placeholder="如：突破3周收缩枢轴，放量" @input="form.entry_reason = $event.detail.value" />
      </view>
    </view>

    <!-- 检查清单 + 风险预演 -->
    <view class="sepa-card" v-if="check">
      <view class="sepa-section-title">✅ Pre-Buy Checklist</view>
      <view class="sepa-cl-item" v-for="it in check.checklist.items" :key="it.key">
        <view class="sepa-cl-icon" :class="clIcon(it)">{{ it.pass ? '✓' : (it.key === 'near_pivot' ? '!' : '✗') }}</view>
        <text class="sepa-cl-text">{{ it.label }}</text>
      </view>

      <view class="sepa-risk-box">
        <view class="sepa-risk-line"><text class="k">Stop Distance</text><text class="v">{{ check.risk.stop_pct }}%</text></view>
        <view class="sepa-risk-line"><text class="k">Position Amount</text><text class="v">{{ sym }}{{ fmt(check.risk.position_amount) }}（占 {{ check.risk.position_pct }}%）</text></view>
        <view class="sepa-risk-line" :class="{ danger: check.risk.exceeds_risk_limit }">
          <text class="k">Max Loss per Trade</text>
          <text class="v">{{ sym }}{{ fmt(check.risk.max_loss) }}（{{ check.risk.max_loss_pct }}% / 上限 {{ check.risk.risk_limit_pct }}%）</text>
        </view>
        <view class="sepa-risk-line" v-if="check.pivot.distance_pct != null">
          <text class="k">Vs Pivot</text>
          <text class="v" :class="check.pivot.within_5pct ? '' : 'pnl-up'">{{ check.pivot.distance_pct }}%</text>
        </view>
      </view>

      <view class="sepa-risk-warn" v-if="check.risk.exceeds_risk_limit">⛔ 单笔亏损超 {{ check.risk.risk_limit_pct }}%，禁止下单（请减少股数或收紧止损）</view>
      <view class="sepa-risk-warn" v-else-if="!check.gate_open">⛔ Market gate closed — new positions blocked</view>
      <view class="sepa-risk-warn" v-else-if="!check.template_pass">⛔ Failed 8 trend templates (or not in pool)</view>
      <view class="sepa-risk-warn" v-else-if="check.circuit_breaker_hit">⛔ Account hit -15% circuit breaker — new positions blocked</view>
      <view class="sepa-risk-warn" v-else-if="check.pivot.within_5pct === false" style="background:var(--color-bg-warning-light);color:var(--color-warning-deep)">
        ⚠️ 距枢轴 {{ check.pivot.distance_pct }}% 已追高（&gt;5%），需勾选「强制确认追高」
      </view>

      <view class="sepa-check-row" v-if="check.pivot.within_5pct === false">
        <text class="sepa-check-label">Force-confirm chasing entry (logged as a risk event)</text>
        <switch :checked="form.force_risky" color="var(--color-warning)" @change="form.force_risky = $event.detail.value" />
      </view>

      <view class="sepa-mindcard">💡 "I'm here to execute the system, not to prove myself right."</view>

      <view class="sepa-btn sepa-btn-primary" :class="{ disabled: !canSubmit }" style="margin-top:16rpx;" @click="submit">
        {{ canSubmit ? '确认开仓（生成持仓+止损单）' : '检查未通过，无法下单' }}
      </view>
    </view>

    <view class="sepa-card" v-else>
      <view class="sepa-btn sepa-btn-brand" @click="runCheck">Run Buy Check</view>
      <view class="sepa-section-sub" style="text-align:center;margin-top:12rpx;">Enter price / shares / stop-loss %, then run the check</view>
    </view>
  </view>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { checkSepaBuy, openSepaTrade, fetchSepaWatchlist } from '@/utils/api'

const props = defineProps({
  market: { type: String, required: true },
  currencySymbol: { type: String, default: '' },
  unlocked: { type: Boolean, default: false },
})
const emit = defineEmits(['need-unlock', 'changed'])

const sym = props.currencySymbol
const check = ref(null)
const watchlist = ref([])
const comboOpen = ref(false)
let blurTimer = null

const emptyForm = () => ({
  symbol: '', name: '', entry_price: '', shares: '', stop_pct: '-7', pivot_price: '',
  vcp_confirmed: false, entry_reason: '', force_risky: false,
})
const form = reactive(emptyForm())

const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString())

// ── 标的代码可搜索下拉 ──
const filteredSymbols = computed(() => {
  const q = (form.symbol || '').trim().toUpperCase()
  const pool = watchlist.value
  if (!q) return pool.slice(0, 30)
  return pool.filter(w =>
    w.symbol.toUpperCase().includes(q) || (w.name || '').toUpperCase().includes(q)
  ).slice(0, 30)
})

const loadWatchlist = async () => {
  try {
    const r = await fetchSepaWatchlist(props.market)
    watchlist.value = r.items || []
  } catch (_) {}
}

const onComboFocus = () => {
  if (blurTimer) { clearTimeout(blurTimer); blurTimer = null }
  comboOpen.value = true
}
const onComboBlur = () => {
  blurTimer = setTimeout(() => { comboOpen.value = false }, 180)
}
const pickSymbol = (w) => {
  form.symbol = w.symbol
  form.name = w.name || ''
  comboOpen.value = false
  check.value = null
}

const onSymbol = (e) => { form.symbol = e.detail.value.toUpperCase(); check.value = null }
const onNum = (k, e) => { form[k] = e.detail.value; check.value = null }
const onStopPct = (e) => {
  let v = e.detail.value.replace(/[^\d.\-]/g, '')
  form.stop_pct = v
  check.value = null
}
const onVcp = (e) => { form.vcp_confirmed = e.detail.value; check.value = null }

// 跌幅（负数，如 -7）→ 绝对止损价
const stopPrice = () => {
  const ep = Number(form.entry_price)
  const sp = Number(form.stop_pct)
  if (!ep || !sp || sp >= 0) return null
  return Math.round(ep * (1 + sp / 100) * 10000) / 10000
}

const clIcon = (it) => {
  if (it.pass) return 'ok'
  return it.key === 'near_pivot' ? 'warn' : 'no'
}

const canSubmit = computed(() => {
  if (!check.value) return false
  const c = check.value
  // 硬条件全过 + 止损有效 + 不超风险 + 未熔断；追高需 force_risky
  const hard = c.checklist.hard_pass && c.risk.stop_valid && !c.risk.exceeds_risk_limit && !c.circuit_breaker_hit
  if (!hard) return false
  if (c.pivot.within_5pct === false && !form.force_risky) return false
  return true
})

const validBasics = () => {
  if (!form.symbol) { uni.showToast({ title: 'Please enter a ticker', icon: 'none' }); return false }
  if (!form.entry_price || !form.shares) { uni.showToast({ title: 'Enter buy price and shares', icon: 'none' }); return false }
  const sp = Number(form.stop_pct)
  if (!form.stop_pct || isNaN(sp) || sp >= 0) { uni.showToast({ title: 'Stop-loss must be negative', icon: 'none' }); return false }
  return true
}

const runCheck = async () => {
  if (!validBasics()) return
  try {
    check.value = await checkSepaBuy({
      market: props.market, symbol: form.symbol,
      entry_price: Number(form.entry_price), shares: Number(form.shares),
      stop_price: stopPrice(),
      pivot_price: form.pivot_price ? Number(form.pivot_price) : null,
      vcp_confirmed: form.vcp_confirmed,
    })
  } catch (e) {
    uni.showToast({ title: e.message || '检查失败', icon: 'none' })
  }
}

const submit = async () => {
  if (!canSubmit.value) return
  if (!props.unlocked) { emit('need-unlock'); return }
  const today = new Date().toISOString().slice(0, 10)
  try {
    await openSepaTrade({
      market: props.market, symbol: form.symbol, name: form.name,
      entry_date: today, entry_price: Number(form.entry_price), shares: Number(form.shares),
      stop_price: stopPrice(),
      pivot_price: form.pivot_price ? Number(form.pivot_price) : null,
      vcp_confirmed: form.vcp_confirmed, entry_reason: form.entry_reason || null,
      force_risky: form.force_risky,
    })
    uni.showToast({ title: 'Position opened', icon: 'success' })
    Object.assign(form, emptyForm())
    check.value = null
    emit('changed')
  } catch (e) {
    uni.showToast({ title: e.message || '下单被拦截', icon: 'none' })
  }
}

watch(() => props.market, () => { Object.assign(form, emptyForm()); check.value = null; loadWatchlist() })
onMounted(loadWatchlist)
</script>
