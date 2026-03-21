<template>
  <view class="container">
    <!-- Header -->
    <view class="header">
      <view class="header-top">
        <text class="logo">AlphaReader</text>
        <view class="inspire-btn" :class="{ 'inspire-btn-copied': promptCopied }" @click="onInspireCopy">
          <image v-if="!promptCopied" class="inspire-icon" src="/static/icons/circle-three.svg" mode="aspectFit" />
          <image v-else class="inspire-icon" src="/static/icons/done-all.svg" mode="aspectFit" />
        </view>
      </view>
      <text class="subtitle">高频金融情报 · 信噪比优先</text>
    </view>

    <!-- 分类 Tab：全部 / 财经 / 科技 -->
    <view class="category-tabs">
      <view
        v-for="cat in categoryTabs"
        :key="cat.value"
        class="category-tab"
        :class="{ 'category-tab-active': currentCategory === cat.value }"
        @click="onSwitchCategory(cat.value)"
      >
        <text class="category-tab-text" :class="{ 'category-tab-text-active': currentCategory === cat.value }">{{ cat.label }}</text>
      </view>
    </view>

    <!-- 搜索栏 + 搜索面板 + 搜索结果 -->
    <NewsSearchBar
      :search-mode="searchMode"
      :search-focused="searchFocused"
      :search-query="searchQuery"
      :search-submitted="searchSubmitted"
      :search-list="searchList"
      :search-total="searchTotal"
      :search-loading="searchLoading"
      :search-loading-more="searchLoadingMore"
      :search-no-more="searchNoMore"
      :search-history="searchHistory"
      :hot-topics="hotTopics"
      @input="onSearchInput"
      @focus="onSearchFocus"
      @confirm="onSearchConfirm"
      @clear="onClearSearch"
      @exit="onExitSearch"
      @clear-history="clearHistory"
      @quick-search="onQuickSearch"
      @open="onOpenUrl"
      @tag-search="onTagSearch"
    />

    <!-- 以下为 News Feed 内容 (非搜索模式时显示) -->
    <template v-if="!searchMode">

    <!-- 筛选面板 -->
    <NewsFilterPopover
      :filter-open="filterOpen"
      :has-active-filter="hasActiveFilter"
      :filter-tags="filterTags"
      :total="total"
      :tmp-sort="tmpSort"
      :tmp-age="tmpAge"
      :tmp-source="tmpSource"
      :tmp-score="tmpScore"
      :sort-tabs="sortTabs"
      :age-options="ageOptions"
      :cn-sources="cnSources"
      :en-sources="enSources"
      :tech-sources="techSources"
      :score-options="scoreOptions"
      @toggle="openFilter"
      @confirm="onConfirmFilter"
      @cancel="cancelFilter"
      @reset="resetTmp"
      @update:tmp-sort="(v) => tmpSort = v"
      @update:tmp-age="(v) => tmpAge = v"
      @update:tmp-source="(v) => tmpSource = v"
      @update:tmp-score="(v) => tmpScore = v"
    />

    <!-- 新闻列表（聚合模式） -->
    <view class="news-list">
      <view v-if="loading && newsList.length === 0" class="loading-container">
        <text class="loading-text">加载中...</text>
      </view>

      <view v-else-if="groupedNews.length === 0" class="empty-container">
        <text class="empty-text">暂无符合条件的新闻</text>
      </view>

      <view v-else class="card-wrapper">
        <NewsCardGroup
          v-for="(group, idx) in groupedNews"
          :key="group.id"
          :group="group"
          :is-last="idx === groupedNews.length - 1"
          :expanded="!!expandedGroups[group.id]"
          :show-gravity="currentSort === 'hot'"
          @open="onOpenUrl"
          @tag-search="onTagSearch"
          @toggle-related="toggleRelated"
        />
      </view>

      <!-- 加载更多状态 -->
      <view v-if="groupedNews.length > 0" class="load-more">
        <text v-if="loadingMore" class="load-more-text">正在加载更多... ⏳</text>
        <text v-else-if="noMore" class="load-more-text">— 没有更多了 —</text>
      </view>
    </view>

    </template>
    <SiteFooter mobile-padding="40rpx 0 60rpx" desktop-padding="32px 0 48px" />
  </view>
</template>

<script setup>
import { ref, nextTick, onMounted, onUnmounted, getCurrentInstance } from 'vue'
import { initTracker, trackImpression, trackClick, destroyTracker } from '../../utils/tracker.js'
import SiteFooter from '@/components/common/SiteFooter.vue'
import NewsSearchBar from '@/components/news/NewsSearchBar.vue'
import NewsFilterPopover from '@/components/news/NewsFilterPopover.vue'
import NewsCardGroup from '@/components/news/NewsCardGroup.vue'
import { useNewsFeed } from '@/composables/useNewsFeed.js'
import { useNewsSearch } from '@/composables/useNewsSearch.js'
import { useNewsFilter } from '@/composables/useNewsFilter.js'

// ── Composables ──
const {
  newsList,
  total,
  loading,
  loadingMore,
  noMore,
  expandedGroups,
  groupedNews,
  toggleRelated,
  resetAndLoad: feedResetAndLoad,
  loadMore: feedLoadMore,
} = useNewsFeed()

