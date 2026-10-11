<template>
  <view class="pc-sidebar">
    <view class="pc-sidebar-brand">
      <image class="pc-sidebar-logo-img" src="/static/logo.png" mode="aspectFit" />
      <text class="pc-sidebar-logo">AlphaReader</text>
    </view>
    <!-- Reports + 侧门「!」入口 -->
    <view
      class="pc-nav-item"
      :class="{ 'pc-nav-active': active === 'reports' }"
      @click="navTo('/pages/reports/index', true)"
    >
      <text class="pc-nav-text">Reports</text>
    </view>
    <!-- News -->
    <view
      class="pc-nav-item"
      :class="{ 'pc-nav-active': active === 'news' }"
      @click="navTo('/pages/index/index', true)"
    >
      <text class="pc-nav-text">News</text>
    </view>
    <!-- 侧门「!」入口：放在 News 下方 -->
    <GateButton />
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

/* ── ≥768px：显示左侧导航（固定宽度，保证各页一致）── */
@media screen and (min-width: 768px) {
  .pc-sidebar {
    position: sticky;
    top: 0;
    width: 168px;
    min-width: 168px;
    max-width: 168px;
    height: 100vh;
    flex-shrink: 0;
    padding: 24px 16px;
    background: var(--color-bg-card);
    border-right: 1px solid var(--color-border);
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .pc-sidebar-brand {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--space-2);
    margin-bottom: 20px;
  }
  .pc-sidebar-logo-img {
    width: 26px;
    height: 26px;
    border-radius: var(--radius-p-md);
    flex-shrink: 0;
  }
  .pc-sidebar-logo {
    font-size: 18px;
    font-weight: 800;
    color: var(--color-text-primary);
    letter-spacing: 0.5px;
    user-select: none;
    -webkit-user-select: none;
  }
  .pc-nav-item {
    padding: 10px 14px;
    border-radius: var(--radius-p-lg);
    cursor: pointer;
    transition: background-color 0.15s;
  }
  /* 在桌面侧栏中：横向排列，图标 + 文字说明 */
  :deep(.gate-wrap) {
    display: flex !important;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    border-radius: var(--radius-p-lg);
    cursor: pointer;
  }
  :deep(.gate-wrap:hover) { background: var(--color-bg-hover); }
  :deep(.gate-btn) {
    width: 26px;
    height: 26px;
    min-width: 26px;
    flex-shrink: 0;
  }
  :deep(.gate-mark) { font-size: 15px; }
  :deep(.gate-label) { display: block; }
  .pc-nav-active { background: var(--color-bg-brand-light); }
  .pc-nav-text { font-size: 14px; color: var(--color-text-secondary); font-weight: 500; }
  .pc-nav-active .pc-nav-text { color: var(--color-brand); font-weight: 700; }
}

/* ── ≥1200px：侧栏加宽到 200px，正文由 .container 的 max-width 控制阅读宽度 ── */
@media screen and (min-width: 1200px) {
  .pc-sidebar {
    width: 200px;
    min-width: 200px;
    max-width: 200px;
  }
}
</style>
