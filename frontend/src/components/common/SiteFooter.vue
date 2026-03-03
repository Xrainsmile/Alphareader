<template>
  <view
    class="site-footer"
    :style="{
      '--footer-mobile-padding': mobilePadding,
      '--footer-desktop-padding': desktopPadding,
    }"
  >
    <text class="footer-icp" @click="openIcp">{{ icpText }}</text>
    <text class="footer-copy">{{ copyText }}</text>
  </view>
</template>

<script setup>
const props = defineProps({
  icpText: {
    type: String,
    default: '蜀ICP备2026006985号',
  },
  copyText: {
    type: String,
    default: '© 2026 Rick',
  },
  icpUrl: {
    type: String,
    default: 'https://beian.miit.gov.cn/',
  },
  mobilePadding: {
    type: String,
    default: '48rpx 0 72rpx',
  },
  desktopPadding: {
    type: String,
    default: '32px 0 48px',
  },
})

const openIcp = () => {
  // #ifdef H5
  window.open(props.icpUrl, '_blank')
  // #endif
}
</script>

<style scoped>
.site-footer {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--footer-mobile-padding);
  gap: 8rpx;
}

.footer-icp {
  font-size: 22rpx;
  color: #b0b0be;
  text-decoration: underline;
}

.footer-copy {
  font-size: 22rpx;
  color: #b0b0be;
}

@media screen and (min-width: 768px) {
  .site-footer {
    padding: var(--footer-desktop-padding);
    gap: 6px;
  }

  .footer-icp {
    font-size: 12px;
    cursor: pointer;
  }

  .footer-icp:hover {
    color: #8c8c9a;
  }

  .footer-copy {
    font-size: 12px;
  }
}
</style>