const {
  searchMode,
  searchFocused,
  searchQuery,
  searchSubmitted,
  searchList,
  searchTotal,
  searchLoading,
  searchLoadingMore,
  searchNoMore,
  searchHistory,
  hotTopics,
  onSearchFocus,
  onSearchInput,
  onSearchConfirm,
  onQuickSearch,
  onTagSearch,
  onClearSearch,
  onExitSearch,
  searchLoadMore,
  clearHistory,
} = useNewsSearch()

const {
  scoreOptions,
  categoryTabs,
  cnSources,
  enSources,
  techSources,
  sortTabs,
  ageOptions,
  currentSort,
  currentCategory,
  filterOpen,
  tmpSort,
  tmpAge,
  tmpSource,
  tmpScore,
  hasActiveFilter,
  filterTags,
  buildFilterParams,
  openFilter,
  confirmFilter,
  cancelFilter,
  resetTmp,
  switchCategory,
} = useNewsFilter()

// ── Inspire Button ──
const promptCopied = ref(false)

// ── 曝光追踪 ──
let _impressionObserver = null
let _impressedSet = new Set()

/** 带筛选参数的加载 */
function doResetAndLoad() {
  return feedResetAndLoad(buildFilterParams())
}

function doLoadMore() {
  return feedLoadMore(buildFilterParams())
}

/** 切换分类 Tab */
function onSwitchCategory(cat) {
  if (switchCategory(cat)) {
    doResetAndLoad()
  }
}

/** 确认筛选 */
function onConfirmFilter() {
  confirmFilter()
  doResetAndLoad()
}

/** 打开链接 */
function onOpenUrl(url, newsId) {
  if (!url) return
  if (newsId) trackClick(newsId)
  // #ifdef H5
  window.open(url, '_blank')
  // #endif
  // #ifndef H5
  uni.setClipboardData({ data: url })
  // #endif
}

/** 灵感按钮：用前端已有 newsList 同步组装 Prompt 并复制 */
function onInspireCopy() {
  if (promptCopied.value) return
  const list = newsList.value
  if (!list || list.length === 0) {
    uni.showToast({ title: '暂无新闻数据', icon: 'none' })
    return
  }
  const top = list.slice(0, 66)
  const dateStr = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
  const newsBlock = top.map((item, i) => {
    const tags = (item.tags && item.tags.length) ? `【${item.tags.join('、')}】` : ''
    const score = item.ai_score != null ? `[评分: ${item.ai_score}]` : ''
    const summary = item.ai_summary || ''
    return `${i + 1}. ${tags} ${item.title} ${score}\n   ${summary}`
  }).join('\n\n')

  const prompt = `# Role
你是一位拥有 20 年经验、擅长"基本面+趋势分析"的对冲基金首席策略师。你具备极强的信息穿透力，能从碎片化的新闻中识别出影响市场估值和流动性的核心逻辑，并识别出隐藏在利好背后的潜在风险。

# Context
以下是 ${dateStr} 高价值情报列表（共 ${top.length} 条），已按热度排序并经 AI 评分筛选。

${newsBlock}

# Investment Logic Framework
在分析时，请遵循以下分析框架：
1. 互联性分析：识别不同新闻之间是否存在因果、协同或对冲关系。
2. 预期差分析：判断该信息是已被市场充分定价，还是存在超预期空间。
3. 风险收益比：每一个机会点必须伴随对应的反面逻辑。

# Task
请基于上述情报生成一份深度分析报告，要求逻辑严密，专业性极强，可读性也很高，减少 AI 语气和措辞。

## 1. 市场图谱与情绪博弈
- **核心逻辑聚类**：用一句话概括今日市场的驱动力。
- **情绪定性**：在 [极度悲观/悲观/中性/乐观/极度乐观] 中选一，并给出理由。

## 2. 核心投资信号挖掘 (High-Conviction Signals)
选出 2-3 个最有价值的信号：
- **【信号名称】**
- **关联证据**：极简概括关联的新闻
- **影响深度**：是"短期刺激"还是"中长期逻辑改变"
- **博弈核心**：当前市场在该信号上的分歧点

## 3. 风险雷达 (Blind Spots)
- **显性风险**：情报中直接提到的负面因素
- **隐性风险**：如果利好逻辑证伪，最坏情况是什么
- **合规/监管预警**：政策或外部环境的潜在冲击

## 4. 短线情绪展望
- 下一个交易日/本周的情绪方向判断
- 需要重点观察的关键数据或事件节点`

  // iOS Safari 兼容
  // #ifdef H5
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(prompt).then(() => {
      promptCopied.value = true
      uni.showToast({ title: 'Prompt 已复制', icon: 'success' })
      setTimeout(() => { promptCopied.value = false }, 3000)
    }).catch(() => {
      _fallbackCopy(prompt)
    })
  } else {
    _fallbackCopy(prompt)
  }
  // #endif
  // #ifndef H5
  uni.setClipboardData({
    data: prompt,
    success: () => {
      promptCopied.value = true
      uni.showToast({ title: 'Prompt 已复制', icon: 'success' })
      setTimeout(() => { promptCopied.value = false }, 3000)
    },
  })
  // #endif
}

/** Clipboard fallback */
function _fallbackCopy(text) {
  // #ifdef H5
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.cssText = 'position:fixed;left:-9999px;top:-9999px;opacity:0'
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    if (ok) {
      promptCopied.value = true
      uni.showToast({ title: 'Prompt 已复制', icon: 'success' })
      setTimeout(() => { promptCopied.value = false }, 3000)
    } else {
      uni.showToast({ title: '复制失败，请手动复制', icon: 'none' })
    }
  } catch {
    uni.showToast({ title: '复制失败', icon: 'none' })
  }
  // #endif
}

