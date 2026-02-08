<template>
  <view class="container">
    <!-- Header -->
    <view class="header">
      <view class="header-top">
        <text class="logo">AlphaReader</text>
      </view>
      <text class="subtitle">高频金融情报 · 信噪比优先</text>
    </view>

    <!-- 大模型提示词区域 -->
    <view class="prompt-card" @click="onCopyPrompt">
      <view class="prompt-header">
        <text class="prompt-icon">✨</text>
        <text class="prompt-title">复制为大模型对话提示词</text>
      </view>
      <text class="prompt-desc">
        {{ promptCopied ? '已复制到剪贴板!' : '一键生成今日 Top 10 结构化分析提示词' }}
      </text>
      <view v-if="promptLoading" class="prompt-loading">
        <text class="loading-text">生成中...</text>
      </view>
    </view>

    <!-- 统计信息 -->
    <view class="stats-bar">
      <text class="stats-text">共 {{ newsList.length }} 条高价值新闻</text>
      <text class="stats-text">评分 ≥ {{ minScore }}</text>
    </view>

    <!-- 新闻列表 -->
    <view class="news-list">
      <view v-if="loading" class="loading-container">
        <text class="loading-text">加载中...</text>
      </view>

      <view v-else-if="newsList.length === 0" class="empty-container">
        <text class="empty-text">暂无新闻，点击「刷新数据」抓取</text>
      </view>

      <view
        v-for="item in newsList"
        :key="item.id"
        class="news-card"
        @click="onOpenUrl(item.url)"
      >
        <!-- Score Badge -->
        <view class="score-badge" :class="scoreClass(item.ai_score)">
          <text class="score-num">{{ item.ai_score }}</text>
        </view>

        <view class="news-body">
          <text class="news-title">{{ item.title }}</text>
          <text class="news-summary">{{ item.ai_summary }}</text>

          <view class="news-meta">
            <text class="meta-source">{{ item.source }}</text>
            <view class="tags-row">
              <text v-for="tag in (item.tags || []).slice(0, 3)" :key="tag" class="tag">{{ tag }}</text>
            </view>
            <text class="meta-time">{{ formatTime(item.published_at) }}</text>
          </view>
        </view>
      </view>
    </view>

    <!-- 底部安全区 -->
    <view class="safe-bottom"></view>
  </view>
</template>

<script>
import { fetchNews, generatePrompt } from '../../utils/api.js'

export default {
  data() {
    return {
      newsList: [],
      loading: true,
      minScore: 6,
      promptLoading: false,
      promptCopied: false,
    }
  },

  onShow() {
    this.loadNews()
  },

  methods: {
    async loadNews() {
      this.loading = true
      try {
        const data = await fetchNews({ limit: 50, min_score: this.minScore })
        this.newsList = data
      } catch (e) {
        console.error('加载新闻失败:', e)
        uni.showToast({ title: '加载失败', icon: 'none' })
      } finally {
        this.loading = false
      }
    },

    async onCopyPrompt() {
      if (this.promptLoading) return
      this.promptLoading = true
      this.promptCopied = false

      try {
        const res = await generatePrompt({ top_n: 10 })
        if (res.prompt) {
          uni.setClipboardData({
            data: res.prompt,
            success: () => {
              this.promptCopied = true
              setTimeout(() => { this.promptCopied = false }, 3000)
            },
          })
        } else {
          uni.showToast({ title: '暂无数据生成 Prompt', icon: 'none' })
        }
      } catch (e) {
        console.error('生成Prompt失败:', e)
        uni.showToast({ title: '生成失败', icon: 'none' })
      } finally {
        this.promptLoading = false
      }
    },

    onOpenUrl(url) {
      if (!url) return
      // #ifdef H5
      window.open(url, '_blank')
      // #endif
      // #ifndef H5
      uni.setClipboardData({ data: url })
      // #endif
    },

    scoreClass(score) {
      if (score >= 9) return 'score-hot'
      if (score >= 7) return 'score-warm'
      return 'score-cool'
    },

    formatTime(iso) {
      if (!iso) return ''
      const d = new Date(iso)
      const mm = String(d.getMonth() + 1).padStart(2, '0')
      const dd = String(d.getDate()).padStart(2, '0')
      const hh = String(d.getHours()).padStart(2, '0')
      const mi = String(d.getMinutes()).padStart(2, '0')
      return `${mm}-${dd} ${hh}:${mi}`
    },
  },
}
</script>

