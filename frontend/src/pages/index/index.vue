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

    <!-- 筛选器 -->
    <view class="filter-bar">
      <!-- 评分筛选 -->
      <view class="filter-group">
        <text class="filter-label">评分</text>
        <view class="filter-chips">
          <view
            v-for="s in scoreOptions"
            :key="s"
            class="chip"
            :class="{ 'chip-active': minScore === s }"
            @click="onScoreChange(s)"
          >
            <text class="chip-text" :class="{ 'chip-text-active': minScore === s }">≥{{ s }}</text>
          </view>
        </view>
      </view>
      <!-- 来源筛选 -->
      <view class="filter-group">
        <text class="filter-label">来源</text>
        <view class="filter-chips">
          <view
            class="chip"
            :class="{ 'chip-active': !currentSource }"
            @click="onSourceChange('')"
          >
            <text class="chip-text" :class="{ 'chip-text-active': !currentSource }">全部</text>
          </view>
          <view
            v-for="src in sourceOptions"
            :key="src"
            class="chip"
            :class="{ 'chip-active': currentSource === src }"
            @click="onSourceChange(src)"
          >
            <text class="chip-text" :class="{ 'chip-text-active': currentSource === src }">{{ src }}</text>
          </view>
        </view>
      </view>
    </view>

    <!-- 统计信息 -->
    <view class="stats-bar">
      <text class="stats-text">共 {{ total }} 条 · 已加载 {{ newsList.length }} 条</text>
      <text class="stats-text">评分 ≥ {{ minScore }}</text>
    </view>

    <!-- 新闻列表 -->
    <view class="news-list">
      <view v-if="loading && newsList.length === 0" class="loading-container">
        <text class="loading-text">加载中...</text>
      </view>

      <view v-else-if="newsList.length === 0" class="empty-container">
        <text class="empty-text">暂无符合条件的新闻</text>
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

      <!-- 加载更多状态 -->
      <view v-if="newsList.length > 0" class="load-more">
        <text v-if="loadingMore" class="load-more-text">加载更多...</text>
        <text v-else-if="noMore" class="load-more-text">— 没有更多了 —</text>
      </view>
    </view>

    <!-- 底部安全区 -->
    <view class="safe-bottom"></view>
  </view>
</template>

<script>
import { fetchNews, generatePrompt } from '../../utils/api.js'

const PAGE_SIZE = 20

export default {
  data() {
    return {
      newsList: [],
      total: 0,
      offset: 0,
      loading: true,
      loadingMore: false,
      noMore: false,
      minScore: 6,
      currentSource: '',
      promptLoading: false,
      promptCopied: false,
      scoreOptions: [6, 7, 8, 9],
      sourceOptions: ['财联社', '格隆汇', '36Kr', '东方财富'],
    }
  },

  onShow() {
    this.resetAndLoad()
  },

  onPullDownRefresh() {
    this.resetAndLoad().finally(() => {
      uni.stopPullDownRefresh()
    })
  },

  onReachBottom() {
    this.loadMore()
  },

  methods: {
    /** 重置列表并加载第一页 */
    async resetAndLoad() {
      this.newsList = []
      this.offset = 0
      this.noMore = false
      this.loading = true
      try {
        const data = await fetchNews({
          limit: PAGE_SIZE,
          offset: 0,
          min_score: this.minScore,
          source: this.currentSource || undefined,
        })
        this.newsList = data.items || []
        this.total = data.total || 0
        this.offset = this.newsList.length
        this.noMore = this.offset >= this.total
      } catch (e) {
        console.error('加载新闻失败:', e)
        uni.showToast({ title: '加载失败', icon: 'none' })
      } finally {
        this.loading = false
      }
    },

    /** 上拉加载更多 */
    async loadMore() {
      if (this.loadingMore || this.noMore || this.loading) return
      this.loadingMore = true
      try {
        const data = await fetchNews({
          limit: PAGE_SIZE,
          offset: this.offset,
          min_score: this.minScore,
          source: this.currentSource || undefined,
        })
        const items = data.items || []
        this.newsList = this.newsList.concat(items)
        this.total = data.total || 0
        this.offset += items.length
        this.noMore = items.length < PAGE_SIZE || this.offset >= this.total
      } catch (e) {
        console.error('加载更多失败:', e)
        uni.showToast({ title: '加载失败', icon: 'none' })
      } finally {
        this.loadingMore = false
      }
    },

    /** 切换评分筛选 */
    onScoreChange(score) {
      if (this.minScore === score) return
      this.minScore = score
      this.resetAndLoad()
    },

    /** 切换来源筛选 */
    onSourceChange(source) {
      if (this.currentSource === source) return
      this.currentSource = source
      this.resetAndLoad()
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

/* ── Filter Bar ── */
.filter-bar {
  margin: 16rpx 0 8rpx;
  padding: 20rpx 24rpx;
  background: rgba(30, 41, 59, 0.6);
  border: 1rpx solid rgba(51, 65, 85, 0.4);
  border-radius: 20rpx;
}
.filter-group {
  display: flex;
  align-items: center;
  margin-bottom: 16rpx;
}
.filter-group:last-child {
  margin-bottom: 0;
}
.filter-label {
  font-size: 24rpx;
  color: #64748b;
  width: 72rpx;
  flex-shrink: 0;
}
.filter-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
}
.chip {
  padding: 8rpx 24rpx;
  border-radius: 28rpx;
  background: rgba(51, 65, 85, 0.4);
  border: 1rpx solid rgba(71, 85, 105, 0.4);
  transition: all 0.2s;
}
.chip-active {
  background: rgba(59, 130, 246, 0.2);
  border-color: rgba(59, 130, 246, 0.5);
}
.chip-text {
  font-size: 22rpx;
  color: #94a3b8;
}
.chip-text-active {
  color: #60a5fa;
  font-weight: 600;
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

/* ── Load More ── */
.load-more {
  display: flex;
  justify-content: center;
  padding: 32rpx 0;
}
.load-more-text {
  font-size: 24rpx;
  color: #475569;
}

/* ── Safe Area ── */
.safe-bottom {
  height: 60rpx;
}
</style>
