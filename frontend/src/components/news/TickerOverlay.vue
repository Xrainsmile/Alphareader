<template>
  <view v-if="visible" class="ticker-overlay" @click.self="$emit('close')">
    <view class="ticker-overlay-card">
      <!-- Loading 状态 -->
      <view v-if="loading" class="ticker-overlay-loading">
        <text class="ticker-overlay-loading-text">查询中...</text>
      </view>
      <!-- 数据已加载 -->
      <template v-else>
        <!-- 标题行 -->
        <view class="ticker-overlay-header">
          <text class="ticker-overlay-code">${{ code }}</text>
          <text v-if="data?.name" class="ticker-overlay-name">{{ data.name }}</text>
          <view class="ticker-overlay-close" @click="$emit('close')">
            <text class="ticker-overlay-close-icon">✕</text>
          </view>
        </view>

        <!-- 策略状态 -->
        <view v-if="data?.in_vcp || data?.in_trend" class="ticker-overlay-strategies">
          <view v-if="data.in_vcp" class="ticker-strategy-row">
            <text class="ticker-strategy-icon">📊</text>
            <text class="ticker-strategy-label">VCP 策略</text>
            <text class="ticker-strategy-badge ticker-strategy-in">白名单中 ✅</text>
            <text v-if="data.vcp_score != null" class="ticker-strategy-score">{{ Math.round(data.vcp_score) }}分</text>
          </view>
          <view v-if="data.in_trend" class="ticker-strategy-row">
            <text class="ticker-strategy-icon">📈</text>
            <text class="ticker-strategy-label">趋势策略</text>
            <text class="ticker-strategy-badge ticker-strategy-in">白名单中 ✅</text>
            <text v-if="data.trend_score != null" class="ticker-strategy-score">{{ Math.round(data.trend_score) }}分</text>
          </view>
          <view v-if="data.industry" class="ticker-strategy-row">
            <text class="ticker-strategy-icon">🏭</text>
            <text class="ticker-strategy-label">行业</text>
            <text class="ticker-strategy-value">{{ data.industry }}</text>
          </view>
        </view>

        <!-- 不在白名单 -->
        <view v-else class="ticker-overlay-empty">
          <text class="ticker-overlay-empty-text">未在当日策略白名单中</text>
        </view>

        <!-- 操作按钮 -->
        <view class="ticker-overlay-actions">
          <view v-if="data?.futu_url" class="ticker-action-btn ticker-action-futu" @click="$emit('open-futu')">
            <text class="ticker-action-text">查看行情详情</text>
          </view>
          <view class="ticker-action-btn ticker-action-search" @click="$emit('search-news')">
            <text class="ticker-action-text">搜索相关新闻</text>
          </view>
        </view>
      </template>
    </view>
  </view>
</template>

<script setup>
defineProps({
  visible: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  code: { type: String, default: '' },
  data: { type: Object, default: null },
})

defineEmits(['close', 'open-futu', 'search-news'])
</script>

