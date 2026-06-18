<template>
  <view>
    <view class="sepa-card">
      <view class="sepa-section-title">📝 买入决策助手 <text class="sepa-section-sub">下单前强制走完检查清单</text></view>

      <view class="sepa-row2">
        <view class="sepa-field"><text class="sepa-field-label">标的代码 *</text>
          <input class="sepa-input" :value="form.symbol" placeholder="须在股池且已入池" @input="onSymbol" /></view>
        <view class="sepa-field"><text class="sepa-field-label">名称</text>
          <input class="sepa-input" :value="form.name" placeholder="可选" @input="form.name = $event.detail.value" /></view>
      </view>

      <view class="sepa-row2">
        <view class="sepa-field"><text class="sepa-field-label">买入价 *</text>
          <input class="sepa-input" type="digit" :value="form.entry_price" @input="onNum('entry_price', $event)" /></view>
        <view class="sepa-field"><text class="sepa-field-label">股数 *</text>
          <input class="sepa-input" type="number" :value="form.shares" @input="onNum('shares', $event)" /></view>
      </view>

      <view class="sepa-row2">
        <view class="sepa-field"><text class="sepa-field-label">止损价 *（必填，无止损不可下单）</text>
          <input class="sepa-input" type="digit" :value="form.stop_price" placeholder="默认建议 -7%" @input="onNum('stop_price', $event)" /></view>
        <view class="sepa-field"><text class="sepa-field-label">枢轴价 Pivot</text>
          <input class="sepa-input" type="digit" :value="form.pivot_price" placeholder="留空取股池" @input="onNum('pivot_price', $event)" /></view>
      </view>

      <view class="sepa-check-row">
        <text class="sepa-check-label">VCP 形态已确认（收缩次数、波动递减）</text>
        <switch :checked="form.vcp_confirmed" color="#34c759" @change="onVcp" />
      </view>

      <view class="sepa-field" style="margin-top:14rpx;">
        <text class="sepa-field-label">买入理由</text>
        <input class="sepa-input" :value="form.entry_reason" placeholder="如：突破3周收缩枢轴，放量" @input="form.entry_reason = $event.detail.value" />
      </view>
    </view>

    <!-- 检查清单 + 风险预演 -->
    <view class="sepa-card" v-if="check">
      <view class="sepa-section-title">✅ 买入前检查清单</view>
      <view class="sepa-cl-item" v-for="it in check.checklist.items" :key="it.key">
        <view class="sepa-cl-icon" :class="clIcon(it)">{{ it.pass ? '✓' : (it.key === 'near_pivot' ? '!' : '✗') }}</view>
        <text class="sepa-cl-text">{{ it.label }}</text>
      </view>

      <view class="sepa-risk-box">
        <view class="sepa-risk-line"><text class="k">止损幅度</text><text class="v">{{ check.risk.stop_pct }}%</text></view>
        <view class="sepa-risk-line"><text class="k">仓位金额</text><text class="v">{{ sym }}{{ fmt(check.risk.position_amount) }}（占 {{ check.risk.position_pct }}%）</text></view>
        <view class="sepa-risk-line" :class="{ danger: check.risk.exceeds_risk_limit }">
          <text class="k">单笔最大亏损</text>
          <text class="v">{{ sym }}{{ fmt(check.risk.max_loss) }}（{{ check.risk.max_loss_pct }}% / 上限 {{ check.risk.risk_limit_pct }}%）</text>
        </view>
        <view class="sepa-risk-line" v-if="check.pivot.distance_pct != null">
          <text class="k">距枢轴</text>
          <text class="v" :class="check.pivot.within_5pct ? '' : 'pnl-up'">{{ check.pivot.distance_pct }}%</text>
        </view>
      </view>

      <view class="sepa-risk-warn" v-if="check.risk.exceeds_risk_limit">⛔ 单笔亏损超 {{ check.risk.risk_limit_pct }}%，禁止下单（请减少股数或收紧止损）</view>
      <view class="sepa-risk-warn" v-else-if="!check.gate_open">⛔ 市场闸门关闭，禁止开新仓</view>
      <view class="sepa-risk-warn" v-else-if="!check.template_pass">⛔ 该标的未通过 8 条趋势模板（或不在股池）</view>
      <view class="sepa-risk-warn" v-else-if="check.circuit_breaker_hit">⛔ 账户已触及 -15% 熔断线，禁止开新仓</view>
      <view class="sepa-risk-warn" v-else-if="check.pivot.within_5pct === false" style="background:var(--color-bg-warning-light);color:var(--color-warning-deep)">
        ⚠️ 距枢轴 {{ check.pivot.distance_pct }}% 已追高（&gt;5%），需勾选「强制确认追高」
      </view>

      <view class="sepa-check-row" v-if="check.pivot.within_5pct === false">
        <text class="sepa-check-label">强制确认追高下单（记录为风险操作）</text>
        <switch :checked="form.force_risky" color="#ff9500" @change="form.force_risky = $event.detail.value" />
      </view>

      <view class="sepa-mindcard">💡 「我是来执行系统的，不是来证明自己对的。」</view>

      <view class="sepa-btn sepa-btn-primary" :class="{ disabled: !canSubmit }" style="margin-top:16rpx;" @click="submit">
        {{ canSubmit ? '确认开仓（生成持仓+止损单）' : '检查未通过，无法下单' }}
      </view>
    </view>

    <view class="sepa-card" v-else>
      <view class="sepa-btn sepa-btn-brand" @click="runCheck">运行买点检查</view>
      <view class="sepa-section-sub" style="text-align:center;margin-top:12rpx;">填写买入价/股数/止损价后，先检查再下单</view>
    </view>
  </view>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { checkSepaBuy, openSepaTrade } from '@/utils/api'

