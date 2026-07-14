<template>
  <view class="page-layout">
    <PcSidebar active="stocks" />
    <view class="container">
    <!-- ═══ 一级导航：市场切换（A股 / 美股）═══ -->
    <MarketSwitcher
      :active-market="activeMarket"
      @switch="onMarketSwitch"
    />

    <!-- ═══ 二级导航：策略 Tab Bar ═══ -->
    <StocksTabBar
      :active-tab="activeTab"
      :market="activeMarket"
      @select-rs="onSelectRs"
      @select-vcp="onSelectVcp"
      @select-trend="onSelectTrend"
      @select-catalyst="onSelectCatalyst"
      @select-value="onSelectValue"
      @select-sandbox="switchToSandbox"
      @select-us-vcp="onSelectUsVcp"
      @select-us-trend="onSelectUsTrend"
      @select-us-catalyst="onSelectUsCatalyst"
    />

    <!-- ═══════════════════════════════════════════════════════
         A 股 Tabs
         ═══════════════════════════════════════════════════════ -->

    <!-- RS Rating Tab — 前端暂时隐藏，后端定时计算服务继续运行 -->

    <!-- VCP 策略 Tab -->
    <VcpTab v-if="activeTab === 'vcp'" ref="vcpRef" />

    <!-- 右侧趋势策略 Tab -->
    <TrendTab v-if="activeTab === 'trend'" ref="trendRef" />

    <!-- 催化剂 Tab -->
    <CatalystTab v-if="activeTab === 'catalyst'" ref="catalystRef" />

    <!-- 价投策略 Tab -->
    <ValueTab v-if="activeTab === 'value'" ref="valueRef" />

    <!-- 模拟仓 Tab -->
    <SandboxTab v-if="activeTab === 'sandbox'" ref="sandboxRef" />

    <!-- ═══════════════════════════════════════════════════════
         美股 Tabs（VCP/趋势复用 A 股组件 + market="US"）
         ═══════════════════════════════════════════════════════ -->

    <VcpTab v-if="activeTab === 'us_vcp'" ref="usVcpRef" market="US" />

    <TrendTab v-if="activeTab === 'us_trend'" ref="usTrendRef" market="US" />

    <UsStockPlaceholder
      v-if="activeTab === 'us_catalyst'"
      title="美股催化剂"
      subtitle="英文新闻 AI 评分 × 技术面交叉验证 — 基于 Finnhub 新闻源"
      :features="usCatalystFeatures"
    />

    <!-- Footer -->
    <SiteFooter />

    <!-- 模拟仓密码验证弹窗 -->
    <SandboxPasswordModal
      :visible="showPwdModal"
      :password="pwdValue"
      :error="pwdError"
      @update:visible="showPwdModal = $event"
      @update:password="pwdValue = $event"
      @confirm="onPwdConfirm"
    />
    </view><!-- /container -->

    <!-- 右看板：策略速览 -->
    <view class="pc-right-panel">
      <view class="right-section">
        <text class="right-section-title">策略速览</text>
        <view v-for="s in strategyLinks" :key="s.key" class="right-news-item" @click="onStrategyClick(s.key)">
          <text class="right-news-rank">{{ s.icon }}</text>
          <view class="right-news-body">
            <text class="right-news-title">{{ s.label }}</text>
            <text class="right-news-meta">{{ s.desc }}</text>
          </view>
        </view>
      </view>
    </view>
  </view><!-- /page-layout -->
</template>

<script setup>
import { ref, computed } from 'vue'
import './stocks-shared.css'
import MarketSwitcher from '@/components/stocks/MarketSwitcher.vue'
import StocksTabBar from '@/components/stocks/StocksTabBar.vue'
import SandboxPasswordModal from '@/components/stocks/SandboxPasswordModal.vue'
import SiteFooter from '@/components/common/SiteFooter.vue'
import PcSidebar from '@/components/common/PcSidebar.vue'
import VcpTab from '@/components/stocks/VcpTab.vue'
import TrendTab from '@/components/stocks/TrendTab.vue'
import CatalystTab from '@/components/stocks/CatalystTab.vue'
import ValueTab from '@/components/stocks/ValueTab.vue'
import SandboxTab from '@/components/stocks/SandboxTab.vue'
import UsStockPlaceholder from '@/components/stocks/UsStockPlaceholder.vue'
import { verifySandboxAccess } from '@/utils/api'

