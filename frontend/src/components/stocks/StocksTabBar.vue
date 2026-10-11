<template>
  <view class="tab-bar">
    <template v-if="market === 'CN'">
      <!-- A股策略 Tab -->
      <!-- RS Rating Tab 暂时隐藏，后端服务继续运行 -->
      <!-- <view
        class="tab-item"
        :class="{ 'tab-active': activeTab === 'rs' }"
        @click="$emit('select-rs')"
      >
        <text class="tab-text">RS Rating</text>
      </view> -->
      <view
        class="tab-item"
        :class="{ 'tab-active': activeTab === 'vcp' }"
        @click="$emit('select-vcp')"
      >
        <text class="tab-text">VCP</text>
      </view>
      <view
        class="tab-item"
        :class="{ 'tab-active': activeTab === 'trend' }"
        @click="$emit('select-trend')"
      >
        <text class="tab-text">Right-Side Trend</text>
      </view>
      <view
        class="tab-item"
        :class="{ 'tab-active': activeTab === 'catalyst' }"
        @click="$emit('select-catalyst')"
      >
        <text class="tab-text">🔥 Catalyst</text>
      </view>
      <view
        class="tab-item"
        :class="{ 'tab-active': activeTab === 'value' }"
        @click="$emit('select-value')"
      >
        <text class="tab-text">Value</text>
      </view>
      <view
        class="tab-item"
        :class="{ 'tab-active': activeTab === 'sandbox' }"
        @click="$emit('select-sandbox')"
      >
        <text class="tab-text">Sandbox</text>
      </view>
    </template>

    <template v-else>
      <!-- 美股策略 Tab -->
      <view
        class="tab-item"
        :class="{ 'tab-active': activeTab === 'us_vcp' }"
        @click="$emit('select-us-vcp')"
      >
        <text class="tab-text">VCP</text>
      </view>
      <view
        class="tab-item"
        :class="{ 'tab-active': activeTab === 'us_trend' }"
        @click="$emit('select-us-trend')"
      >
        <text class="tab-text">Right-Side Trend</text>
      </view>
      <view
        class="tab-item"
        :class="{ 'tab-active': activeTab === 'us_catalyst' }"
        @click="$emit('select-us-catalyst')"
      >
        <text class="tab-text">🔥 Catalyst</text>
      </view>
    </template>
  </view>
</template>

<script setup>
defineProps({
  activeTab: {
    type: String,
    required: true,
  },
  market: {
    type: String,
    default: 'CN',
    validator: (v) => ['CN', 'US'].includes(v),
  },
})

defineEmits([
  'select-rs', 'select-vcp', 'select-trend', 'select-catalyst', 'select-value', 'select-sandbox',
  'select-us-vcp', 'select-us-trend', 'select-us-catalyst',
])
</script>

<style scoped>
.tab-bar {
  display: flex;
  gap: 0;
  background: var(--color-bg-card);
  border-radius: var(--radius-r-md);
  margin: 16rpx 0 12rpx;
  padding: 4rpx;
  box-shadow: 0 1rpx 8rpx rgba(0, 0, 0, 0.04);
}
.tab-item {
  flex: 1;
  padding: 16rpx 0;
  text-align: center;
  border-radius: var(--radius-r-md);
  transition: all 0.2s;
  cursor: pointer;
}
.tab-active {
  background: var(--color-text-primary);
}
.tab-text {
  font-size: 28rpx;
  font-weight: 600;
  color: var(--color-text-muted);
}
.tab-active .tab-text {
  color: var(--color-text-white);
}

@media screen and (min-width: 768px) {
  .tab-bar { margin: 12px 0 8px; padding: 3px; border-radius: var(--radius-p-lg); }
  .tab-item { padding: 10px 0; border-radius: var(--radius-p-lg); }
  .tab-text { font-size: 15px; }
}
</style>
