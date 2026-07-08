<template>
  <view class="news-card" :data-news-id="item.id" @click="$emit('open', item.url, item.id)">
    <!-- Score Badge -->
    <view class="score-badge" :class="scoreClass(item.ai_score)">
      <text class="score-num">{{ formatScore(item.ai_score) }}</text>
    </view>

    <view class="news-body">
      <!-- 搜索模式下使用 rich-text 高亮 -->
      <rich-text v-if="highlighted" class="news-title search-highlight" :nodes="item.title_highlighted || item.title"></rich-text>
      <text v-else class="news-title">{{ item.title }}</text>

      <rich-text v-if="highlighted && (item.summary_highlighted || item.ai_summary)" class="news-summary search-highlight" :nodes="item.summary_highlighted || item.ai_summary || ''"></rich-text>
      <text v-else-if="item.ai_summary" class="news-summary">{{ item.ai_summary }}</text>

      <!-- 推荐理由（why_it_matters）：一句话告诉用户为什么该关注 -->
      <view v-if="item.why_it_matters" class="news-why">
        <text class="why-icon">💡</text>
        <text class="why-text">{{ item.why_it_matters }}</text>
      </view>

      <!-- Tags -->
      <view v-if="item.tags && item.tags.length" class="news-tags">
        <text
          v-for="tag in item.tags"
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
        <!-- Hacker Gravity 指标 -->
        <template v-if="showGravity && item.ranking_score != null">
          <text class="meta-dot">·</text>
          <view class="gravity-badge" :class="gravityClass(computedGravity)">
            <text class="gravity-icon">⚡</text>
            <text class="gravity-value">{{ formatGravity(computedGravity) }}</text>
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
        <template v-if="item.sentiment_score != null">
          <text class="meta-dot">·</text>
          <view class="sentiment-badge" :class="sentimentClass(item.sentiment_score)">
            <text class="sentiment-icon">{{ sentimentIcon(item.sentiment_score) }}</text>
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
  formatGravity,
  gravityClass,
  sentimentClass,
  sentimentIcon,
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
</script>
