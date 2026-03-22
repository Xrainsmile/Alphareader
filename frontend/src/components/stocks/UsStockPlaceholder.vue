<template>
  <view class="us-placeholder">
    <view class="us-placeholder-icon">
      <text class="us-icon-text">🇺🇸</text>
    </view>
    <view class="us-placeholder-content">
      <text class="us-title">{{ title }}</text>
      <text class="us-subtitle">{{ subtitle }}</text>
    </view>
    <view class="us-feature-list">
      <view v-for="(feat, idx) in features" :key="idx" class="us-feature-item">
        <text class="us-feature-dot">{{ feat.icon }}</text>
        <text class="us-feature-text">{{ feat.text }}</text>
      </view>
    </view>
    <view class="us-coming-badge">
      <text class="us-coming-text">🚀 即将上线</text>
    </view>
  </view>
</template>

<script setup>
defineProps({
  title: {
    type: String,
    default: '美股策略',
  },
  subtitle: {
    type: String,
    default: '基于 Minervini/IBD 方法论的美股选股系统正在开发中',
  },
  features: {
    type: Array,
    default: () => [
      { icon: '📊', text: 'US Market Stage2 趋势筛选（基于 yfinance 日线数据）' },
      { icon: '💪', text: 'RS Rating — 美股相对强度排名' },
      { icon: '🔥', text: '新闻催化剂 × 技术面交叉验证' },
      { icon: '🌍', text: '美东时间自动调度，盘后自动运行' },
    ],
  },
})
</script>

<style scoped>
.us-placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 80rpx 40rpx 60rpx;
  text-align: center;
}

.us-placeholder-icon {
  width: 120rpx;
  height: 120rpx;
  border-radius: 50%;
  background: rgba(59, 130, 246, 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 32rpx;
}
.us-icon-text {
  font-size: 56rpx;
  line-height: 1;
}

.us-placeholder-content {
  margin-bottom: 40rpx;
}
.us-title {
  font-size: 36rpx;
  font-weight: 800;
  color: var(--color-text-primary);
  display: block;
  margin-bottom: 12rpx;
  font-family: var(--font-display);
}
.us-subtitle {
  font-size: 26rpx;
  color: var(--color-text-muted);
  line-height: 1.6;
  display: block;
}

.us-feature-list {
  display: flex;
  flex-direction: column;
  gap: 18rpx;
  width: 100%;
  background: var(--color-bg-card);
  border-radius: 16rpx;
  padding: 28rpx 32rpx;
  margin-bottom: 40rpx;
  box-shadow: 0 1rpx 8rpx rgba(0, 0, 0, 0.04);
}
.us-feature-item {
  display: flex;
  align-items: center;
  gap: 14rpx;
}
.us-feature-dot {
  font-size: 28rpx;
  flex-shrink: 0;
}
.us-feature-text {
  font-size: 26rpx;
  color: var(--color-text-body);
  text-align: left;
  line-height: 1.5;
}

.us-coming-badge {
  padding: 14rpx 40rpx;
  border-radius: 32rpx;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.12) 0%, rgba(139, 92, 246, 0.12) 100%);
  border: 2rpx solid rgba(59, 130, 246, 0.2);
}
.us-coming-text {
  font-size: 28rpx;
  font-weight: 700;
  color: var(--color-accent);
  letter-spacing: 2rpx;
}

/* ── PC 适配 ── */
@media screen and (min-width: 768px) {
  .us-placeholder { padding: 60px 32px 48px; }
  .us-placeholder-icon { width: 72px; height: 72px; margin-bottom: 20px; }
  .us-icon-text { font-size: 36px; }
  .us-title { font-size: 22px; margin-bottom: 8px; }
  .us-subtitle { font-size: 14px; }
  .us-feature-list { padding: 20px 24px; border-radius: 12px; margin-bottom: 28px; gap: 12px; }
  .us-feature-dot { font-size: 16px; }
  .us-feature-text { font-size: 14px; }
  .us-coming-badge { padding: 8px 28px; border-radius: 20px; border-width: 1px; }
  .us-coming-text { font-size: 15px; letter-spacing: 1px; }
}
</style>
