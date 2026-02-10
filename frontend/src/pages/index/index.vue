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
        <text class="loading-spinner">生成中...</text>
      </view>
    </view>

    <!-- 排序模式切换 -->
    <view class="sort-tabs">
      <view
        v-for="tab in sortTabs"
        :key="tab.value"
        class="sort-tab"
        :class="{ 'sort-tab-active': currentSort === tab.value }"
        @click="onSortChange(tab.value)"
      >
        <text class="sort-tab-icon">{{ tab.icon }}</text>
        <text class="sort-tab-text" :class="{ 'sort-tab-text-active': currentSort === tab.value }">{{ tab.label }}</text>
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
      <!-- 时间窗口筛选（仅 hot 模式） -->
      <view v-if="currentSort === 'hot'" class="filter-group">
        <text class="filter-label">时效</text>
        <view class="filter-chips">
          <view
            v-for="opt in ageOptions"
            :key="opt.value"
            class="chip"
            :class="{ 'chip-active': maxAgeHours === opt.value }"
            @click="onAgeChange(opt.value)"
          >
            <text class="chip-text" :class="{ 'chip-text-active': maxAgeHours === opt.value }">{{ opt.label }}</text>
          </view>
        </view>
      </view>
      <!-- 来源筛选 -->
      <view class="filter-group">
        <text class="filter-label">来源</text>
        <view class="filter-chips filter-chips-wrap">
          <view
            class="chip"
            :class="{ 'chip-active': !currentSource }"
            @click="onSourceChange('')"
          >
            <text class="chip-text" :class="{ 'chip-text-active': !currentSource }">全部</text>
          </view>
          <view
            v-for="src in cnSources"
            :key="src"
            class="chip"
            :class="{ 'chip-active': currentSource === src }"
            @click="onSourceChange(src)"
          >
            <text class="chip-text" :class="{ 'chip-text-active': currentSource === src }">{{ src }}</text>
          </view>
          <view class="chip-divider"></view>
          <view
            v-for="src in enSources"
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
      <text class="stats-text">{{ sortLabel }} · 评分≥{{ minScore }}</text>
    </view>

    <!-- 新闻列表 -->
    <view class="news-list">
      <view v-if="loading && newsList.length === 0" class="loading-container">
        <text class="loading-text">加载中...</text>
      </view>

      <view v-else-if="newsList.length === 0" class="empty-container">
        <text class="empty-text">暂无符合条件的新闻</text>
      </view>

      <view v-else class="card-wrapper">
        <view
          v-for="(item, idx) in newsList"
          :key="item.id"
          class="news-card"
          :class="{ 'news-card-last': idx === newsList.length - 1 }"
          @click="onOpenUrl(item.url)"
        >
          <!-- Score Badge -->
          <view class="score-badge" :class="scoreClass(item.ai_score)">
            <text class="score-num">{{ formatScore(item.ai_score) }}</text>
          </view>

          <view class="news-body">
            <text class="news-title">{{ item.title }}</text>
            <text class="news-summary">{{ item.ai_summary }}</text>

            <view class="news-meta">
              <text class="meta-source">{{ item.source }}</text>
              <text class="meta-dot">·</text>
              <text class="meta-time">{{ formatTime(item.published_at) }}</text>
              <!-- 热度指标 (hot 模式下显示) -->
              <template v-if="currentSort === 'hot' && item.ranking_score != null">
                <text class="meta-dot">·</text>
                <view class="heat-badge" :class="heatClass(item.ranking_score)">
                  <text class="heat-icon">🔥</text>
                  <text class="heat-value">{{ formatHeat(item.ranking_score) }}</text>
                </view>
              </template>
            </view>
          </view>
        </view>
      </view>

      <!-- 加载更多状态 -->
      <view v-if="newsList.length > 0" class="load-more">
        <text v-if="loadingMore" class="load-more-text">正在加载更多... ⏳</text>
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
      currentSort: 'hot',
      maxAgeHours: 72,
      promptLoading: false,
      promptCopied: false,
      scoreOptions: [6, 7, 8, 9],
      sourceOptions: [
        '财联社', '华尔街见闻', '第一财经', '新浪财经', '同花顺',
        '东方财富公告', '东方财富快讯',
        'MarketWatch', 'CNBC World', 'CNBC US Markets', 'Seeking Alpha', 'TechCrunch',
      ],
      cnSources: ['财联社', '华尔街见闻', '第一财经', '新浪财经', '同花顺', '东方财富公告', '东方财富快讯'],
      enSources: ['MarketWatch', 'CNBC World', 'CNBC US Markets', 'Seeking Alpha', 'TechCrunch'],
      sortTabs: [
        { value: 'hot', label: '热度', icon: '🔥' },
        { value: 'latest', label: '最新', icon: '🕐' },
        { value: 'score', label: '评分', icon: '⭐' },
      ],
      ageOptions: [
        { value: 24, label: '24h' },
        { value: 48, label: '48h' },
        { value: 72, label: '3天' },
        { value: 168, label: '7天' },
      ],
    }
  },

  computed: {
    sortLabel() {
      const tab = this.sortTabs.find(t => t.value === this.currentSort)
      return tab ? `${tab.icon}${tab.label}` : ''
    },
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
          sort: this.currentSort,
          max_age_hours: this.maxAgeHours,
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
          sort: this.currentSort,
          max_age_hours: this.maxAgeHours,
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

    /** 切换排序模式 */
    onSortChange(sort) {
      if (this.currentSort === sort) return
      this.currentSort = sort
      this.resetAndLoad()
    },

    /** 切换时间窗口 */
    onAgeChange(hours) {
      if (this.maxAgeHours === hours) return
      this.maxAgeHours = hours
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
      if (score >= 9) return 'score-high'
      if (score >= 8) return 'score-medium'
      if (score >= 7) return 'score-normal'
      return 'score-low'
    },

    formatScore(score) {
      if (score == null) return '-'
      const n = Number(score)
      return Number.isInteger(n) ? n.toFixed(1) : n.toString()
    },

    formatTime(iso) {
      if (!iso) return ''
      const now = new Date()
      const d = new Date(iso)
      const diffMs = now - d
      const diffMin = Math.floor(diffMs / 60000)
      if (diffMin < 1) return '刚刚'
      if (diffMin < 60) return `${diffMin}分钟前`
      const diffHour = Math.floor(diffMin / 60)
      if (diffHour < 24) return `${diffHour}小时前`
      const diffDay = Math.floor(diffHour / 24)
      if (diffDay < 7) return `${diffDay}天前`
      const mm = String(d.getMonth() + 1).padStart(2, '0')
      const dd = String(d.getDate()).padStart(2, '0')
      return `${mm}-${dd}`
    },

    /** 热度值格式化 */
    formatHeat(score) {
      if (score == null) return ''
      if (score >= 1) return score.toFixed(1)
      if (score >= 0.01) return score.toFixed(2)
      return score.toFixed(3)
    },

    /** 热度等级 class */
    heatClass(score) {
      if (score >= 1.0) return 'heat-high'
      if (score >= 0.3) return 'heat-medium'
      if (score >= 0.05) return 'heat-normal'
      return 'heat-low'
    },
  },
}
</script>