// ── 曝光追踪 ──
function _setupImpressionObserver() {
  if (_impressionObserver) return
  _impressedSet = new Set()
  _impressionObserver = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const id = entry.target.dataset.newsId
        if (id && !_impressedSet.has(id)) {
          _impressedSet.add(id)
          trackImpression(id)
        }
      }
    })
  }, { threshold: 0.5 })
  nextTick(() => _observeCards())
}

function _observeCards() {
  if (!_impressionObserver) return
  const cards = document.querySelectorAll('.news-card[data-news-id]')
  cards.forEach(el => {
    if (!el._observed) {
      _impressionObserver.observe(el)
      el._observed = true
    }
  })
}

function _destroyImpressionObserver() {
  if (_impressionObserver) {
    _impressionObserver.disconnect()
    _impressionObserver = null
  }
}

// ── uni-app 页面生命周期（通过 defineOptions 在 script setup 中暂不支持，使用底层实例挂载） ──
const instance = getCurrentInstance()
if (instance) {
  // onShow
  instance.proxy.$options.onShow = [function () {
    initTracker()
    doResetAndLoad().then(() => {
      // #ifdef H5
      nextTick(() => _observeCards())
      // #endif
    })
    // #ifdef H5
    _setupImpressionObserver()
    // #endif
  }]
  // onHide
  instance.proxy.$options.onHide = [function () {
    destroyTracker()
    // #ifdef H5
    _destroyImpressionObserver()
    // #endif
  }]
  // onPullDownRefresh
  instance.proxy.$options.onPullDownRefresh = [function () {
    doResetAndLoad().finally(() => {
      uni.stopPullDownRefresh()
    })
  }]
  // onReachBottom
  instance.proxy.$options.onReachBottom = [function () {
    if (searchMode.value && searchSubmitted.value) {
      searchLoadMore()
    } else {
      doLoadMore()
    }
  }]
}
</script>

<style scoped>
.container {
  min-height: 100vh;
  background: var(--color-bg);
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
  color: var(--color-text-primary);
  letter-spacing: 1rpx;
  font-family: var(--font-display);
  user-select: none;
  -webkit-user-select: none;
}

/* ── Inspire Button ── */
.inspire-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 64rpx;
  height: 64rpx;
  border-radius: 50%;
  background: rgba(26, 26, 46, 0.06);
  border: 1rpx solid rgba(26, 26, 46, 0.1);
  cursor: pointer;
  transition: all 0.2s ease;
  -webkit-tap-highlight-color: transparent;
  user-select: none;
  -webkit-user-select: none;
}
.inspire-btn:active {
  transform: scale(0.9);
  background: rgba(26, 26, 46, 0.12);
}
.inspire-btn-copied {
  background: rgba(52, 199, 89, 0.1);
  border-color: rgba(52, 199, 89, 0.25);
}
.inspire-icon {
  width: 36rpx;
  height: 36rpx;
}
.subtitle {
  font-size: 24rpx;
  color: var(--color-text-muted);
  margin-top: 6rpx;
  letter-spacing: 1rpx;
}

/* ── Category Tabs ── */
.category-tabs {
  display: flex;
  align-items: center;
  gap: 0;
  margin: 20rpx 0 4rpx;
  background: var(--color-border);
  border-radius: 20rpx;
  padding: 4rpx;
}
.category-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16rpx 0;
  border-radius: 16rpx;
  cursor: pointer;
  transition: background-color 0.2s, box-shadow 0.2s;
  -webkit-tap-highlight-color: transparent;
}
.category-tab-active {
  background: var(--color-bg-card);
  box-shadow: 0 2rpx 8rpx rgba(0, 0, 0, 0.08);
}
.category-tab-text {
  font-size: 26rpx;
  color: var(--color-text-muted);
  font-weight: 500;
  letter-spacing: 1rpx;
}
.category-tab-text-active {
  color: var(--color-text-primary);
  font-weight: 700;
}

/* ── Search Bar ── */
:deep(.search-bar) {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin: 16rpx 0 8rpx;
}
:deep(.search-input-wrap) {
  flex: 1;
  display: flex;
  align-items: center;
  background: var(--color-bg-card);
  border-radius: 36rpx;
  padding: 16rpx 24rpx;
  border: 2rpx solid var(--color-border);
  transition: border-color 0.2s, box-shadow 0.2s;
}
:deep(.search-bar-focus .search-input-wrap) {
  border-color: var(--color-brand);
  box-shadow: 0 2rpx 12rpx rgba(66, 133, 244, 0.15);
}
:deep(.search-icon) {
  font-size: 28rpx;
  margin-right: 12rpx;
  flex-shrink: 0;
}
:deep(.search-input) {
  flex: 1;
  font-size: 28rpx;
  color: var(--color-text-primary);
  background: transparent;
  border: none;
  outline: none;
  line-height: 1.4;
}
:deep(.search-clear) {
  padding: 4rpx 8rpx;
  margin-left: 8rpx;
  flex-shrink: 0;
  cursor: pointer;
}
:deep(.search-clear-icon) {
  font-size: 32rpx;
  color: var(--color-text-placeholder);
  font-weight: 500;
}
:deep(.search-cancel) {
  flex-shrink: 0;
  padding: 8rpx 4rpx;
  cursor: pointer;
}
:deep(.search-cancel-text) {
  font-size: 28rpx;
  color: var(--color-brand);
  font-weight: 500;
}

