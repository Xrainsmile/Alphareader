<template>
  <view class="hot-topics">
    <!-- 说明 -->
    <view class="hot-intro">
      <text class="hot-intro-text">多家媒体正在跟进的同一事件，按信源数排序</text>
    </view>

    <view v-if="loading && items.length === 0" class="loading-container">
      <text class="loading-text">加载中...</text>
    </view>

    <view v-else-if="items.length === 0" class="empty-container">
      <text class="empty-text">暂无多信源热点事件</text>
    </view>

    <view v-else class="hot-list">
      <view
        v-for="(ev, idx) in items"
        :key="ev.id"
        class="hot-card"
        :class="{ 'hot-card-last': idx === items.length - 1 }"
        :data-news-id="ev.id"
        @click="$emit('open', ev.url, ev.id)"
      >
        <!-- 排名 + 信源数 -->
        <view class="hot-rank" :class="rankClass(ev.source_count)">
          <text class="hot-rank-num">{{ idx + 1 }}</text>
          <view class="hot-source-count">
            <text class="hot-flame">🔥</text>
            <text class="hot-source-num">{{ ev.source_count }}</text>
            <text class="hot-source-label">信源</text>
          </view>
        </view>

        <view class="hot-body">
          <text class="hot-title">{{ ev.title }}</text>

          <!-- 推荐理由 / 摘要 -->
          <view v-if="ev.why_it_matters" class="hot-why">
            <text class="why-icon">💡</text>
            <text class="why-text">{{ ev.why_it_matters }}</text>
          </view>
          <text v-else-if="ev.ai_summary" class="hot-summary">{{ ev.ai_summary }}</text>

          <!-- 信源 chips -->
          <view class="hot-sources">
            <text class="hot-source-chip hot-source-parent">{{ ev.source }}</text>
            <text
              v-for="s in ev.child_sources"
              :key="s"
              class="hot-source-chip"
            >{{ s }}</text>
          </view>

          <!-- 元信息 -->
          <view class="hot-meta">
            <text class="meta-source">{{ ev.source }}</text>
            <text class="meta-dot">·</text>
            <text class="meta-time">{{ formatTime(ev.published_at || ev.created_at) }}</text>
            <text v-if="ev.ai_score != null" class="meta-dot">·</text>
            <text v-if="ev.ai_score != null" class="meta-score">评分 {{ ev.ai_score }}</text>
          </view>

          <!-- 关联报道展开 -->
          <view v-if="ev.child_titles && ev.child_titles.length" class="hot-related">
            <view class="hot-related-toggle" @click.stop="toggle(ev.id)">
              <text class="hot-related-text">关联报道 ({{ ev.child_titles.length }}条)</text>
              <text class="hot-related-arrow" :class="{ 'hot-related-arrow-up': expanded[ev.id] }">›</text>
            </view>
            <view v-if="expanded[ev.id]" class="hot-related-list">
              <view
                v-for="(ct, i) in ev.child_titles"
                :key="i"
                class="hot-related-item"
              >
                <text class="hot-related-bullet">•</text>
                <text class="hot-related-title">{{ ct }}</text>
              </view>
            </view>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { reactive } from 'vue'
import { formatTime } from '../../utils/formatters.js'

defineProps({
  items: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})

defineEmits(['open'])

const expanded = reactive({})

/** 切换关联报道展开/折叠 */
function toggle(id) {
  expanded[id] = !expanded[id]
}

/** 热度等级：信源数越多越"热" */
function rankClass(count) {
  if (count >= 5) return 'hot-rank-top'
  if (count >= 3) return 'hot-rank-high'
  return 'hot-rank-normal'
}
</script>

