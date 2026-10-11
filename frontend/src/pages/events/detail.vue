<template>
  <view class="event-detail-page">
    <view v-if="loading" class="state-box"><text class="state-text">Loading...</text></view>
    <view v-else-if="!event" class="state-box"><text class="state-text">Event not found or deleted</text></view>

    <template v-else>
      <!-- 事件概览 -->
      <view class="card overview">
        <view class="status-row">
          <text v-if="event.status" class="status-badge" :class="'status-' + event.status">{{ statusLabel }}</text>
          <text v-if="event.version" class="version-text">v{{ event.version }}</text>
        </view>
        <text class="title">{{ event.title }}</text>
        <text v-if="event.summary" class="summary">{{ event.summary }}</text>
        <view v-if="event.why_important" class="block important">
          <text class="block-label">Why It Matters</text>
          <text class="block-text">{{ event.why_important }}</text>
        </view>
        <view class="meta-grid">
          <view class="meta-item"><text class="meta-label">Unique Sources</text><text class="meta-value">{{ event.source_count }}</text></view>
          <view class="meta-item"><text class="meta-label">Total Articles</text><text class="meta-value">{{ event.article_count }}</text></view>
          <view class="meta-item"><text class="meta-label">First Seen</text><text class="meta-value">{{ formatTime(event.first_seen_at) }}</text></view>
          <view class="meta-item"><text class="meta-label">Last Updated</text><text class="meta-value">{{ formatTime(event.last_updated_at) }}</text></view>
        </view>
      </view>

      <!-- 最新变化 -->
      <view v-if="event.latest_change" class="card">
        <text class="section-title">Latest Change</text>
        <view class="block change">
          <text class="block-text">{{ event.latest_change }}</text>
        </view>
      </view>

      <!-- 不确定信息（空时隐藏） -->
      <view v-if="event.uncertainty" class="card">
        <text class="section-title">Uncertainty</text>
        <view class="block uncertainty">
          <text class="block-text">{{ event.uncertainty }}</text>
        </view>
      </view>

      <!-- 后续观察（空时隐藏） -->
      <view v-if="event.watch_next" class="card">
        <text class="section-title">What to Watch</text>
        <view class="block watch">
          <text class="block-text">{{ event.watch_next }}</text>
        </view>
      </view>

      <!-- 事件演进（版本倒序，时间线形式呈现进展） -->
      <view v-if="event.versions && event.versions.length" class="card">
        <text class="section-title">Event Timeline</text>
        <view class="tl">
          <view v-for="(v, vi) in event.versions" :key="v.version" class="tl-item">
            <view class="tl-rail">
              <view class="tl-dot" :class="{ 'tl-dot-latest': vi === 0 }"></view>
              <view v-if="vi < event.versions.length - 1" class="tl-line"></view>
            </view>
            <view class="tl-body">
              <view class="version-head">
                <text class="version-num">v{{ v.version }}</text>
                <text v-if="vi === 0" class="tl-latest-tag">Latest</text>
                <text class="version-time">{{ formatTime(v.created_at) }}</text>
              </view>
              <text v-if="v.latest_change" class="version-change">{{ v.latest_change }}</text>
              <text v-if="v.event_summary" class="version-summary">{{ v.event_summary }}</text>
              <text class="version-meta">{{ v.source_count || 1 }} sources · {{ v.article_count || 1 }} articles</text>
            </view>
          </view>
        </view>
      </view>
      <!-- 无演进记录时给出说明，避免页面下方直接留白 -->
      <view v-else class="card">
        <text class="section-title">Event Timeline</text>
        <text class="tl-empty">No update recorded yet — this event has a single version.</text>
      </view>

      <!-- 关联报道 -->
      <view class="card">
        <text class="section-title">全部关联报道（{{ event.articles ? event.articles.length : 0 }}）</text>
        <view
          v-for="a in event.articles"
          :key="a.id"
          class="article-item"
          @click="openUrl(a.url)"
        >
          <view class="article-head">
            <text class="article-source">{{ a.source }}</text>
            <text v-if="a.ai_score" class="article-score">{{ a.ai_score }}分</text>
          </view>
          <text class="article-title">{{ a.title }}</text>
          <text class="article-time">{{ formatTime(a.published_at || a.created_at) }}</text>
        </view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref, computed } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { fetchEventDetail } from '../../utils/api.js'
import { formatTime } from '../../utils/formatters.js'

const event = ref(null)
const loading = ref(true)

const STATUS_LABELS = {
  new: '新事件',
  developing: '发展中',
  stable: '稳定',
  resolved: '已结束',
}
const statusLabel = computed(() => STATUS_LABELS[event.value?.status] || event.value?.status || '')

onLoad(async (options) => {
  const id = options?.id
  if (!id) {
    loading.value = false
    return
  }
  try {
    const resp = await fetchEventDetail(id)
    event.value = resp.data || resp
  } catch (e) {
    console.error('加载事件详情失败:', e)
  } finally {
    loading.value = false
  }
})

function openUrl(url) {
  if (!url) return
  // #ifdef H5
  window.open(url, '_blank')
  // #endif
  // #ifndef H5
  uni.setClipboardData({ data: url })
  // #endif
}
</script>