/* ── Search Panel (History + Hot Topics) ── */
:deep(.search-panel) {
  padding: 16rpx 0;
}
:deep(.sp-section) {
  margin-bottom: 28rpx;
}
:deep(.sp-section-header) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16rpx;
}
:deep(.sp-section-title) {
  font-size: 26rpx;
  color: var(--color-text-hint);
  font-weight: 600;
}
:deep(.sp-clear-btn) {
  padding: 4rpx 16rpx;
  cursor: pointer;
}
:deep(.sp-clear-text) {
  font-size: 24rpx;
  color: var(--color-text-placeholder);
}
:deep(.sp-tags) {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
}
:deep(.sp-tag) {
  padding: 12rpx 24rpx;
  background: var(--color-bg-card);
  border-radius: 24rpx;
  border: 1rpx solid var(--color-border);
  cursor: pointer;
  transition: background-color 0.15s;
}
:deep(.sp-tag:active) {
  background: var(--color-bg);
}
:deep(.sp-tag-hot) {
  background: rgba(66, 133, 244, 0.06);
  border-color: rgba(66, 133, 244, 0.2);
}
:deep(.sp-tag-text) {
  font-size: 24rpx;
  color: var(--color-text-secondary);
}
:deep(.sp-tag-hot .sp-tag-text) {
  color: var(--color-brand);
}

/* ── Search Results ── */
:deep(.search-results) {
  padding-bottom: 20rpx;
}
:deep(.search-results-header) {
  padding: 8rpx 0 16rpx;
}
:deep(.search-results-count) {
  font-size: 24rpx;
  color: var(--color-text-muted);
}

/* ── Search Highlight ── */
:deep(.search-highlight mark) {
  background: rgba(66, 133, 244, 0.18);
  color: var(--color-brand);
  font-weight: 600;
  padding: 0 2rpx;
  border-radius: 4rpx;
}

/* ── Relevance Badge ── */
:deep(.relevance-badge) {
  display: flex;
  align-items: center;
  gap: 4rpx;
  padding: 2rpx 12rpx;
  background: rgba(66, 133, 244, 0.08);
  border-radius: 16rpx;
}
:deep(.relevance-label) {
  font-size: 20rpx;
  color: var(--color-text-muted);
}
:deep(.relevance-value) {
  font-size: 20rpx;
  color: var(--color-brand);
  font-weight: 600;
  font-family: var(--font-numeric);
}

/* ── Filter Anchor (定位容器) ── */
:deep(.filter-anchor) {
  position: relative;
  z-index: 100;
}