<style scoped>
.hot-topics {
  padding-bottom: 20rpx;
}
.hot-intro {
  padding: 8rpx 4rpx 16rpx;
}
.hot-intro-text {
  font-size: 22rpx;
  color: var(--color-text-muted);
}
.hot-list {
  background: var(--color-bg-card);
  border-radius: 20rpx;
  box-shadow: 0 2rpx 16rpx rgba(0, 0, 0, 0.05);
  overflow: hidden;
}
.hot-card {
  display: flex;
  padding: 28rpx 28rpx;
  border-bottom: 1rpx solid var(--color-border-light);
  cursor: pointer;
  transition: background-color 0.15s;
}
.hot-card-last {
  border-bottom: none;
}
.hot-card:active {
  background-color: var(--color-bg-hover);
}

/* 排名 + 信源数 */
.hot-rank {
  flex-shrink: 0;
  width: 76rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-right: 20rpx;
}
.hot-rank-num {
  font-size: 36rpx;
  font-weight: 800;
  font-family: var(--font-numeric);
  color: var(--color-text-placeholder);
}
.hot-rank-top .hot-rank-num {
  color: var(--color-up);
}
.hot-rank-high .hot-rank-num {
  color: var(--color-warning);
}
.hot-source-count {
  display: flex;
  align-items: center;
  gap: 2rpx;
  margin-top: 6rpx;
  padding: 2rpx 8rpx;
  border-radius: 12rpx;
  background: rgba(255, 59, 48, 0.1);
}
.hot-flame {
  font-size: 18rpx;
}
.hot-source-num {
  font-size: 22rpx;
  font-weight: 700;
  color: var(--color-up);
  font-family: var(--font-numeric);
}
.hot-source-label {
  font-size: 18rpx;
  color: var(--color-text-muted);
}

