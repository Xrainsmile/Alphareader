<template>
  <view class="market-switcher">
    <view
      class="market-item"
      :class="{ 'market-active': activeMarket === 'CN' }"
      @click="$emit('switch', 'CN')"
    >
      <text class="market-flag">🇨🇳</text>
      <text class="market-label">A-Shares</text>
    </view>
    <view
      class="market-item"
      :class="{ 'market-active': activeMarket === 'US' }"
      @click="$emit('switch', 'US')"
    >
      <text class="market-flag">🇺🇸</text>
      <text class="market-label">US Stocks</text>
    </view>
  </view>
</template>

<script setup>
defineProps({
  activeMarket: {
    type: String,
    required: true,
    validator: (v) => ['CN', 'US'].includes(v),
  },
})

defineEmits(['switch'])
</script>

<style scoped>
.market-switcher {
  display: flex;
  gap: 0;
  background: var(--color-bg-card);
  border-radius: var(--radius-r-md);
  padding: 6rpx;
  box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.06);
  margin-bottom: 4rpx;
}
.market-item {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  padding: 20rpx 0;
  border-radius: var(--radius-r-md);
  cursor: pointer;
  transition: all 0.25s ease;
  position: relative;
}
.market-active {
  background: var(--color-text-primary);
  box-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.15);
}
.market-flag {
  font-size: 28rpx;
  line-height: 1;
}
.market-label {
  font-size: 30rpx;
  font-weight: 700;
  color: var(--color-text-secondary);
  letter-spacing: 1rpx;
}
.market-active .market-label {
  color: var(--color-text-white);
}

/* ── PC 适配 ── */
@media screen and (min-width: 768px) {
  .market-switcher {
    border-radius: var(--radius-p-xl);
    padding: var(--space-1);
    margin-bottom: 2px;
  }
  .market-item {
    padding: 12px 0;
    border-radius: var(--radius-p-lg);
    gap: 6px;
  }
  .market-flag { font-size: 16px; }
  .market-label { font-size: 16px; letter-spacing: 0.5px; }
}
</style>
