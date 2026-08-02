<template>
  <svg
    class="icon-svg"
    :style="{ width: size, height: size }"
    viewBox="0 0 24 24"
    fill="none"
    :stroke="color"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <!-- 本时段变化 -->
    <template v-if="name === 'change'">
      <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
      <path d="M21 3v5h-5" />
      <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
      <path d="M3 21v-5h5" />
    </template>
    <!-- 最新变化 -->
    <template v-else-if="name === 'new'">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v8M8 12h8" />
    </template>
    <!-- 接下来关注（watch_next） -->
    <template v-else-if="name === 'eye'">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
    </template>
    <!-- 收录统计 -->
    <template v-else-if="name === 'chart'">
      <path d="M3 3v18h18" />
      <rect x="7" y="10" width="3" height="8" rx="0.5" />
      <rect x="13" y="6" width="3" height="12" rx="0.5" />
    </template>
    <!-- 今日简报 -->
    <template v-else-if="name === 'news'">
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9Z" />
      <path d="M14 3v6h6" />
      <path d="M8 13h8M8 17h6" />
    </template>
    <!-- 每日研报 -->
    <template v-else-if="name === 'briefing'">
      <path d="M3 3v18h18" />
      <path d="m7 14 3-4 3 3 4-6" />
    </template>
    <!-- 情绪色点（替代 🟢🔴🟡⚪） -->
    <template v-else-if="name === 'dot'">
      <circle cx="12" cy="12" r="6" :fill="color" stroke="none" />
    </template>
    <!-- 核心标的 tier_s -->
    <template v-else-if="name === 'target'">
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <circle cx="12" cy="12" r="1.5" />
    </template>
    <!-- 观察标的 tier_a -->
    <template v-else-if="name === 'clipboard'">
      <rect x="6" y="4" width="12" height="17" rx="2" />
      <path d="M9 4V3h6v1" />
      <path d="M9 10h6M9 14h6" />
    </template>
    <!-- 风险 tier_x -->
    <template v-else-if="name === 'warning'">
      <path d="M12 3 2 20h20Z" />
      <path d="M12 9v5" />
      <path d="M12 17h.01" />
    </template>
    <!-- 生成耗时 -->
    <template v-else-if="name === 'clock'">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </template>
    <!-- 时段图标 -->
    <template v-else-if="name === 'sunrise'">
      <path d="M12 2v4" />
      <path d="M12 8a4 4 0 0 0 0 8" />
      <path d="m6 6 1.5 1.5M17.5 7.5 19 6" />
      <path d="M3 18h18" />
      <path d="M5 14a7 7 0 0 1 14 0" />
    </template>
    <template v-else-if="name === 'sun'">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </template>
    <template v-else-if="name === 'sunset'">
      <path d="M12 10V2" />
      <path d="M12 10a4 4 0 0 0 0 8" />
      <path d="m6 18 1.5-1.5M17.5 16.5 19 18" />
      <path d="M3 6h18" />
      <path d="M5 10a7 7 0 0 0 14 0" />
    </template>
    <template v-else-if="name === 'moon'">
      <path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8Z" />
    </template>
    <template v-else>
      <circle cx="12" cy="12" r="9" />
    </template>
  </svg>
</template>

<script setup>
defineProps({
  name: { type: String, required: true },
  size: { type: String, default: '1em' },
  color: { type: String, default: 'currentColor' },
})
</script>

<style scoped>
.icon-svg {
  display: inline-block;
  vertical-align: -0.125em;
  flex: none;
}
</style>
