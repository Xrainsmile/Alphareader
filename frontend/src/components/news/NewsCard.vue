<template>
  <view class="news-card" :class="{ 'density-compact': isCompact }" :data-news-id="item.id" @click="$emit('open', item.url, item.id)">
    <!-- Score Badge -->
    <view class="score-badge" :class="scoreClass(item.ai_score)">
      <text class="score-num">{{ formatScore(item.ai_score) }}</text>
    </view>

    <view class="news-body">
      <!-- 搜索模式下使用 rich-text 高亮 -->
      <rich-text v-if="highlighted" class="news-title search-highlight" :nodes="item.title_highlighted || item.title"></rich-text>
      <text v-else class="news-title">{{ item.title }}</text>

      <rich-text v-if="highlighted && (item.summary_highlighted || item.ai_summary)" class="news-summary search-highlight" :nodes="item.summary_highlighted || item.ai_summary || ''"></rich-text>
      <text v-else-if="!isCompact && item.ai_summary" class="news-summary">{{ item.ai_summary }}</text>

      <!-- 推荐理由（why_it_matters）：一句话告诉用户为什么该关注 -->
      <view v-if="!isCompact && item.why_it_matters" class="news-why">
        <view class="why-icon-svg"></view>
        <text class="why-text">{{ item.why_it_matters }}</text>
      </view>

      <!-- Tags -->
      <view v-if="displayTags.length" class="news-tags">
        <text
          v-for="tag in displayTags"
          :key="tag"
          class="news-tag"
          :class="isTickerTag(tag) ? 'news-tag-ticker' : 'news-tag-clickable'"
          @click.stop="onTagClick(tag)"
        >{{ tag }}</text>
      </view>

      <view class="news-meta">
        <text class="meta-source">{{ item.source }}</text>
        <text class="meta-dot">·</text>
        <text class="meta-time">{{ formatTime(item.published_at || item.created_at) }}</text>
        <!-- 多信源聚合：同一事件被多家媒体报道时的信源数徽标 -->
        <template v-if="density === 'detailed' && childrenCount > 0">
          <text class="meta-dot">·</text>
          <view class="source-count-badge">
            <view class="source-count-icon-svg"></view>
            <text class="source-count-text">{{ childrenCount + 1 }} 信源</text>
          </view>
        </template>
        <!-- Hacker Gravity 指标 -->
        <template v-if="!isCompact && showGravity && item.ranking_score != null">
          <text class="meta-dot">·</text>
          <view class="gravity-badge" :class="gravityClass(computedGravity)">
            <text class="gravity-value">{{ gravityStars(computedGravity) }}</text>
          </view>
        </template>
        <!-- 搜索相关度 -->
        <template v-if="item.relevance_score != null">
          <text class="meta-dot">·</text>
          <view class="relevance-badge">
            <text class="relevance-label">相关度</text>
            <text class="relevance-value">{{ formatRelevance(item.relevance_score) }}</text>
          </view>
        </template>
        <!-- 情绪指标 -->
        <template v-if="density === 'detailed' && item.sentiment_score != null">
          <text class="meta-dot">·</text>
          <view class="sentiment-badge" :class="sentimentClass(item.sentiment_score)">
            <view v-if="item.sentiment_score > 0" class="sentiment-icon-svg sentiment-icon-up"></view>
            <view v-else-if="item.sentiment_score < 0" class="sentiment-icon-svg sentiment-icon-down"></view>
            <text v-else class="sentiment-icon">—</text>
            <text class="sentiment-value">{{ item.sentiment_score > 0 ? '+' : '' }}{{ item.sentiment_score }}</text>
          </view>
        </template>
      </view>
    </view>
  </view>
</template>

<script setup>
import { computed } from 'vue'
import {
  scoreClass,
  formatScore,
  formatTime,
  gravityStars,
  gravityClass,
  sentimentClass,
  formatRelevance,
} from '../../utils/formatters.js'

const props = defineProps({
  item: { type: Object, required: true },
  /** 是否为搜索高亮模式 */
  highlighted: { type: Boolean, default: false },
  /** 是否显示 Gravity 指标 */
  showGravity: { type: Boolean, default: false },
  /** 子新闻数量（用于计算聚合热度加成） */
  childrenCount: { type: Number, default: 0 },
  /** 密度模式: compact(紧凑) / standard(标准) / detailed(详情) */
  density: { type: String, default: 'standard' },
})

const emit = defineEmits(['open', 'tag-search', 'ticker-click'])

/** 判断 tag 是否为 ticker 标签（以 $ 开头） */
function isTickerTag(tag) {
  return tag.startsWith('$')
}

/** 点击 tag：ticker 标签触发 ticker-click，普通标签触发 tag-search */
function onTagClick(tag) {
  if (isTickerTag(tag)) {
    // 去掉 $ 前缀传给上层
    emit('ticker-click', tag.slice(1))
  } else {
    emit('tag-search', tag)
  }
}

/** 聚合热度计算：base + children * 0.2 */
const computedGravity = computed(() => {
  const base = props.item.ranking_score || 0
  const boost = props.childrenCount > 0 ? props.childrenCount * 0.2 : 0
  return base + boost
})

/** 根据密度模式决定显示的标签数量 */
const displayTags = computed(() => {
  const tags = props.item.tags || []
  if (props.density === 'compact') return tags.slice(0, 1)
  return tags
})

/** 是否为紧凑模式 */
const isCompact = computed(() => props.density === 'compact')
</script>