<style scoped>
.container {
  min-height: 100vh;
  background: #0f172a;
  padding: 0 24rpx;
}

/* ── Header ── */
.header {
  padding: 24rpx 0 16rpx;
}
.header-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.logo {
  font-size: 44rpx;
  font-weight: 700;
  color: #f8fafc;
  letter-spacing: 2rpx;
}
.subtitle {
  font-size: 24rpx;
  color: #64748b;
  margin-top: 4rpx;
}

/* ── Pill Button ── */
.pill {
  display: flex;
  align-items: center;
  background: rgba(59, 130, 246, 0.15);
  border: 1rpx solid rgba(59, 130, 246, 0.3);
  border-radius: 40rpx;
  padding: 12rpx 28rpx;
}
.pill-active {
  background: rgba(234, 179, 8, 0.15);
  border-color: rgba(234, 179, 8, 0.3);
}
.pill-dot {
  width: 14rpx;
  height: 14rpx;
  border-radius: 50%;
  background: #3b82f6;
  margin-right: 12rpx;
}
.pill-active .pill-dot {
  background: #eab308;
}
.dot-pulse {
  animation: pulse 1.5s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}
.pill-text {
  font-size: 24rpx;
  color: #94a3b8;
}

/* ── Prompt Card ── */
.prompt-card {
  margin: 20rpx 0;
  padding: 32rpx;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.15), rgba(168, 85, 247, 0.15));
  border: 1rpx solid rgba(139, 92, 246, 0.3);
  border-radius: 24rpx;
}
.prompt-header {
  display: flex;
  align-items: center;
  margin-bottom: 12rpx;
}
.prompt-icon {
  font-size: 36rpx;
  margin-right: 12rpx;
}
.prompt-title {
  font-size: 32rpx;
  font-weight: 600;
  color: #e2e8f0;
}
.prompt-desc {
  font-size: 26rpx;
  color: #94a3b8;
  line-height: 1.5;
}
.prompt-loading {
  margin-top: 12rpx;
}

/* ── Stats ── */
.stats-bar {
  display: flex;
  justify-content: space-between;
  padding: 16rpx 8rpx;
}
.stats-text {
  font-size: 22rpx;
  color: #475569;
}

/* ── News List ── */
.news-list {
  padding-bottom: 20rpx;
}
.loading-container,
.empty-container {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 120rpx 0;
}
.loading-text {
  color: #64748b;
  font-size: 28rpx;
}
.empty-text {
  color: #475569;
  font-size: 28rpx;
}

/* ── News Card ── */
.news-card {
  display: flex;
  margin-bottom: 20rpx;
  padding: 28rpx;
  background: rgba(30, 41, 59, 0.7);
  border: 1rpx solid rgba(51, 65, 85, 0.5);
  border-radius: 20rpx;
}

.score-badge {
  flex-shrink: 0;
  width: 72rpx;
  height: 72rpx;
  border-radius: 16rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 24rpx;
  margin-top: 4rpx;
}
.score-num {
  font-size: 32rpx;
  font-weight: 700;
  color: #fff;
}
.score-hot {
  background: linear-gradient(135deg, #ef4444, #dc2626);
}
.score-warm {
  background: linear-gradient(135deg, #f59e0b, #d97706);
}
.score-cool {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
}

.news-body {
  flex: 1;
  min-width: 0;
}
.news-title {
  font-size: 30rpx;
  font-weight: 600;
  color: #f1f5f9;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.news-summary {
  font-size: 24rpx;
  color: #94a3b8;
  line-height: 1.5;
  margin-top: 8rpx;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.news-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 12rpx;
  gap: 12rpx;
}
.meta-source {
  font-size: 22rpx;
  color: #3b82f6;
  font-weight: 500;
}
.tags-row {
  display: flex;
  gap: 8rpx;
}
.tag {
  font-size: 20rpx;
  color: #a78bfa;
  background: rgba(139, 92, 246, 0.15);
  padding: 4rpx 16rpx;
  border-radius: 20rpx;
}
.meta-time {
  font-size: 20rpx;
  color: #475569;
  margin-left: auto;
}

/* ── Safe Area ── */
.safe-bottom {
  height: 60rpx;
}
</style>
