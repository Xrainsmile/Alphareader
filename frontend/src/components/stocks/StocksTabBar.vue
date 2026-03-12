<template>
  <view class="tab-bar">
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
      <text class="tab-text">VCP策略</text>
    </view>
    <view
      class="tab-item"
      :class="{ 'tab-active': activeTab === 'value' }"
      @click="$emit('select-value')"
    >
      <text class="tab-text">价投</text>
    </view>
    <view
      class="tab-item"
      :class="{ 'tab-active': activeTab === 'sandbox' }"
      @click="$emit('select-sandbox')"
    >
      <text class="tab-text">模拟仓</text>
    </view>
  </view>
</template>

<script setup>
defineProps({
  activeTab: {
    type: String,
    required: true,
  },
})

defineEmits(['select-rs', 'select-vcp', 'select-value', 'select-sandbox'])
</script>

<style scoped>
.tab-bar {
  display: flex;
  gap: 0;
  background: #ffffff;
  border-radius: 12rpx;
  margin: 16rpx 0 12rpx;
  padding: 4rpx;
  box-shadow: 0 1rpx 8rpx rgba(0, 0, 0, 0.04);
}
.tab-item {
  flex: 1;
  padding: 16rpx 0;
  text-align: center;
  border-radius: 10rpx;
  transition: all 0.2s;
  cursor: pointer;
}
.tab-active {
  background: #1a1a2e;
}
.tab-text {
  font-size: 28rpx;
  font-weight: 600;
  color: #8c8c9a;
}
.tab-active .tab-text {
  color: #ffffff;
}

@media screen and (min-width: 768px) {
  .tab-bar { margin: 12px 0 8px; padding: 3px; border-radius: 8px; }
  .tab-item { padding: 10px 0; border-radius: 7px; }
  .tab-text { font-size: 15px; }
}
</style>