<style scoped>
/* ── Ticker Tag 特殊样式（移动端） ── */
:deep(.news-tag-ticker) {
  cursor: pointer;
  background: rgba(255, 149, 0, 0.10);
  color: var(--color-warning, #ff9500);
  font-weight: 600;
  transition: background-color 0.15s;
}
:deep(.news-tag-ticker:active) {
  background: rgba(255, 149, 0, 0.22);
}

/* ── 浮层蒙版 ── */
.ticker-overlay {
  position: fixed;
  left: 0;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.35);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40rpx;
  animation: ticker-fade-in 0.15s ease;
}
@keyframes ticker-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* ── 浮层卡片 ── */
.ticker-overlay-card {
  background: var(--color-bg-card);
  border-radius: 24rpx;
  width: 100%;
  max-width: 640rpx;
  padding: 36rpx 32rpx 28rpx;
  box-shadow: 0 16rpx 64rpx rgba(0, 0, 0, 0.18);
  animation: ticker-slide-up 0.2s ease;
}
@keyframes ticker-slide-up {
  from { transform: translateY(30rpx); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

/* ── Loading ── */
.ticker-overlay-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48rpx 0;
}
.ticker-overlay-loading-text {
  font-size: 28rpx;
  color: var(--color-text-muted);
}

/* ── Header ── */
.ticker-overlay-header {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-bottom: 28rpx;
}
.ticker-overlay-code {
  font-size: 34rpx;
  font-weight: 700;
  color: var(--color-warning, #ff9500);
  font-family: var(--font-numeric);
}
.ticker-overlay-name {
  font-size: 30rpx;
  font-weight: 600;
  color: var(--color-text-primary);
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ticker-overlay-close {
  width: 48rpx;
  height: 48rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  cursor: pointer;
  flex-shrink: 0;
  transition: background-color 0.15s;
}
.ticker-overlay-close:active {
  background: rgba(0, 0, 0, 0.06);
}
.ticker-overlay-close-icon {
  font-size: 28rpx;
  color: var(--color-text-placeholder);
}

/* ── 策略状态 ── */
.ticker-overlay-strategies {
  display: flex;
  flex-direction: column;
  gap: 16rpx;
  margin-bottom: 28rpx;
}
.ticker-strategy-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
  padding: 14rpx 16rpx;
  background: var(--color-bg-code, rgba(0, 0, 0, 0.03));
  border-radius: 12rpx;
}
.ticker-strategy-icon {
  font-size: 28rpx;
  flex-shrink: 0;
}
.ticker-strategy-label {
  font-size: 26rpx;
  color: var(--color-text-secondary);
  font-weight: 500;
  min-width: 120rpx;
}
.ticker-strategy-badge {
  font-size: 24rpx;
  font-weight: 600;
}
.ticker-strategy-in {
  color: var(--color-down, #34c759);
}
.ticker-strategy-score {
  font-size: 26rpx;
  font-weight: 700;
  color: var(--color-text-primary);
  font-family: var(--font-numeric);
  margin-left: auto;
}
.ticker-strategy-value {
  font-size: 26rpx;
  color: var(--color-text-secondary);
}

/* ── 不在白名单 ── */
.ticker-overlay-empty {
  padding: 32rpx 0;
  text-align: center;
}
.ticker-overlay-empty-text {
  font-size: 28rpx;
  color: var(--color-text-muted);
}

/* ── 操作按钮 ── */
.ticker-overlay-actions {
  display: flex;
  gap: 16rpx;
  margin-top: 8rpx;
}
.ticker-action-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20rpx 0;
  border-radius: 16rpx;
  cursor: pointer;
  transition: background-color 0.15s, box-shadow 0.15s;
}
.ticker-action-futu {
  background: var(--color-brand, #4285f4);
}
.ticker-action-futu .ticker-action-text {
  color: var(--color-text-white, #fff);
  font-weight: 600;
}
.ticker-action-futu:active {
  background: var(--color-brand-hover, #3b78dc);
}
.ticker-action-search {
  background: var(--color-bg-code, rgba(0, 0, 0, 0.03));
  border: 2rpx solid var(--color-border-divider);
}
.ticker-action-search .ticker-action-text {
  color: var(--color-text-secondary);
  font-weight: 500;
}
.ticker-action-search:active {
  background: var(--color-bg-section, rgba(0, 0, 0, 0.06));
}
.ticker-action-text {
  font-size: 26rpx;
}

/* ── PC / Tablet 适配 ── */
@media screen and (min-width: 768px) {
  :deep(.news-tag-ticker:hover) {
    background: rgba(255, 149, 0, 0.18);
  }

  .ticker-overlay {
    padding: 24px;
  }
  .ticker-overlay-card {
    max-width: 400px;
    border-radius: 16px;
    padding: 24px 24px 20px;
    box-shadow: 0 12px 48px rgba(0, 0, 0, 0.2);
  }
  .ticker-overlay-loading {
    padding: 36px 0;
  }
  .ticker-overlay-loading-text {
    font-size: 15px;
  }
  .ticker-overlay-header {
    gap: 8px;
    margin-bottom: 20px;
  }
  .ticker-overlay-code {
    font-size: 20px;
  }
  .ticker-overlay-name {
    font-size: 17px;
  }
  .ticker-overlay-close {
    width: 28px;
    height: 28px;
  }
  .ticker-overlay-close:hover {
    background: rgba(0, 0, 0, 0.06);
  }
  .ticker-overlay-close-icon {
    font-size: 15px;
  }
  .ticker-overlay-strategies {
    gap: 10px;
    margin-bottom: 20px;
  }
  .ticker-strategy-row {
    gap: 8px;
    padding: 10px 14px;
    border-radius: 8px;
  }
  .ticker-strategy-icon {
    font-size: 16px;
  }
  .ticker-strategy-label {
    font-size: 14px;
    min-width: 72px;
  }
  .ticker-strategy-badge {
    font-size: 13px;
  }
  .ticker-strategy-score {
    font-size: 14px;
  }
  .ticker-strategy-value {
    font-size: 14px;
  }
  .ticker-overlay-empty {
    padding: 24px 0;
  }
  .ticker-overlay-empty-text {
    font-size: 15px;
  }
  .ticker-overlay-actions {
    gap: 10px;
  }
  .ticker-action-btn {
    padding: 11px 0;
    border-radius: 10px;
  }
  .ticker-action-btn:hover {
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  }
  .ticker-action-futu:hover {
    background: var(--color-brand-hover, #3b78dc);
  }
  .ticker-action-search:hover {
    background: var(--color-bg-section, rgba(0, 0, 0, 0.05));
  }
  .ticker-action-text {
    font-size: 14px;
  }
}
</style>
