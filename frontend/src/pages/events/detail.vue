<template>
  <view class="event-detail-page">
    <view v-if="loading" class="state-box"><text class="state-text">加载中...</text></view>
    <view v-else-if="!event" class="state-box"><text class="state-text">事件不存在或已删除</text></view>

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
          <text class="block-label">为什么重要</text>
          <text class="block-text">{{ event.why_important }}</text>
        </view>
        <view class="meta-grid">
          <view class="meta-item"><text class="meta-label">独立信源</text><text class="meta-value">{{ event.source_count }}</text></view>
          <view class="meta-item"><text class="meta-label">报道总数</text><text class="meta-value">{{ event.article_count }}</text></view>
          <view class="meta-item"><text class="meta-label">首次出现</text><text class="meta-value">{{ formatTime(event.first_seen_at) }}</text></view>
          <view class="meta-item"><text class="meta-label">最后更新</text><text class="meta-value">{{ formatTime(event.last_updated_at) }}</text></view>
        </view>
      </view>

      <!-- 最新变化 -->
      <view v-if="event.latest_change" class="card">
        <text class="section-title">最新变化</text>
        <view class="block change">
          <text class="block-text">{{ event.latest_change }}</text>
        </view>
      </view>

      <!-- 不确定信息（空时隐藏） -->
      <view v-if="event.uncertainty" class="card">
        <text class="section-title">不确定信息</text>
        <view class="block uncertainty">
          <text class="block-text">{{ event.uncertainty }}</text>
        </view>
      </view>

      <!-- 后续观察（空时隐藏） -->
      <view v-if="event.watch_next" class="card">
        <text class="section-title">后续观察</text>
        <view class="block watch">
          <text class="block-text">{{ event.watch_next }}</text>
        </view>
      </view>

      <!-- 事件演进（版本倒序） -->
      <view v-if="event.versions && event.versions.length" class="card">
        <text class="section-title">事件演进</text>
        <view v-for="v in event.versions" :key="v.version" class="version-item">
          <view class="version-head">
            <text class="version-num">版本 {{ v.version }}</text>
            <text class="version-time">{{ formatTime(v.created_at) }}</text>
          </view>
          <text v-if="v.latest_change" class="version-change">{{ v.latest_change }}</text>
          <text v-if="v.event_summary" class="version-summary">{{ v.event_summary }}</text>
          <text class="version-meta">{{ v.source_count || 1 }} 信源 · {{ v.article_count || 1 }} 篇报道</text>
        </view>
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
  background: #f0f2f5;
  padding: 24rpx;
  box-sizing: border-box;
}
.state-box {
  padding: 120rpx 0;
  text-align: center;
}
.state-text {
  font-size: 28rpx;
  color: #8c8c9a;
}
.card {
  background: #fff;
  border-radius: 20rpx;
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
  border-radius: 8rpx;
  font-weight: 600;
}
.status-new { background: #e8f5e9; color: #2e7d32; }
.status-developing { background: #fff3e0; color: #ef6c00; }
.status-stable { background: #eceff1; color: #546e7a; }
.status-resolved { background: #e3f2fd; color: #1565c0; }
.version-text {
  font-size: 22rpx;
  color: #8c8c9a;
}
.title {
  font-size: 36rpx;
  font-weight: 700;
  color: #1a1a2e;
  line-height: 1.4;
}
.summary {
  font-size: 28rpx;
  color: #5a5a6e;
  line-height: 1.65;
  margin-top: 16rpx;
}
.block {
  border-radius: 12rpx;
  padding: 16rpx 20rpx;
  margin-top: 16rpx;
}
.block.important { background: #e3f2fd; border-left: 6rpx solid #1e88e5; }
.block.change { background: #e8f5e9; border-left: 6rpx solid #43a047; }
.block.uncertainty { background: #fff8e1; border-left: 6rpx solid #f9a825; }
.block.watch { background: #f3e5f5; border-left: 6rpx solid #8e24aa; }
.block-label {
  font-size: 24rpx;
  font-weight: 600;
  color: #1565c0;
  display: block;
  margin-bottom: 6rpx;
}
.block-text {
  font-size: 27rpx;
  color: #3a3a4a;
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
  color: #8c8c9a;
}
.meta-value {
  font-size: 26rpx;
  color: #1a1a2e;
  font-weight: 600;
}
.section-title {
  font-size: 30rpx;
  font-weight: 700;
  color: #1a1a2e;
  display: block;
  margin-bottom: 12rpx;
}
.version-item {
  border-left: 4rpx solid #e0e0e6;
  padding: 8rpx 0 8rpx 20rpx;
  margin-bottom: 16rpx;
}
.version-head {
  display: flex;
  align-items: center;
  gap: 16rpx;
}
.version-num {
  font-size: 26rpx;
  font-weight: 700;
  color: #4285f4;
}
.version-time {
  font-size: 22rpx;
  color: #8c8c9a;
}
.version-change {
  font-size: 26rpx;
  color: #2e7d32;
  line-height: 1.55;
  display: block;
  margin-top: 8rpx;
}
.version-summary {
  font-size: 25rpx;
  color: #5a5a6e;
  line-height: 1.55;
  display: block;
  margin-top: 6rpx;
}
.version-meta {
  font-size: 22rpx;
  color: #8c8c9a;
  display: block;
  margin-top: 6rpx;
}
.article-item {
  padding: 16rpx 0;
  border-bottom: 1rpx solid #f0f0f4;
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
  color: #4285f4;
  font-weight: 600;
}
.article-score {
  font-size: 20rpx;
  color: #8c8c9a;
}
.article-title {
  font-size: 27rpx;
  color: #1a1a2e;
  line-height: 1.5;
  display: block;
  margin-top: 6rpx;
}
.article-time {
  font-size: 22rpx;
  color: #8c8c9a;
  display: block;
  margin-top: 4rpx;
}

@media (min-width: 768px) {
  .event-detail-page {
    max-width: 860px;
    margin: 0 auto;
    padding: 24px;
  }
  .card { border-radius: 12px; padding: 24px; margin-bottom: 16px; }
  .title { font-size: 24px; }
  .summary { font-size: 15px; }
  .block-text { font-size: 15px; }
  .section-title { font-size: 17px; }
}
</style>