/* ── Filter Trigger Bar ── */
:deep(.filter-trigger-bar) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 12rpx 0 8rpx;
}
:deep(.filter-trigger-left) {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
:deep(.filter-trigger-btn) {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 14rpx 24rpx;
  background: var(--color-bg-card);
  border-radius: 32rpx;
  border: 2rpx solid var(--color-border-divider);
  flex-shrink: 0;
  cursor: pointer;
  transition: border-color 0.2s, background-color 0.2s, box-shadow 0.2s;
}
:deep(.filter-trigger-active) {
  border-color: var(--color-brand);
  background: var(--color-bg-brand-light);
}
:deep(.filter-trigger-icon) {
  font-size: 26rpx;
  color: var(--color-text-hint);
}
:deep(.filter-trigger-text) {
  font-size: 26rpx;
  color: var(--color-text-secondary);
  font-weight: 500;
}
:deep(.filter-arrow) {
  font-size: 28rpx;
  color: var(--color-text-muted);
  transform: rotate(90deg);
  transition: transform 0.25s;
}
:deep(.filter-arrow-up) {
  transform: rotate(-90deg);
}
:deep(.filter-tags) {
  display: flex;
  align-items: center;
  gap: 8rpx;
  overflow: hidden;
}
:deep(.filter-tag) {
  padding: 6rpx 16rpx;
  background: var(--color-bg-info-soft);
  border-radius: 20rpx;
  flex-shrink: 0;
}
:deep(.filter-tag-text) {
  font-size: 22rpx;
  color: var(--color-brand);
  font-weight: 500;
  white-space: nowrap;
}
:deep(.stats-text-inline) {
  font-size: 22rpx;
  color: var(--color-text-muted);
  flex-shrink: 0;
  margin-left: 12rpx;
}

/* ── Filter Popover (浮窗) ── */
:deep(.filter-popover) {
  position: absolute;
  left: 0;
  right: 0;
  top: 100%;
  z-index: 101;
  padding-top: 8rpx;
}
:deep(.filter-popover-body) {
  background: var(--color-bg-card);
  border-radius: 20rpx;
  padding: 28rpx 28rpx 0;
  box-shadow: 0 8rpx 40rpx rgba(0, 0, 0, 0.12), 0 2rpx 8rpx rgba(0, 0, 0, 0.06);
  border: 1rpx solid rgba(0, 0, 0, 0.05);
}

/* ── Filter Backdrop (轻量遮罩) ── */
:deep(.filter-backdrop) {
  position: fixed;
  left: 0;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 99;
  background: rgba(0, 0, 0, 0.08);
}
:deep(.filter-row) {
  display: flex;
  align-items: flex-start;
  padding-bottom: 28rpx;
  border-bottom: 1rpx solid var(--color-border-subtle);
  margin-bottom: 24rpx;
}
:deep(.filter-row-last) {
  border-bottom: none;
  margin-bottom: 0;
  padding-bottom: 16rpx;
}
:deep(.filter-row-label) {
  font-size: 26rpx;
  color: var(--color-text-muted);
  width: 80rpx;
  flex-shrink: 0;
  font-weight: 500;
  padding-top: 10rpx;
}
:deep(.filter-row-chips) {
  display: flex;
  flex-wrap: nowrap;
  gap: 16rpx;
  flex: 1;
}
:deep(.filter-row-chips-wrap) {
  flex-wrap: wrap;
}

/* ── Filter Chip (fc) ── */
:deep(.fc) {
  flex: 1;
  min-width: 0;
  padding: 16rpx 0;
  border-radius: 12rpx;
  background: var(--color-bg-code);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color 0.2s, transform 0.1s;
}
:deep(.filter-row-chips-wrap .fc) {
  flex: none;
  padding: 12rpx 24rpx;
}
:deep(.fc-active) {
  background: var(--color-bg-brand-light);
}
:deep(.fc-text) {
  font-size: 26rpx;
  color: var(--color-text-secondary);
  white-space: nowrap;
}
:deep(.fc-text-active) {
  color: var(--color-text-primary);
  font-weight: 700;
}
:deep(.fc-divider) {
  width: 100%;
  height: 0;
}

/* ── Gravity Tooltip (CSS-only) ── */
:deep(.fc-gravity) {
  position: relative;
}
:deep(.gravity-tooltip) {
  display: none;
}
@media (hover: hover) {
  :deep(.fc-gravity:hover .gravity-tooltip) {
    display: block;
    position: absolute;
    top: calc(100% + 10px);
    left: 50%;
    transform: translateX(-50%);
    width: 240px;
    padding: 10px 14px;
    background: var(--color-text-primary);
    color: rgba(255, 255, 255, 0.92);
    font-size: 12px;
    line-height: 1.6;
    border-radius: 8px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
    z-index: 10;
    pointer-events: none;
    white-space: normal;
  }
  :deep(.fc-gravity:hover .gravity-tooltip::before) {
    content: '';
    position: absolute;
    bottom: 100%;
    left: 50%;
    transform: translateX(-50%);
    border: 6px solid transparent;
    border-bottom-color: var(--color-text-primary);
  }
}

/* ── Filter Footer ── */
:deep(.filter-footer) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24rpx 0;
  border-top: 1rpx solid var(--color-border-subtle);
  gap: 24rpx;
}
:deep(.filter-reset-btn) {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20rpx 0;
  border-radius: 16rpx;
  border: 2rpx solid var(--color-border-divider);
  cursor: pointer;
  transition: background-color 0.2s;
}
:deep(.filter-reset-text) {
  font-size: 28rpx;
  color: var(--color-text-hint);
  font-weight: 500;
}
:deep(.filter-confirm-btn) {
  flex: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20rpx 0;
  border-radius: 16rpx;
  background: var(--color-brand);
  cursor: pointer;
  transition: background-color 0.2s, box-shadow 0.2s;
}
:deep(.filter-confirm-text) {
  font-size: 28rpx;
  color: var(--color-text-white);
  font-weight: 600;
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
  color: var(--color-text-muted);
  font-size: 28rpx;
}
.empty-text {
  color: var(--color-text-placeholder);
  font-size: 28rpx;
}

/* ── Card Wrapper ── */
:deep(.card-wrapper) {
  background: var(--color-bg-card);
  border-radius: 20rpx;
  box-shadow: 0 2rpx 16rpx rgba(0, 0, 0, 0.05);
  overflow: hidden;
}

/* ── News Card Group (聚合卡片容器) ── */
:deep(.news-card-group) {
  border-bottom: 1rpx solid var(--color-border-light);
}
:deep(.news-card-group-last) {
  border-bottom: none;
}
:deep(.news-card-group .news-card) {
  border-bottom: none;
}

/* ── News Card ── */
:deep(.news-card) {
  display: flex;
  padding: 32rpx 28rpx;
  position: relative;
  transition: background-color 0.15s;
  cursor: pointer;
}
:deep(.news-card:active) {
  background-color: var(--color-bg-hover);
}

/* ── 关联报道折叠区 ── */
:deep(.related-section) {
  padding: 0 28rpx 20rpx;
}
:deep(.related-toggle) {
  display: flex;
  align-items: center;
  gap: 6rpx;
  padding: 12rpx 20rpx;
  cursor: pointer;
  border-radius: 12rpx;
  transition: background-color 0.15s;
  -webkit-tap-highlight-color: transparent;
}
:deep(.related-toggle:active) {
  background: rgba(0, 0, 0, 0.04);
}
:deep(.related-toggle-text) {
  font-size: 24rpx;
  color: var(--color-text-muted);
  font-weight: 500;
}
:deep(.related-toggle-arrow) {
  font-size: 24rpx;
  color: var(--color-text-placeholder);
  transform: rotate(90deg);
  transition: transform 0.25s ease;
}
:deep(.related-toggle-arrow-up) {
  transform: rotate(-90deg);
}

