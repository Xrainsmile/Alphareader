<template>
  <!-- 筛选按钮 + 已选标签 + 浮窗面板 -->
  <view class="filter-anchor">
    <view class="filter-trigger-bar">
      <view class="filter-trigger-left">
        <view class="filter-trigger-btn" :class="{ 'filter-trigger-active': hasActiveFilter || filterOpen }" @click="$emit('toggle')">
          <text class="filter-trigger-icon">☰</text>
          <text class="filter-trigger-text">筛选</text>
          <text class="filter-arrow" :class="{ 'filter-arrow-up': filterOpen }">›</text>
        </view>
        <view v-if="filterTags.length" class="filter-tags">
          <view v-for="tag in filterTags" :key="tag" class="filter-tag">
            <text class="filter-tag-text">{{ tag }}</text>
          </view>
        </view>
      </view>
      <text class="stats-text-inline">{{ total }} 条</text>
    </view>

    <!-- 筛选浮窗 -->
    <view v-if="filterOpen" class="filter-popover">
      <view class="filter-popover-body">
        <!-- 排序 -->
        <view class="filter-row">
          <text class="filter-row-label">排序</text>
          <view class="filter-row-chips">
            <view
              v-for="tab in sortTabs"
              :key="tab.value"
              class="fc"
              :class="{ 'fc-active': tmpSort === tab.value, 'fc-gravity': tab.value === 'hot' }"
              @click="$emit('update:tmpSort', tab.value)"
            >
              <text class="fc-text" :class="{ 'fc-text-active': tmpSort === tab.value }">{{ tab.label }}</text>
              <view v-if="tab.value === 'hot'" class="gravity-tooltip">基于 Hacker News 经典重力算法：高评分的新鲜资讯排在前面，随时间自然下沉</view>
            </view>
          </view>
        </view>
        <!-- 时效 -->
        <view class="filter-row">
          <text class="filter-row-label">时效</text>
          <view class="filter-row-chips">
            <view
              v-for="opt in ageOptions"
              :key="opt.value"
              class="fc"
              :class="{ 'fc-active': tmpAge === opt.value }"
              @click="$emit('update:tmpAge', opt.value)"
            >
              <text class="fc-text" :class="{ 'fc-text-active': tmpAge === opt.value }">{{ opt.label }}</text>
            </view>
          </view>
        </view>
        <!-- 来源 -->
        <view class="filter-row">
          <text class="filter-row-label">来源</text>
          <view class="filter-row-chips filter-row-chips-wrap">
            <view class="fc" :class="{ 'fc-active': !tmpSource }" @click="$emit('update:tmpSource', '')">
              <text class="fc-text" :class="{ 'fc-text-active': !tmpSource }">全部</text>
            </view>
            <view
              v-for="src in cnSources"
              :key="src"
              class="fc"
              :class="{ 'fc-active': tmpSource === src }"
              @click="$emit('update:tmpSource', src)"
            >
              <text class="fc-text" :class="{ 'fc-text-active': tmpSource === src }">{{ src }}</text>
            </view>
            <view class="fc-divider"></view>
            <view
              v-for="src in enSources"
              :key="src"
              class="fc"
              :class="{ 'fc-active': tmpSource === src }"
              @click="$emit('update:tmpSource', src)"
            >
              <text class="fc-text" :class="{ 'fc-text-active': tmpSource === src }">{{ src }}</text>
            </view>
            <view class="fc-divider"></view>
            <view
              v-for="src in techSources"
              :key="src"
              class="fc"
              :class="{ 'fc-active': tmpSource === src }"
              @click="$emit('update:tmpSource', src)"
            >
              <text class="fc-text" :class="{ 'fc-text-active': tmpSource === src }">{{ src }}</text>
            </view>
          </view>
        </view>
        <!-- 评分 -->
        <view class="filter-row filter-row-last">
          <text class="filter-row-label">评分</text>
          <view class="filter-row-chips">
            <view
              v-for="s in scoreOptions"
              :key="s"
              class="fc"
              :class="{ 'fc-active': tmpScore === s }"
              @click="$emit('update:tmpScore', s)"
            >
              <text class="fc-text" :class="{ 'fc-text-active': tmpScore === s }">≥{{ s }}</text>
            </view>
          </view>
        </view>
        <!-- 底部操作栏 -->
        <view class="filter-footer">
          <view class="filter-reset-btn" @click="$emit('reset')">
            <text class="filter-reset-text">重置</text>
          </view>
          <view class="filter-confirm-btn" @click="$emit('confirm')">
            <text class="filter-confirm-text">确认</text>
          </view>
        </view>
      </view>
    </view>
  </view>

  <!-- 浮窗背景遮罩 -->
  <view v-if="filterOpen" class="filter-backdrop" @click="$emit('cancel')"></view>
</template>

<script setup>
defineProps({
  filterOpen: { type: Boolean, default: false },
  hasActiveFilter: { type: Boolean, default: false },
  filterTags: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  // 面板暂存值
  tmpSort: { type: String, default: 'hot' },
  tmpAge: { type: Number, default: 72 },
  tmpSource: { type: String, default: '' },
  tmpScore: { type: Number, default: 5 },
  // 常量配置
  sortTabs: { type: Array, default: () => [] },
  ageOptions: { type: Array, default: () => [] },
  cnSources: { type: Array, default: () => [] },
  enSources: { type: Array, default: () => [] },
  techSources: { type: Array, default: () => [] },
  scoreOptions: { type: Array, default: () => [] },
})

defineEmits([
  'toggle',
  'confirm',
  'cancel',
  'reset',
  'update:tmpSort',
  'update:tmpAge',
  'update:tmpSource',
  'update:tmpScore',
])
</script>