const props = defineProps({
  market: { type: String, required: true },
  currencySymbol: { type: String, default: '' },
  unlocked: { type: Boolean, default: false },
})
const emit = defineEmits(['need-unlock', 'changed'])

const sym = props.currencySymbol
const check = ref(null)
const emptyForm = () => ({
  symbol: '', name: '', entry_price: '', shares: '', stop_price: '', pivot_price: '',
  vcp_confirmed: false, entry_reason: '', force_risky: false,
})
const form = reactive(emptyForm())

const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString())

const onSymbol = (e) => { form.symbol = e.detail.value.toUpperCase(); check.value = null }
const onNum = (k, e) => { form[k] = e.detail.value; check.value = null }
const onVcp = (e) => { form.vcp_confirmed = e.detail.value; check.value = null }

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
  if (!form.symbol) { uni.showToast({ title: '请填写代码', icon: 'none' }); return false }
  if (!form.entry_price || !form.shares) { uni.showToast({ title: '请填买入价与股数', icon: 'none' }); return false }
  if (!form.stop_price) { uni.showToast({ title: '必须填止损价', icon: 'none' }); return false }
  return true
}

const runCheck = async () => {
  if (!validBasics()) return
  try {
    check.value = await checkSepaBuy({
      market: props.market, symbol: form.symbol,
      entry_price: Number(form.entry_price), shares: Number(form.shares),
      stop_price: form.stop_price ? Number(form.stop_price) : null,
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
      stop_price: Number(form.stop_price),
      pivot_price: form.pivot_price ? Number(form.pivot_price) : null,
      vcp_confirmed: form.vcp_confirmed, entry_reason: form.entry_reason || null,
      force_risky: form.force_risky,
    })
    uni.showToast({ title: '已开仓', icon: 'success' })
    Object.assign(form, emptyForm())
    check.value = null
    emit('changed')
  } catch (e) {
    uni.showToast({ title: e.message || '下单被拦截', icon: 'none' })
  }
}

watch(() => props.market, () => { Object.assign(form, emptyForm()); check.value = null })
</script>