/* ── 关联报道子列表 ── */
:deep(.related-list) {
  margin: 8rpx 0 4rpx 20rpx;
  padding-left: 20rpx;
  border-left: 3rpx solid var(--color-border);
}
:deep(.related-item) {
  display: flex;
  align-items: flex-start;
  padding: 14rpx 12rpx;
  gap: 12rpx;
  cursor: pointer;
  border-radius: 8rpx;
  transition: background-color 0.15s;
}
:deep(.related-item:active) {
  background: rgba(0, 0, 0, 0.03);
}
:deep(.related-bullet) {
  font-size: 24rpx;
  color: var(--color-text-placeholder);
  flex-shrink: 0;
  line-height: 1.5;
}
:deep(.related-item-body) {
  flex: 1;
  min-width: 0;
}
:deep(.related-item-title) {
  font-size: 26rpx;
  color: var(--color-text-secondary);
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-family: var(--font-sans);
}
:deep(.related-item-meta) {
  display: flex;
  align-items: center;
  gap: 6rpx;
  margin-top: 6rpx;
}
:deep(.related-item-source) {
  font-size: 20rpx;
  color: var(--color-text-muted);
  font-weight: 500;
}
:deep(.related-item-time) {
  font-size: 20rpx;
  color: var(--color-text-placeholder);
}

