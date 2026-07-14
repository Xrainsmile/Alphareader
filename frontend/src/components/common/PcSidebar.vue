<template>
  <view class="pc-sidebar">
    <text class="pc-sidebar-logo">AlphaReader</text>
    <view
      v-for="item in navItems"
      :key="item.path"
      class="pc-nav-item"
      :class="{ 'pc-nav-active': active === item.key }"
      @click="navTo(item.path)"
    >
      <text class="pc-nav-text">{{ item.label }}</text>
    </view>
  </view>
</template>

<script setup>
const props = defineProps({
  active: { type: String, default: 'news' },
})

const navItems = [
  { key: 'news', label: 'News', path: '/pages/index/index' },
  { key: 'stocks', label: 'Stocks', path: '/pages/stocks/index' },
  { key: 'reports', label: 'Reports', path: '/pages/reports/index' },
  { key: 'sepa', label: 'SEPA', path: '/pages/sepa/index' },
]

function navTo(url) {
  uni.switchTab({ url })
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
</style>
