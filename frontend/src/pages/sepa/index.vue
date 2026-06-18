<template>
  <view class="sepa-container">
    <view class="sepa-market-switch">
      <view v-for="m in markets" :key="m.market" class="sepa-market-tab" :class="{ active: market === m.market }" @click="switchMarket(m.market)">
        {{ m.label }}<text class="sepa-market-cur">{{ m.symbol }}</text>
      </view>
    </view>

    <view class="sepa-account-card" v-if="account">
      <view class="sepa-equity-label">总权益 · {{ curLabel }}（{{ account.currency }}）</view>
      <view class="sepa-equity">{{ sym }}{{ fmt(account.total_equity) }}</view>
      <view class="sepa-account-grid">
        <view class="cell"><view class="k">现金</view><view class="v">{{ sym }}{{ fmt(account.cash) }}</view></view>
        <view class="cell"><view class="k">持仓市值</view><view class="v">{{ sym }}{{ fmt(account.market_value) }}</view></view>
        <view class="cell"><view class="k">累计盈亏</view><view class="v" :class="pnlClass(account.total_pnl_pct)">{{ fmtPct(account.total_pnl_pct) }}</view></view>
        <view class="cell"><view class="k">初始资金</view><view class="v">{{ sym }}{{ fmt(account.initial_capital) }}</view></view>
        <view class="cell"><view class="k">已实现盈亏</view><view class="v" :class="pnlClass(account.realized_pnl)">{{ sym }}{{ fmt(account.realized_pnl) }}</view></view>
        <view class="cell"><view class="k">距熔断(-15%)</view><view class="v" :class="account.dist_to_breaker_pct < 5 ? 'pnl-up' : ''">{{ account.dist_to_breaker_pct }}%</view></view>
      </view>
    </view>

    <view class="sepa-breaker-banner" v-if="account && account.circuit_breaker_hit">
      <text class="icon">🛑</text>
      <text class="txt">账户已亏损达 {{ account.circuit_breaker_pct }}% 熔断线，全局禁止开新仓，请强制停手复盘。</text>
    </view>

    <view class="sepa-lock-bar" :class="{ unlocked }" @click="unlocked ? null : openPwd()">
      <text>{{ unlocked ? '🔓 已解锁，可执行交易操作' : '🔒 只读模式 — 点此输入密码解锁交易操作' }}</text>
    </view>

    <view class="sepa-module-tabs">
      <view v-for="t in tabs" :key="t.k" class="sepa-module-tab" :class="{ active: tab === t.k }" @click="tab = t.k">{{ t.label }}</view>
    </view>

    <SepaDecisionPanel v-if="tab === 'decision'" :market="market" :currency-symbol="sym" :unlocked="unlocked" @need-unlock="openPwd" @changed="refreshAccount" />
    <SepaPositionsPanel v-else-if="tab === 'positions'" :market="market" :currency-symbol="sym" :unlocked="unlocked" @need-unlock="openPwd" @changed="refreshAccount" />
    <SepaWatchlistPanel v-else-if="tab === 'watchlist'" :market="market" :currency-symbol="sym" :unlocked="unlocked" @need-unlock="openPwd" @changed="refreshAccount" />
    <SepaJournalPanel v-else-if="tab === 'journal'" :market="market" :currency-symbol="sym" :unlocked="unlocked" @need-unlock="openPwd" @changed="refreshAccount" />
    <SepaKpiPanel v-else-if="tab === 'kpi'" :market="market" />
    <SepaGatePanel v-else-if="tab === 'gate'" :market="market" :unlocked="unlocked" @need-unlock="openPwd" @changed="refreshAccount" />

    <SiteFooter />

    <SandboxPasswordModal
      :visible="showPwd" :password="pwdValue" :error="pwdError"
      @update:visible="showPwd = $event" @update:password="pwdValue = $event" @confirm="onPwdConfirm" />
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onPullDownRefresh } from '@dcloudio/uni-app'
import './sepa-shared.css'
import SepaDecisionPanel from '@/components/sepa/SepaDecisionPanel.vue'
import SepaPositionsPanel from '@/components/sepa/SepaPositionsPanel.vue'
import SepaWatchlistPanel from '@/components/sepa/SepaWatchlistPanel.vue'
import SepaJournalPanel from '@/components/sepa/SepaJournalPanel.vue'
import SepaKpiPanel from '@/components/sepa/SepaKpiPanel.vue'
import SepaGatePanel from '@/components/sepa/SepaGatePanel.vue'
import SandboxPasswordModal from '@/components/stocks/SandboxPasswordModal.vue'
import SiteFooter from '@/components/common/SiteFooter.vue'
import { fetchSepaMarkets, fetchSepaAccount, verifySandboxAccess } from '@/utils/api'

const DEFAULT_MARKETS = [
  { market: 'CN', label: 'A股', symbol: '¥', currency: 'CNY' },
  { market: 'HK', label: '港股', symbol: 'HK$', currency: 'HKD' },
  { market: 'US', label: '美股', symbol: '$', currency: 'USD' },
]

const markets = ref(DEFAULT_MARKETS)
const market = ref('CN')
const account = ref(null)
const tab = ref('decision')
const tabs = [
  { k: 'decision', label: '决策' },
  { k: 'positions', label: '持仓' },
  { k: 'watchlist', label: '股池' },
  { k: 'journal', label: '日志' },
  { k: 'kpi', label: 'KPI' },
  { k: 'gate', label: '闸门' },
]

const curInfo = computed(() => markets.value.find(m => m.market === market.value) || DEFAULT_MARKETS[0])
const sym = computed(() => curInfo.value.symbol)
const curLabel = computed(() => curInfo.value.label)

const fmt = (n) => (n == null ? '—' : Number(n).toLocaleString())
const fmtPct = (v) => (v == null ? '—' : (v > 0 ? '+' : '') + v + '%')
const pnlClass = (v) => (v == null || v === 0 ? 'pnl-flat' : v > 0 ? 'pnl-up' : 'pnl-down')

const loadMarkets = async () => {
  try {
    const r = await fetchSepaMarkets()
    if (r && r.items && r.items.length) markets.value = r.items
  } catch (e) { /* 用默认 */ }
}

const refreshAccount = async () => {
  try {
    account.value = await fetchSepaAccount(market.value)
  } catch (e) { account.value = null }
}

const switchMarket = (m) => {
  if (market.value === m) return
  market.value = m
  refreshAccount()
}

// ── 密码解锁 ──
const unlocked = ref(false)
const showPwd = ref(false)
const pwdValue = ref('')
const pwdError = ref(false)

const checkCached = () => {
  try {
    if (uni.getStorageSync('sepa_unlocked') === 'true' && uni.getStorageSync('sepa_pwd')) {
      unlocked.value = true
    }
  } catch (_) {}
}

const openPwd = () => {
  if (unlocked.value) return
  pwdValue.value = ''
  pwdError.value = false
  showPwd.value = true
}

const onPwdConfirm = async () => {
  try {
    await verifySandboxAccess(pwdValue.value)
    unlocked.value = true
    showPwd.value = false
    try {
      uni.setStorageSync('sepa_unlocked', 'true')
      uni.setStorageSync('sepa_pwd', pwdValue.value)
    } catch (_) {}
  } catch (_) {
    pwdError.value = true
    setTimeout(() => { pwdError.value = false }, 1500)
  }
}

onPullDownRefresh(async () => {
  await Promise.all([loadMarkets(), refreshAccount()])
  uni.stopPullDownRefresh()
})

checkCached()
loadMarkets()
refreshAccount()
</script>