<style scoped>
.container {
  min-height: 100vh;
  background: #f0f2f5;
  padding: 0 24rpx;
}

/* ── Header ── */
.header {
  padding: 28rpx 0 20rpx;
}
.header-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.logo {
  font-size: 46rpx;
  font-weight: 800;
  color: #1a1a2e;
  letter-spacing: 1rpx;
  font-family: 'SF Pro Display', 'PingFang SC', -apple-system, sans-serif;
}
.subtitle {
  font-size: 24rpx;
  color: #8c8c9a;
  margin-top: 6rpx;
  letter-spacing: 1rpx;
}

/* ── Sort Tabs ── */
.sort-tabs {
  display: flex;
  gap: 16rpx;
  margin: 12rpx 0 8rpx;
}
.sort-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  padding: 18rpx 0;
  background: #ffffff;
  border-radius: 16rpx;
  border: 2rpx solid transparent;
  box-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.04);
  transition: all 0.2s;
}
.sort-tab-active {
  background: #e8f0fe;
  border-color: #4285f4;
  box-shadow: 0 2rpx 12rpx rgba(66, 133, 244, 0.15);
}
.sort-tab-icon {
  font-size: 28rpx;
}
.sort-tab-text {
  font-size: 26rpx;
  color: #6b6b7b;
  font-weight: 500;
}
.sort-tab-text-active {
  color: #4285f4;
  font-weight: 700;
}

/* ── Filter Bar ── */
.filter-bar {
  margin: 12rpx 0 8rpx;
  padding: 20rpx 24rpx;
  background: #ffffff;
  border-radius: 20rpx;
  box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.04);
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
  color: #8c8c9a;
  width: 72rpx;
  flex-shrink: 0;
  font-weight: 500;
}
.filter-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
}
.chip {
  padding: 8rpx 26rpx;
  border-radius: 28rpx;
  background: #f5f5f7;
  border: 1rpx solid #ececee;
  transition: all 0.2s;
}
.chip-active {
  background: #e8f0fe;
  border-color: #4285f4;
}
.chip-text {
  font-size: 22rpx;
  color: #6b6b7b;
}
.chip-text-active {
  color: #4285f4;
  font-weight: 600;
}
.chip-divider {
  width: 100%;
  height: 0;
}