<style scoped>
.event-detail-page {
  min-height: 100vh;
  background: var(--color-bg);
  padding: 24rpx;
  box-sizing: border-box;
}
/* 桌面端：限制阅读宽度并居中，避免正文横向跨度过大、下方留大片空白 */
@media screen and (min-width: 768px) {
  .event-detail-page {
    max-width: 720px;
    margin: 0 auto;
    padding: 32px 24px;
  }
}
.state-box {
  padding: 120rpx 0;
  text-align: center;
}
.state-text {
  font-size: 28rpx;
  color: var(--color-text-muted);
}
.card {
  background: var(--color-bg-card);
  border-radius: var(--radius-r-2xl);
  padding: 28rpx;
  margin-bottom: 20rpx;
}
.status-row {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-bottom: 16rpx;
}
.status-badge {
  font-size: 22rpx;
  padding: 4rpx 16rpx;
  border-radius: var(--radius-r-md);
  font-weight: 600;
}
.status-new { background: var(--color-bg-success-soft); color: var(--color-success-text); }
.status-developing { background: var(--color-bg-warning-light); color: #ef6c00; }
.status-stable { background: #eceff1; color: #546e7a; }
.status-resolved { background: var(--color-bg-info-softer); color: var(--color-info-deep); }
.version-text {
  font-size: 22rpx;
  color: var(--color-text-muted);
}
.title {
  display: block;
  font-size: 36rpx;
  font-weight: 700;
  color: var(--color-text-primary);
  line-height: 1.45;
}
.summary {
  display: block;
  font-size: 28rpx;
  color: var(--color-text-tertiary);
  line-height: 1.7;
  margin-top: 16rpx;
}
.block {
  border-radius: var(--radius-r-md);
  padding: 16rpx 20rpx;
  margin-top: 16rpx;
}
.block.important { background: var(--color-bg-info-softer); border-left: 6rpx solid var(--color-info-active); }
.block.change { background: var(--color-bg-success-soft); border-left: 6rpx solid var(--color-success-hover); }
.block.uncertainty { background: #fff8e1; border-left: 6rpx solid #f9a825; }
.block.watch { background: var(--color-bg-time-evening); border-left: 6rpx solid #8e24aa; }
.block-label {
  font-size: 24rpx;
  font-weight: 600;
  color: var(--color-info-deep);
  display: block;
  margin-bottom: 6rpx;
}
.block-text {
  font-size: 27rpx;
  color: var(--color-text-secondary);
  line-height: 1.6;
}
.meta-grid {
  display: flex;
  flex-wrap: wrap;
  margin-top: 20rpx;
  gap: 16rpx 32rpx;
}
.meta-item {
  display: flex;
  flex-direction: column;
  gap: 4rpx;
}
.meta-label {
  font-size: 22rpx;
  color: var(--color-text-muted);
}
.meta-value {
  font-size: 26rpx;
  color: var(--color-text-primary);
  font-weight: 600;
}
.section-title {
  font-size: 30rpx;
  font-weight: 700;
  color: var(--color-text-primary);
  display: block;
  margin-bottom: 12rpx;
}
/* ── Event Timeline（版本演进，倒序：最新在上）── */
.tl { display: block; }
.tl-item { display: flex; align-items: stretch; }
.tl-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 28rpx;
  flex: none;
  margin-right: 18rpx;
}
.tl-dot {
  width: 16rpx;
  height: 16rpx;
  border-radius: 50%;
  background: var(--color-border-strong);
  flex: none;
  margin-top: 10rpx;
}
.tl-dot-latest {
  background: var(--color-brand);
  box-shadow: 0 0 0 6rpx var(--color-bg-brand-light);
}
.tl-line {
  flex: 1;
  width: 2rpx;
  background: var(--color-border-divider);
  margin: 6rpx 0;
}
.tl-body { flex: 1; min-width: 0; padding-bottom: 28rpx; }
.tl-latest-tag {
  font-size: 18rpx;
  font-weight: 700;
  color: var(--color-brand);
  background: var(--color-bg-brand-light);
  border-radius: var(--radius-p-sm);
  padding: 4rpx 10rpx;
  line-height: 1.2;
}
.tl-empty {
  font-size: 24rpx;
  color: var(--color-text-placeholder);
  line-height: 1.6;
}
.version-head {
  display: flex;
  align-items: center;
  gap: 16rpx;
}
.version-num {
  font-size: 26rpx;
  font-weight: 700;
  color: var(--color-brand);
}
.version-time {
  font-size: 22rpx;
  color: var(--color-text-muted);
}
.version-change {
  font-size: 26rpx;
  color: var(--color-success-text);
  line-height: 1.55;
  display: block;
  margin-top: 8rpx;
}
.version-summary {
  font-size: 25rpx;
  color: var(--color-text-tertiary);
  line-height: 1.55;
  display: block;
  margin-top: 6rpx;
}
.version-meta {
  font-size: 22rpx;
  color: var(--color-text-muted);
  display: block;
  margin-top: 6rpx;
}
.article-item {
  padding: 16rpx 0;
  border-bottom: 1rpx solid var(--color-bg-active-press);
}
.article-item:last-child {
  border-bottom: none;
}
.article-head {
  display: flex;
  align-items: center;
  gap: 12rpx;
}
.article-source {
  font-size: 22rpx;
  color: var(--color-brand);
  font-weight: 600;
}
.article-score {
  font-size: 20rpx;
  color: var(--color-text-muted);
}
.article-title {
  font-size: 27rpx;
  color: var(--color-text-primary);
  line-height: 1.5;
  display: block;
  margin-top: 6rpx;
}
.article-time {
  font-size: 22rpx;
  color: var(--color-text-muted);
  display: block;
  margin-top: 4rpx;
}

@media (min-width: 768px) {
  .event-detail-page {
    max-width: 860px;
    margin: 0 auto;
    padding: var(--space-6);
  }
  .card { border-radius: var(--radius-p-2xl); padding: var(--space-6); margin-bottom: 16px; }
  .title { font-size: 24px; }
  .summary { font-size: 15px; }
  .block-text { font-size: 15px; }
  .section-title { font-size: 17px; }
}
</style>
