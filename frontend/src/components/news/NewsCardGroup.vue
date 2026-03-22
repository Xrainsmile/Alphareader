<template>
  <view class="news-card-group" :class="{ 'news-card-group-last': isLast }">
    <!-- 主卡片 -->
    <NewsCard
      :item="group"
      :show-gravity="showGravity"
      :children-count="group.children ? group.children.length : 0"
      @open="(url, id) => $emit('open', url, id)"
      @tag-search="(tag) => $emit('tag-search', tag)"
      @ticker-click="(code) => $emit('ticker-click', code)"
    />

    <!-- 关联报道折叠区 -->
    <view v-if="group.children && group.children.length" class="related-section">
      <view class="related-toggle" @click.stop="$emit('toggle-related', group.id)">
        <text class="related-toggle-text">关联报道 ({{ group.children.length }}条)</text>
        <text class="related-toggle-arrow" :class="{ 'related-toggle-arrow-up': expanded }">›</text>
      </view>

      <!-- 展开的子卡片列表 -->
      <view v-if="expanded" class="related-list">
        <view
          v-for="child in group.children"
          :key="child.id"
          class="related-item"
          @click.stop="$emit('open', child.url, child.id)"
        >
          <text class="related-bullet">•</text>
          <view class="related-item-body">
            <text class="related-item-title">{{ child.title }}</text>
            <view class="related-item-meta">
              <text class="related-item-source">{{ child.source }}</text>
              <text class="meta-dot">·</text>
              <text class="related-item-time">{{ formatTime(child.published_at || child.created_at) }}</text>
            </view>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { formatTime } from '../../utils/formatters.js'
import NewsCard from './NewsCard.vue'

defineProps({
  group: { type: Object, required: true },
  isLast: { type: Boolean, default: false },
  expanded: { type: Boolean, default: false },
  showGravity: { type: Boolean, default: false },
})

defineEmits(['open', 'tag-search', 'toggle-related', 'ticker-click'])
</script>