/* ── Score Badge ── */
:deep(.score-badge) {
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
:deep(.score-num) {
  font-size: 28rpx;
  font-weight: 700;
  color: var(--color-text-white);
  font-family: var(--font-numeric);
}
:deep(.score-high) {
  background: var(--gradient-sentiment-strong-bull);
}
:deep(.score-medium) {
  background: var(--gradient-sentiment-mild-bull);
}
:deep(.score-normal) {
  background: var(--gradient-sentiment-caution);
}
:deep(.score-low) {
  background: var(--gradient-sentiment-mild-bear);
}
:deep(.score-muted) {
  background: var(--gradient-sentiment-neutral);
}

/* ── News Body ── */
:deep(.news-body) {
  flex: 1;
  min-width: 0;
}
:deep(.news-title) {
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
:deep(.news-summary) {
  font-size: 25rpx;
  color: var(--color-text-tertiary);
  line-height: 1.55;
  margin-top: 10rpx;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ── Tags ── */
:deep(.news-tags) {
  display: flex;
  flex-wrap: wrap;
  gap: 8rpx;
  margin-top: 12rpx;
}
:deep(.news-tag) {
  display: inline-block;
  font-size: 22rpx;
  color: var(--color-brand);
  background: rgba(66, 133, 244, 0.08);
  border-radius: 6rpx;
  padding: 4rpx 12rpx;
  line-height: 1.6;
}
:deep(.news-tag-clickable) {
  cursor: pointer;
  transition: background-color 0.15s;
}
:deep(.news-tag-clickable:active) {
  background: rgba(66, 133, 244, 0.2);
}

/* ── Meta ── */
:deep(.news-meta) {
  display: flex;
  align-items: center;
  margin-top: 14rpx;
  gap: 8rpx;
}
:deep(.meta-source) {
  font-size: 22rpx;
  color: var(--color-text-muted);
  font-weight: 500;
}
:deep(.meta-dot) {
  font-size: 22rpx;
  color: var(--color-border-hover);
}
:deep(.meta-time) {
  font-size: 22rpx;
  color: var(--color-text-placeholder);
}

/* ── Gravity Badge ── */
:deep(.gravity-badge) {
  display: flex;
  align-items: center;
  gap: 4rpx;
  padding: 2rpx 12rpx;
  border-radius: 16rpx;
}
:deep(.gravity-icon) {
  font-size: 20rpx;
}
:deep(.gravity-value) {
  font-size: 20rpx;
  font-weight: 600;
  font-family: var(--font-numeric);
}
:deep(.gravity-high) {
  background: rgba(255, 59, 48, 0.12);
}
:deep(.gravity-high .gravity-value) {
  color: var(--color-up);
}
:deep(.gravity-medium) {
  background: rgba(255, 149, 0, 0.12);
}
:deep(.gravity-medium .gravity-value) {
  color: var(--color-warning);
}
:deep(.gravity-normal) {
  background: rgba(52, 199, 89, 0.12);
}
:deep(.gravity-normal .gravity-value) {
  color: var(--color-down);
}
:deep(.gravity-low) {
  background: rgba(142, 142, 147, 0.12);
}
:deep(.gravity-low .gravity-value) {
  color: var(--color-neutral-light);
}

/* ── Sentiment Badge ── */
:deep(.sentiment-badge) { display:flex; align-items:center; gap:4rpx; padding:2rpx 12rpx; border-radius:16rpx; }
:deep(.sentiment-icon)  { font-size:18rpx; }
:deep(.sentiment-value) { font-size:20rpx; font-weight:600; font-family:'SF Pro Display',-apple-system,sans-serif; }
:deep(.sentiment-bull)      { background:rgba(255,59,48,0.12); }
:deep(.sentiment-bull .sentiment-value),:deep(.sentiment-bull .sentiment-icon) { color:var(--color-up); }
:deep(.sentiment-mild-bull) { background:rgba(255,149,0,0.10); }
:deep(.sentiment-mild-bull .sentiment-value),:deep(.sentiment-mild-bull .sentiment-icon) { color:var(--color-warning); }
:deep(.sentiment-neutral)   { background:rgba(142,142,147,0.10); }
:deep(.sentiment-neutral .sentiment-value),:deep(.sentiment-neutral .sentiment-icon) { color:var(--color-neutral-light); }
:deep(.sentiment-mild-bear) { background:rgba(52,199,89,0.07); }
:deep(.sentiment-mild-bear .sentiment-value),:deep(.sentiment-mild-bear .sentiment-icon) { color:var(--color-down); }
:deep(.sentiment-bear)      { background:rgba(52,199,89,0.12); }
:deep(.sentiment-bear .sentiment-value),:deep(.sentiment-bear .sentiment-icon) { color:var(--color-down); }

/* ── Load More ── */
:deep(.load-more) {
  display: flex;
  justify-content: center;
  padding: 36rpx 0;
}
:deep(.load-more-text) {
  font-size: 24rpx;
  color: var(--color-text-muted);
}

/* ═══════════════════════════════════════════════════════════
   PC / Tablet 适配 (屏幕宽度 > 768px)
   ═══════════════════════════════════════════════════════════ */
@media screen and (min-width: 768px) {
  .container {
    max-width: 800px;
    margin: 0 auto;
    padding: 0 24px;
  }

  /* ── Search Bar (PC) ── */
  :deep(.search-bar) {
    margin: 12px 0 8px;
    gap: 10px;
  }
  :deep(.search-input-wrap) {
    border-radius: 22px;
    padding: 10px 18px;
    border-width: 1px;
  }
  :deep(.search-icon) { font-size: 15px; margin-right: 8px; }
  :deep(.search-input) { font-size: 15px; }
  :deep(.search-clear-icon) { font-size: 18px; }
  :deep(.search-cancel-text) { font-size: 15px; }
  :deep(.search-input-wrap:hover) {
    border-color: var(--color-border-hover);
  }
  :deep(.search-bar-focus .search-input-wrap:hover) {
    border-color: var(--color-brand);
  }
  :deep(.sp-section) { margin-bottom: 18px; }
  :deep(.sp-section-title) { font-size: 14px; }
  :deep(.sp-clear-text) { font-size: 13px; }
  :deep(.sp-tags) { gap: 8px; }
  :deep(.sp-tag) {
    padding: 7px 16px;
    border-radius: 16px;
  }
  :deep(.sp-tag:hover) { background: var(--color-bg); }
  :deep(.sp-tag-hot:hover) { background: rgba(66, 133, 244, 0.1); }
  :deep(.sp-tag-text) { font-size: 13px; }
  :deep(.search-results-count) { font-size: 13px; }
  :deep(.relevance-badge) {
    gap: 3px;
    padding: 1px 8px;
    border-radius: 10px;
  }
  :deep(.relevance-label) { font-size: 11px; }
  :deep(.relevance-value) { font-size: 11px; }

  /* ── Header ── */
  .header {
    padding: 24px 0 16px;
  }
  .logo {
    font-size: 28px;
    letter-spacing: 0.5px;
  }
  .inspire-btn {
    width: 36px;
    height: 36px;
  }
  .inspire-btn:hover {
    background: rgba(26, 26, 46, 0.1);
    box-shadow: 0 2px 8px rgba(26, 26, 46, 0.08);
  }
  .inspire-btn-copied:hover {
    background: rgba(52, 199, 89, 0.15);
    box-shadow: 0 2px 8px rgba(52, 199, 89, 0.1);
  }
  .inspire-icon { width: 20px; height: 20px; }
  .subtitle {
    font-size: 13px;
    margin-top: 4px;
  }

  /* ── Category Tabs (PC) ── */
  .category-tabs {
    margin: 14px 0 4px;
    border-radius: 12px;
    padding: 3px;
  }
  .category-tab {
    padding: 9px 0;
    border-radius: 10px;
  }
  .category-tab:hover:not(.category-tab-active) {
    background: rgba(0, 0, 0, 0.03);
  }
  .category-tab-text {
    font-size: 14px;
  }

  /* ── Filter Trigger Bar ── */
  :deep(.filter-trigger-bar) {
    margin: 10px 0 8px;
  }
  :deep(.filter-trigger-left) {
    gap: 8px;
  }
  :deep(.filter-trigger-btn) {
    gap: 6px;
    padding: 8px 16px;
    border-radius: 20px;
    border-width: 1px;
  }
  :deep(.filter-trigger-btn:hover) {
    border-color: var(--color-brand);
    background: var(--color-bg-brand-light);
    box-shadow: 0 2px 8px rgba(66, 133, 244, 0.15);
  }
  :deep(.filter-trigger-icon) {
    font-size: 14px;
  }
  :deep(.filter-trigger-text) {
    font-size: 14px;
  }
  :deep(.filter-arrow) {
    font-size: 15px;
  }
  :deep(.filter-tags) {
    gap: 6px;
  }
  :deep(.filter-tag) {
    padding: 3px 10px;
    border-radius: 12px;
  }
  :deep(.filter-tag-text) {
    font-size: 12px;
  }
  :deep(.stats-text-inline) {
    font-size: 12px;
    margin-left: 8px;
  }

  /* ── Filter Popover (PC) ── */
  :deep(.filter-popover) {
    padding-top: 6px;
  }
  :deep(.filter-popover-body) {
    border-radius: 14px;
    padding: 24px 28px 0;
    box-shadow: 0 8px 40px rgba(0, 0, 0, 0.12), 0 1px 4px rgba(0, 0, 0, 0.06);
  }
  :deep(.filter-row) {
    padding-bottom: 18px;
    margin-bottom: 16px;
    border-bottom-width: 1px;
  }
  :deep(.filter-row-last) {
    padding-bottom: 12px;
  }
  :deep(.filter-row-label) {
    font-size: 14px;
    width: 50px;
    padding-top: 7px;
  }
  :deep(.filter-row-chips) {
    gap: 10px;
  }
  :deep(.fc) {
    padding: 9px 0;
    border-radius: 8px;
    transition: background-color 0.15s, transform 0.1s;
  }
  :deep(.fc:hover) {
    background: var(--color-bg-section);
    transform: translateY(-1px);
  }
  :deep(.fc-active:hover) {
    background: var(--color-bg-info-light);
  }
  :deep(.filter-row-chips-wrap .fc) {
    padding: 7px 16px;
  }
  :deep(.fc-text) {
    font-size: 14px;
  }
  :deep(.filter-footer) {
    padding: 16px 0;
    gap: 16px;
    border-top-width: 1px;
  }
  :deep(.filter-reset-btn) {
    padding: 10px 0;
    border-radius: 10px;
    border-width: 1px;
  }
  :deep(.filter-reset-btn:hover) {
    background: var(--color-bg-code);
  }
  :deep(.filter-reset-text) {
    font-size: 14px;
  }
  :deep(.filter-confirm-btn) {
    padding: 10px 0;
    border-radius: 10px;
  }
  :deep(.filter-confirm-btn:hover) {
    background: var(--color-brand-hover);
    box-shadow: 0 4px 12px rgba(66, 133, 244, 0.3);
  }
  :deep(.filter-confirm-text) {
    font-size: 14px;
  }

  /* ── News List ── */
  .news-list {
    padding-bottom: 16px;
  }
  .loading-container,
  .empty-container {
    padding: 80px 0;
  }
  .loading-text,
  .empty-text {
    font-size: 15px;
  }

  /* ── Card Wrapper ── */
  :deep(.card-wrapper) {
    border-radius: 14px;
    box-shadow: 0 1px 12px rgba(0, 0, 0, 0.06);
  }

  /* ── News Card ── */
  :deep(.news-card) {
    padding: 20px 24px;
    transition: background-color 0.2s;
  }
  :deep(.news-card:hover) {
    background-color: var(--color-bg-hover);
  }
  :deep(.news-card:active) {
    background-color: var(--color-bg-active);
  }

  /* ── 关联报道 (PC) ── */
  :deep(.related-section) {
    padding: 0 24px 14px;
  }
  :deep(.related-toggle) {
    padding: 7px 14px;
    border-radius: 8px;
    gap: 4px;
  }
  :deep(.related-toggle:hover) {
    background: rgba(0, 0, 0, 0.03);
  }
  :deep(.related-toggle-text) {
    font-size: 13px;
  }
  :deep(.related-toggle-arrow) {
    font-size: 13px;
  }
  :deep(.related-list) {
    margin: 4px 0 2px 14px;
    padding-left: 14px;
    border-left-width: 2px;
  }
  :deep(.related-item) {
    padding: 8px 10px;
    gap: 8px;
    border-radius: 6px;
  }
  :deep(.related-item:hover) {
    background: rgba(0, 0, 0, 0.025);
  }
  :deep(.related-bullet) {
    font-size: 13px;
  }
  :deep(.related-item-title) {
    font-size: 14px;
  }
  :deep(.related-item-source),
  :deep(.related-item-time) {
    font-size: 11px;
  }
  :deep(.related-item-meta .meta-dot) {
    font-size: 11px;
  }

  /* ── Score Badge ── */
  :deep(.score-badge) {
    width: 48px;
    height: 32px;
    border-radius: 8px;
    margin-right: 16px;
    margin-top: 4px;
  }
  :deep(.score-num) {
    font-size: 15px;
  }

  /* ── News Body ── */
  :deep(.news-title) {
    font-size: 16px;
    line-height: 1.5;
  }
  :deep(.news-summary) {
    font-size: 13.5px;
    margin-top: 6px;
    line-height: 1.6;
    -webkit-line-clamp: 3;
  }

  /* ── Tags ── */
  :deep(.news-tags) {
    gap: 6px;
    margin-top: 8px;
  }
  :deep(.news-tag) {
    font-size: 12px;
    border-radius: 4px;
    padding: 2px 8px;
  }
  :deep(.news-tag-clickable:hover) {
    background: rgba(66, 133, 244, 0.18);
  }

  /* ── Meta ── */
  :deep(.news-meta) {
    margin-top: 10px;
    gap: 6px;
  }
  :deep(.meta-source),
  :deep(.meta-dot),
  :deep(.meta-time) {
    font-size: 12px;
  }

  /* ── Gravity Badge ── */
  :deep(.gravity-badge) {
    gap: 3px;
    padding: 1px 8px;
    border-radius: 10px;
  }
  :deep(.gravity-icon) {
    font-size: 11px;
  }
  :deep(.gravity-value) {
    font-size: 11px;
  }

  /* ── Load More ── */
  :deep(.load-more) {
    padding: 24px 0;
  }
  :deep(.load-more-text) {
    font-size: 13px;
  }

  /* ── Sentiment Badge PC ── */
  :deep(.sentiment-badge) { gap:3px; padding:1px 8px; border-radius:10px; }
  :deep(.sentiment-icon),:deep(.sentiment-value) { font-size:11px; }
}

/* ═══════════════════════════════════════════════════════════
   大屏 (≥1200px)
   ═══════════════════════════════════════════════════════════ */
@media screen and (min-width: 1200px) {
  .container {
    max-width: 860px;
  }
  :deep(.news-summary) {
    -webkit-line-clamp: 4;
    line-height: 1.65;
  }
}
</style>