.hot-body {
  flex: 1;
  min-width: 0;
}
.hot-title {
  font-size: 30rpx;
  font-weight: 600;
  color: var(--color-text-primary);
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-family: var(--font-sans);
}
.hot-why {
  display: flex;
  align-items: flex-start;
  gap: 8rpx;
  margin-top: 10rpx;
  padding: 10rpx 16rpx;
  background: rgba(255, 149, 0, 0.08);
  border-left: 4rpx solid var(--color-warning);
  border-radius: 8rpx;
}
.why-icon {
  font-size: 22rpx;
  line-height: 1.5;
  flex-shrink: 0;
}
.why-text {
  font-size: 24rpx;
  color: var(--color-text-secondary);
  line-height: 1.5;
  font-weight: 500;
}
.hot-summary {
  font-size: 25rpx;
  color: var(--color-text-tertiary);
  line-height: 1.55;
  margin-top: 10rpx;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* 信源 chips */
.hot-sources {
  display: flex;
  flex-wrap: wrap;
  gap: 8rpx;
  margin-top: 12rpx;
}
.hot-source-chip {
  font-size: 20rpx;
  color: var(--color-text-muted);
  background: var(--color-bg-code);
  border-radius: 6rpx;
  padding: 4rpx 12rpx;
  line-height: 1.6;
}
.hot-source-parent {
  color: var(--color-brand);
  background: rgba(66, 133, 244, 0.08);
  font-weight: 500;
}

/* 元信息 */
.hot-meta {
  display: flex;
  align-items: center;
  margin-top: 12rpx;
  gap: 8rpx;
}
.meta-source {
  font-size: 22rpx;
  color: var(--color-text-muted);
  font-weight: 500;
}
.meta-dot {
  font-size: 22rpx;
  color: var(--color-border-hover);
}
.meta-time {
  font-size: 22rpx;
  color: var(--color-text-placeholder);
}
.meta-score {
  font-size: 22rpx;
  color: var(--color-text-muted);
}

/* 关联报道 */
.hot-related {
  margin-top: 10rpx;
}
.hot-related-toggle {
  display: flex;
  align-items: center;
  gap: 6rpx;
  padding: 10rpx 16rpx;
  cursor: pointer;
  border-radius: 12rpx;
  transition: background-color 0.15s;
  -webkit-tap-highlight-color: transparent;
}
.hot-related-toggle:active {
  background: rgba(0, 0, 0, 0.04);
}
.hot-related-text {
  font-size: 22rpx;
  color: var(--color-text-muted);
  font-weight: 500;
}
.hot-related-arrow {
  font-size: 22rpx;
  color: var(--color-text-placeholder);
  transform: rotate(90deg);
  transition: transform 0.25s ease;
}
.hot-related-arrow-up {
  transform: rotate(-90deg);
}
.hot-related-list {
  margin: 4rpx 0 0 16rpx;
  padding-left: 16rpx;
  border-left: 3rpx solid var(--color-border);
}
.hot-related-item {
  display: flex;
  align-items: flex-start;
  padding: 10rpx 8rpx;
  gap: 10rpx;
}
.hot-related-bullet {
  font-size: 22rpx;
  color: var(--color-text-placeholder);
  flex-shrink: 0;
  line-height: 1.5;
}
.hot-related-title {
  font-size: 24rpx;
  color: var(--color-text-secondary);
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.loading-container,
.empty-container {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 120rpx 0;
}
.loading-text,
.empty-text {
  color: var(--color-text-placeholder);
  font-size: 28rpx;
}

/* ═════════════════════════════════════════════════
   PC / Tablet 适配
   ═══════════════════════════════════════════════ */
@media screen and (min-width: 768px) {
  .hot-topics {
    padding-bottom: 16px;
  }
  .hot-intro {
    padding: 6px 4px 12px;
  }
  .hot-intro-text {
    font-size: 13px;
  }
  .hot-list {
    border-radius: 14px;
    box-shadow: 0 1px 12px rgba(0, 0, 0, 0.06);
  }
  .hot-card {
    padding: 20px 24px;
    transition: background-color 0.2s;
  }
  .hot-card:hover {
    background-color: var(--color-bg-hover);
  }
  .hot-rank {
    width: 48px;
    margin-right: 16px;
  }
  .hot-rank-num {
    font-size: 22px;
  }
  .hot-source-count {
    margin-top: 4px;
    padding: 1px 8px;
    border-radius: 10px;
  }
  .hot-flame {
    font-size: 11px;
  }
  .hot-source-num {
    font-size: 12px;
  }
  .hot-source-label {
    font-size: 11px;
  }
  .hot-title {
    font-size: 16px;
    line-height: 1.5;
  }
  .hot-why {
    gap: 6px;
    margin-top: 6px;
    padding: 6px 12px;
    border-radius: 6px;
  }
  .why-icon {
    font-size: 12px;
  }
  .why-text {
    font-size: 13px;
  }
  .hot-summary {
    font-size: 13.5px;
    margin-top: 6px;
    line-height: 1.6;
  }
  .hot-sources {
    gap: 6px;
    margin-top: 8px;
  }
  .hot-source-chip {
    font-size: 11px;
    border-radius: 4px;
    padding: 2px 8px;
  }
  .hot-meta {
    margin-top: 8px;
    gap: 6px;
  }
  .meta-source,
  .meta-dot,
  .meta-time,
  .meta-score {
    font-size: 12px;
  }
  .hot-related-toggle {
    padding: 6px 12px;
    border-radius: 8px;
  }
  .hot-related-toggle:hover {
    background: rgba(0, 0, 0, 0.03);
  }
  .hot-related-text {
    font-size: 13px;
  }
  .hot-related-arrow {
    font-size: 13px;
  }
  .hot-related-list {
    margin: 2px 0 0 12px;
    padding-left: 12px;
    border-left-width: 2px;
  }
  .hot-related-item {
    padding: 6px 8px;
    gap: 8px;
  }
  .hot-related-bullet {
    font-size: 12px;
  }
  .hot-related-title {
    font-size: 13px;
  }
  .loading-container,
  .empty-container {
    padding: 80px 0;
  }
  .loading-text,
  .empty-text {
    font-size: 15px;
  }
}
</style>
