<template>
  <view
    class="empty-state"
    :style="{
      padding: mobilePadding,
      background: bg,
      borderRadius: radius,
      '--empty-desktop-padding': desktopPadding,
    }"
  >
    <text class="empty-text">{{ text }}</text>
  </view>
</template>

<script setup>
defineProps({
  text: {
    type: String,
    default: '暂无数据',
  },
  mobilePadding: {
    type: String,
    default: '120rpx 0',
  },
  desktopPadding: {
    type: String,
    default: '80px 0',
  },
  bg: {
    type: String,
    default: 'transparent',
  },
  radius: {
    type: String,
    default: '0',
  },
})
</script>

<style scoped>
.empty-state {
  display: flex;
  justify-content: center;
  align-items: center;
}

.empty-text {
  font-size: 28rpx;
  color: var(--color-text-placeholder);
}

@media screen and (min-width: 768px) {
  .empty-state {
    padding: var(--empty-desktop-padding) !important;
  }

  .empty-text {
    font-size: 15px;
  }
}
</style>