// ── 一级导航：市场切换 ──
const activeMarket = ref('CN')

// ── 二级导航：Tab 切换 ──
const activeTab = ref('vcp')
const vcpRef = ref(null)
const trendRef = ref(null)
const catalystRef = ref(null)
const valueRef = ref(null)
const sandboxRef = ref(null)
const usVcpRef = ref(null)
const usTrendRef = ref(null)

// 市场切换时重置到该市场的默认 Tab
const onMarketSwitch = (market) => {
  if (activeMarket.value === market) return
  activeMarket.value = market
  activeTab.value = market === 'CN' ? 'vcp' : 'us_vcp'
}

// ── A 股 Tab 事件 ──
const onSelectRs = () => { activeTab.value = 'rs' }
const onSelectVcp = () => { activeTab.value = 'vcp' }
const onSelectTrend = () => { activeTab.value = 'trend' }
const onSelectCatalyst = () => { activeTab.value = 'catalyst' }
const onSelectValue = () => { activeTab.value = 'value' }

// ── 美股 Tab 事件 ──
const onSelectUsVcp = () => { activeTab.value = 'us_vcp' }
const onSelectUsTrend = () => { activeTab.value = 'us_trend' }
const onSelectUsCatalyst = () => { activeTab.value = 'us_catalyst' }

// ── 美股各策略功能预告（仅催化剂仍为占位）──
const usCatalystFeatures = [
  { icon: '🔥', text: '英文新闻 AI 评分 ≥ 7 的标的自动提取' },
  { icon: '🎯', text: '催化剂 × VCP/趋势白名单双确认' },
  { icon: '📰', text: '基于 Finnhub Market News + RSS 英文源' },
  { icon: '💡', text: '产业链映射（供应链受益方分析）' },
]

// ── 右看板：策略速览 ──
const strategyLinks = computed(() => {
  if (activeMarket.value === 'CN') {
    return [
      { key: 'vcp', icon: '📐', label: 'VCP 收缩', desc: '波动率收缩蓄势' },
      { key: 'trend', icon: '📈', label: '右侧趋势', desc: '突破回踩确认' },
      { key: 'catalyst', icon: '⚡', label: '催化剂', desc: '事件驱动机会' },
      { key: 'value', icon: '💎', label: '价投', desc: '低估价值挖掘' },
      { key: 'sandbox', icon: '🧪', label: '模拟仓', desc: '组合与回测' },
    ]
  }
  return [
    { key: 'us_vcp', icon: '📐', label: 'VCP (US)', desc: '美股波动率收缩' },
    { key: 'us_trend', icon: '📈', label: '趋势 (US)', desc: '美股右侧趋势' },
  ]
})

function onStrategyClick(key) {
  if (key === 'sandbox') { switchToSandbox(); return }
  activeTab.value = key
}

// ── 模拟仓密码验证 ──
const sbUnlocked = ref(false)
const showPwdModal = ref(false)
const pwdValue = ref('')
const pwdError = ref(false)

const switchToSandbox = () => {
  if (!sbUnlocked.value) {
    try {
      const cached = uni.getStorageSync('sb_unlocked')
      if (cached === 'true') sbUnlocked.value = true
    } catch (_) {}
  }

  if (sbUnlocked.value) {
    activeTab.value = 'sandbox'
    return
  }

  pwdValue.value = ''
  pwdError.value = false
  showPwdModal.value = true
}

const onPwdConfirm = async () => {
  try {
    await verifySandboxAccess(pwdValue.value)
    sbUnlocked.value = true
    showPwdModal.value = false
    try { uni.setStorageSync('sb_unlocked', 'true') } catch (_) {}
    activeTab.value = 'sandbox'
  } catch (_) {
    pwdError.value = true
    setTimeout(() => { pwdError.value = false }, 1500)
  }
}
</script>

<!-- 样式已移至 stocks-shared.css，通过 script import 引入，避免 uni-app 自动 scoped -->