/* ── Prompt Card ── */
.prompt-card {
  margin: 16rpx 0;
  padding: 28rpx 32rpx;
  background: linear-gradient(135deg, #667eea, #764ba2);
  border-radius: 20rpx;
  box-shadow: 0 8rpx 24rpx rgba(102, 126, 234, 0.25);
}
.prompt-header {
  display: flex;
  align-items: center;
  margin-bottom: 10rpx;
}
.prompt-icon {
  font-size: 34rpx;
  margin-right: 12rpx;
}
.prompt-title {
  font-size: 30rpx;
  font-weight: 600;
  color: #ffffff;
}
.prompt-desc {
  font-size: 24rpx;
  color: rgba(255, 255, 255, 0.8);
  line-height: 1.5;
}
.prompt-loading {
  margin-top: 10rpx;
}
.loading-spinner {
  font-size: 24rpx;
  color: rgba(255, 255, 255, 0.7);
}

/* ── Stats ── */
.stats-bar {
  display: flex;
  justify-content: space-between;
  padding: 16rpx 8rpx;
}
.stats-text {
  font-size: 22rpx;
  color: #8c8c9a;
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
  color: #8c8c9a;
  font-size: 28rpx;
}
.empty-text {
  color: #b0b0be;
  font-size: 28rpx;
}

/* ── Card Wrapper ── */
.card-wrapper {
  background: #ffffff;
  border-radius: 20rpx;
  box-shadow: 0 2rpx 16rpx rgba(0, 0, 0, 0.05);
  overflow: hidden;
}

/* ── News Card ── */
.news-card {
  display: flex;
  padding: 32rpx 28rpx;
  border-bottom: 1rpx solid #f0f0f2;
  position: relative;
  transition: background-color 0.15s;
}
.news-card:active {
  background-color: #fafafa;
}
.news-card-last {
  border-bottom: none;
}

/* ── Score Badge ── */
.score-badge {
  flex-shrink: 0;
  width: 80rpx;
  height: 52rpx;
  border-radius: 12rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 24rpx;
  margin-top: 6rpx;
}
.score-num {
  font-size: 28rpx;
  font-weight: 700;
  color: #ffffff;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}

/* 评分 ≥ 9: 绿色 */
.score-high {
  background: linear-gradient(135deg, #34c759, #28a745);
}
/* 评分 ≥ 8: 橙色 */
.score-medium {
  background: linear-gradient(135deg, #ff9500, #e8870e);
}
/* 评分 ≥ 7: 黄橙 */
.score-normal {
  background: linear-gradient(135deg, #f0b429, #d4981e);
}
/* 评分 < 7: 淡绿 */
.score-low {
  background: linear-gradient(135deg, #5ac778, #48b066);
}

/* ── News Body ── */
.news-body {
  flex: 1;
  min-width: 0;
}
.news-title {
  font-size: 30rpx;
  font-weight: 600;
  color: #1a1a2e;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-family: 'PingFang SC', 'SF Pro Text', -apple-system, sans-serif;
}
.news-summary {
  font-size: 25rpx;
  color: #5a5a6e;
  line-height: 1.55;
  margin-top: 10rpx;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ── Meta ── */
.news-meta {
  display: flex;
  align-items: center;
  margin-top: 14rpx;
  gap: 8rpx;
}
.meta-source {
  font-size: 22rpx;
  color: #8c8c9a;
  font-weight: 500;
}
.meta-dot {
  font-size: 22rpx;
  color: #c0c0cc;
}
.meta-time {
  font-size: 22rpx;
  color: #b0b0be;
}

/* ── Heat Badge ── */
.heat-badge {
  display: flex;
  align-items: center;
  gap: 4rpx;
  padding: 2rpx 12rpx;
  border-radius: 16rpx;
}
.heat-icon {
  font-size: 20rpx;
}
.heat-value {
  font-size: 20rpx;
  font-weight: 600;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.heat-high {
  background: rgba(255, 59, 48, 0.12);
}
.heat-high .heat-value {
  color: #ff3b30;
}
.heat-medium {
  background: rgba(255, 149, 0, 0.12);
}
.heat-medium .heat-value {
  color: #ff9500;
}
.heat-normal {
  background: rgba(52, 199, 89, 0.12);
}
.heat-normal .heat-value {
  color: #34c759;
}
.heat-low {
  background: rgba(142, 142, 147, 0.12);
}
.heat-low .heat-value {
  color: #8e8e93;
}

/* ── Load More ── */
.load-more {
  display: flex;
  justify-content: center;
  padding: 36rpx 0;
}
.load-more-text {
  font-size: 24rpx;
  color: #8c8c9a;
}

/* ── Safe Area ── */
.safe-bottom {
  height: 60rpx;
}
</style>
