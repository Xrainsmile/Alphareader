<template>
  <view class="pc-sidebar">
    <text class="pc-sidebar-logo">AlphaReader</text>
    <!-- Reports + 侧门「!」入口 -->
    <view
      class="pc-nav-item"
      :class="{ 'pc-nav-active': active === 'reports' }"
      @click="navTo('/pages/reports/index', true)"
    >
      <text class="pc-nav-text">Reports</text>
    </view>
    <GateButton />
    <!-- News -->
    <view
      class="pc-nav-item"
      :class="{ 'pc-nav-active': active === 'news' }"
      @click="navTo('/pages/index/index', true)"
    >
      <text class="pc-nav-text">News</text>
    </view>
    <!-- Stocks / SEPA：默认对外隐藏，解锁（gate_open）后显现 -->
    <view
      v-show="isOpen"
      class="pc-nav-item"
      :class="{ 'pc-nav-active': active === 'stocks' }"
      @click="navTo('/pages/stocks/index', false)"
    >
      <text class="pc-nav-text">Stocks</text>
    </view>
    <view
      v-show="isOpen"
      class="pc-nav-item"
      :class="{ 'pc-nav-active': active === 'sepa' }"
      @click="navTo('/pages/sepa/index', false)"
    >
      <text class="pc-nav-text">SEPA</text>
    </view>
  </view>
</template>

<script setup>
import GateButton from '@/components/common/GateButton.vue'
import { useGate } from '@/utils/useGate'

const props = defineProps({
  active: { type: String, default: 'news' },
})

const { isOpen } = useGate()

// tab=true → 原生 tabBar 页，用 switchTab；否则（已隐藏的 Stocks/SEPA）用 navigateTo
function navTo(url, isTab) {
  if (isTab) uni.switchTab({ url })
  else uni.navigateTo({ url })
}
</script>

<style scoped>
.pc-sidebar {
  display: none;
}

/* ── ≥768px：显示左侧导航 ── */
@media screen and (min-width: 768px) {
  .pc-sidebar {
    position: sticky;
    top: 0;
    width: 180px;
    height: 100vh;
    flex-shrink: 0;
    padding: 24px 16px;
    background: var(--color-bg-card);
    border-right: 1px solid var(--color-border);
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .pc-sidebar-logo {
    font-size: 18px;
    font-weight: 800;
    color: var(--color-text-primary);
    margin-bottom: 20px;
    letter-spacing: 0.5px;
    user-select: none;
    -webkit-user-select: none;
  }
  .pc-nav-item {
    padding: 10px 14px;
    border-radius: 8px;
    cursor: pointer;
    transition: background-color 0.15s;
  }
  .pc-nav-item:hover { background: var(--color-bg-hover); }
  .pc-nav-active { background: var(--color-bg-brand-light); }
  .pc-nav-text { font-size: 14px; color: var(--color-text-secondary); font-weight: 500; }
  .pc-nav-active .pc-nav-text { color: var(--color-brand); font-weight: 700; }
}

/* ── ≥1200px：三列比例中左导航占 2（左导航:中间:右侧 = 2:14:4）── */
@media screen and (min-width: 1200px) {
  .pc-sidebar {
    width: auto;
    flex: 2 1 0;
    min-width: 0;
  }
}
</style>
