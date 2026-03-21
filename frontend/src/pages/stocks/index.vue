<template>
  <view class="stocks-container">
    <!-- Tab Bar -->
    <StocksTabBar
      :active-tab="activeTab"
      @select-rs="onSelectRs"
      @select-vcp="onSelectVcp"
      @select-trend="onSelectTrend"
      @select-value="onSelectValue"
      @select-sandbox="switchToSandbox"
    />

    <!-- ═══════════════════════════════════════════════════════
         RS Rating Tab — 前端暂时隐藏，后端定时计算服务继续运行
         ═══════════════════════════════════════════════════════ -->
    <!-- RS Rating 前端模板已注释，恢复时取消注释即可 -->

    <!-- VCP 策略 Tab -->
    <VcpTab v-if="activeTab === 'vcp'" ref="vcpRef" />

    <!-- 右侧趋势策略 Tab -->
    <TrendTab v-if="activeTab === 'trend'" ref="trendRef" />

    <!-- 价投策略 Tab -->
    <ValueTab v-if="activeTab === 'value'" ref="valueRef" />

    <!-- 模拟仓 Tab -->
    <SandboxTab v-if="activeTab === 'sandbox'" ref="sandboxRef" />

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
  </view>
</template>

<script setup>
import { ref } from 'vue'
import './stocks-shared.css'
import StocksTabBar from '@/components/stocks/StocksTabBar.vue'
import SandboxPasswordModal from '@/components/stocks/SandboxPasswordModal.vue'
import SiteFooter from '@/components/common/SiteFooter.vue'
import VcpTab from '@/components/stocks/VcpTab.vue'
import TrendTab from '@/components/stocks/TrendTab.vue'
import ValueTab from '@/components/stocks/ValueTab.vue'
import SandboxTab from '@/components/stocks/SandboxTab.vue'
import { verifySandboxAccess } from '@/utils/api'

// ── Tab 切换 ──
const activeTab = ref('vcp')
const vcpRef = ref(null)
const trendRef = ref(null)
const valueRef = ref(null)
const sandboxRef = ref(null)

// v-if 控制子组件生命周期，每次挂载时子组件在 onMounted 中自动 init
const onSelectRs = () => { activeTab.value = 'rs' }
const onSelectVcp = () => { activeTab.value = 'vcp' }
const onSelectTrend = () => { activeTab.value = 'trend' }
const onSelectValue = () => { activeTab.value = 'value' }

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
