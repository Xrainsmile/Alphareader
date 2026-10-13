<template>
  <view class="pc-sidebar">
    <!-- 品牌区 -->
    <view class="pc-sidebar-brand">
      <image class="pc-sidebar-logo-img" src="/static/logo.png" mode="aspectFit" />
      <view class="pc-brand-text">
        <text class="pc-sidebar-logo">AlphaReader</text>
        <text class="pc-brand-sub">把注意力留给重点</text>
      </view>
    </view>

    <!-- 主导航 -->
    <view class="pc-nav-group">
      <text class="pc-nav-label">阅读工作台</text>

      <view
        class="pc-nav-item"
        :class="{ 'pc-nav-active': active === 'reports' }"
        @click="navTo('/pages/reports/index', true)"
      >
        <text class="pc-nav-text">每日简报</text>
      </view>

      <view
        class="pc-nav-item"
        :class="{ 'pc-nav-active': active === 'news' }"
        @click="navTo('/pages/index/index', true)"
      >
        <text class="pc-nav-text">精选资讯</text>
      </view>

      <view
        class="pc-nav-item"
        :class="{ 'pc-nav-active': active === 'worldline' }"
        @click="navTo('/pages/worldline/index', false)"
      >
        <text class="pc-nav-text">世界线工作台</text>
      </view>

      <view
        class="pc-nav-item pc-nav-item-count"
        :class="{ 'pc-nav-active': active === 'bookmarks' }"
        @click="navTo('/pages/bookmarks/index', false)"
      >
        <text class="pc-nav-text">我的收藏</text>
        <text class="pc-nav-count">{{ bookmarkCount }}</text>
      </view>
    </view>

    <!-- 侧门「!」入口：解锁后显现 Stocks / SEPA -->
    <GateButton />

    <view v-show="isOpen" class="pc-nav-group pc-nav-group-gate">
      <view
        class="pc-nav-item"
        :class="{ 'pc-nav-active': active === 'stocks' }"
        @click="navTo('/pages/stocks/index', false)"
      >
        <text class="pc-nav-text">Stocks</text>
      </view>
      <view
        class="pc-nav-item"
        :class="{ 'pc-nav-active': active === 'sepa' }"
        @click="navTo('/pages/sepa/index', false)"
      >
        <text class="pc-nav-text">SEPA</text>
      </view>
    </view>

    <!-- 底部：设置 + 评分说明 -->
    <view class="pc-sidebar-foot">
      <view class="pc-nav-item pc-nav-item-sm" @click="$emit('open-settings')">
        <text class="pc-nav-text">阅读设置</text>
      </view>
      <view class="pc-nav-item pc-nav-item-sm" @click="$emit('open-score')">
        <text class="pc-nav-text">评分与信源</text>
      </view>
      <text class="pc-sidebar-note">中文界面 · 北京时间</text>
      <text class="pc-sidebar-note pc-sidebar-note-dim">专注阅读，持续追踪。</text>
    </view>
  </view>
</template>

<script setup>
import GateButton from '@/components/common/GateButton.vue'
import { useGate } from '@/utils/useGate'
import { useBookmarks } from '@/utils/useBookmarks.js'

const props = defineProps({
  active: { type: String, default: 'news' },
})

defineEmits(['open-settings', 'open-score'])

const { isOpen } = useGate()
const { bookmarkCount } = useBookmarks()

// tab=true → 原生 tabBar 页，用 switchTab；否则用 navigateTo
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
    width: 190px;
    min-width: 190px;
    max-width: 190px;
    height: 100vh;
    flex-shrink: 0;
    padding: 26px 16px 18px;
    background: var(--color-bg-card);
    border-right: 1px solid var(--color-border);
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .pc-sidebar-brand {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 22px;
    padding-left: 6px;
  }
  .pc-brand-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .pc-sidebar-logo-img {
    width: 30px;
    height: 30px;
    border-radius: 8px;
    flex-shrink: 0;
  }
  .pc-sidebar-logo {
    font-size: 16px;
    font-weight: 700;
    color: var(--color-text-primary);
    letter-spacing: 0.2px;
    user-select: none;
    -webkit-user-select: none;
  }
  .pc-brand-sub {
    font-size: 11px;
    color: var(--color-text-muted);
    line-height: 1.3;
  }

  /* 导航分组标签 */
  .pc-nav-group {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .pc-nav-group-gate {
    margin-top: 4px;
  }
  .pc-nav-label {
    font-size: 10px;
    color: var(--color-text-muted);
    letter-spacing: 1.5px;
    margin: 10px 14px 6px;
  }

  .pc-nav-item {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 10px 14px;
    border-radius: 9px;
    cursor: pointer;
    transition: background-color 0.15s;
  }
  .pc-nav-item:hover { background: var(--color-bg-hover); }
  .pc-nav-item-sm { padding: 7px 14px; }

  .pc-nav-count {
    font-size: 11px;
    color: var(--color-text-muted);
    background: var(--color-bg-secondary);
    border-radius: 20px;
    padding: 1px 7px;
    min-width: 20px;
    text-align: center;
    flex-shrink: 0;
  }

  /* 在桌面侧栏中：横向排列，图标 + 文字说明 */
  :deep(.gate-wrap) {
    display: flex !important;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    border-radius: 9px;
    cursor: pointer;
  }
  :deep(.gate-wrap:hover) { background: var(--color-bg-hover); }
  :deep(.gate-btn) {
    width: 26px;
    height: 26px;
    min-width: 26px;
    flex-shrink: 0;
  }
  :deep(.gate-label) { display: block; }

  .pc-sidebar-foot {
    margin-top: auto;
    border-top: 1px solid var(--color-border);
    padding-top: 14px;
    display: flex;
    flex-direction: column;
    gap: 1px;
  }
  .pc-sidebar-note {
    font-size: 11px;
    color: var(--color-text-muted);
    padding: 6px 14px 0;
    line-height: 1.5;
  }
  .pc-sidebar-note-dim {
    padding-top: 2px;
    opacity: 0.8;
  }
}

/* ── ≥1200px：侧栏加宽 ── */
@media screen and (min-width: 1200px) {
  .pc-sidebar {
    width: 218px;
    min-width: 218px;
    max-width: 218px;
  }
}
</style>
