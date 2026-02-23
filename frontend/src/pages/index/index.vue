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

    <!-- 搜索栏 -->
    <view class="search-bar" :class="{ 'search-bar-focus': searchFocused }">
      <view class="search-input-wrap">
        <text class="search-icon">🔍</text>
        <input
          class="search-input"
          type="text"
          placeholder="搜索财经新闻..."
          :value="searchQuery"
          @input="onSearchInput"
          @focus="onSearchFocus"
          @confirm="onSearchConfirm"
          confirm-type="search"
        />
        <view v-if="searchQuery" class="search-clear" @click="onClearSearch">
          <text class="search-clear-icon">×</text>
        </view>
      </view>
      <view v-if="searchMode" class="search-cancel" @click="onExitSearch">
        <text class="search-cancel-text">取消</text>
      </view>
    </view>

    <!-- 搜索面板: 热门话题 + 搜索历史 (搜索模式且无查询时) -->
    <view v-if="searchMode && !searchQuery" class="search-panel">
      <!-- 搜索历史 -->
      <view v-if="searchHistory.length" class="sp-section">
        <view class="sp-section-header">
          <text class="sp-section-title">搜索历史</text>
          <view class="sp-clear-btn" @click="clearHistory">
            <text class="sp-clear-text">清除</text>
          </view>
        </view>
        <view class="sp-tags">
          <view v-for="h in searchHistory" :key="h" class="sp-tag" @click="onQuickSearch(h)">
            <text class="sp-tag-text">{{ h }}</text>
          </view>
        </view>
      </view>
      <!-- 热门话题 -->
      <view v-if="hotTopics.length" class="sp-section">
        <view class="sp-section-header">
          <text class="sp-section-title">热门话题</text>
        </view>
        <view class="sp-tags">
          <view v-for="t in hotTopics" :key="t" class="sp-tag sp-tag-hot" @click="onQuickSearch(t)">
            <text class="sp-tag-text">{{ t }}</text>
          </view>
        </view>
      </view>
    </view>

    <!-- 搜索结果 -->
    <view v-if="searchMode && searchQuery && searchSubmitted" class="search-results">
      <view class="search-results-header">
        <text class="search-results-count">找到 {{ searchTotal }} 条结果</text>
      </view>

      <view v-if="searchLoading && searchList.length === 0" class="loading-container">
        <text class="loading-text">搜索中...</text>
      </view>

      <view v-else-if="searchList.length === 0" class="empty-container">
        <text class="empty-text">未找到相关新闻，换个关键词试试</text>
      </view>

      <view v-else class="card-wrapper">
        <view
          v-for="(item, idx) in searchList"
          :key="item.id"
          class="news-card"
          :class="{ 'news-card-last': idx === searchList.length - 1 }"
          @click="onOpenUrl(item.url)"
        >
          <view class="score-badge" :class="scoreClass(item.ai_score)">
            <text class="score-num">{{ formatScore(item.ai_score) }}</text>
          </view>
          <view class="news-body">
            <rich-text class="news-title search-highlight" :nodes="item.title_highlighted || item.title"></rich-text>
            <rich-text v-if="item.summary_highlighted || item.ai_summary" class="news-summary search-highlight" :nodes="item.summary_highlighted || item.ai_summary || ''"></rich-text>
            <view v-if="item.tags && item.tags.length" class="news-tags">
              <text v-for="tag in item.tags" :key="tag" class="news-tag news-tag-clickable" @click.stop="onTagSearch(tag)">{{ tag }}</text>
            </view>
            <view class="news-meta">
              <text class="meta-source">{{ item.source }}</text>
              <text class="meta-dot">·</text>
              <text class="meta-time">{{ formatTime(item.created_at) }}</text>
              <template v-if="item.relevance_score != null">
                <text class="meta-dot">·</text>
                <view class="relevance-badge">
                  <text class="relevance-label">相关度</text>
                  <text class="relevance-value">{{ formatRelevance(item.relevance_score) }}</text>
                </view>
              </template>
            </view>
          </view>
        </view>
      </view>

      <view v-if="searchList.length > 0" class="load-more">
        <text v-if="searchLoadingMore" class="load-more-text">正在加载更多...</text>
        <text v-else-if="searchNoMore" class="load-more-text">— 没有更多了 —</text>
      </view>
    </view>

    <!-- 以下为原有 News Feed 内容 (非搜索模式时显示) -->
    <template v-if="!searchMode">

    <!-- 筛选按钮 + 已选标签 -->
    <view class="filter-trigger-bar">
      <view class="filter-trigger-left">
        <view class="filter-trigger-btn" :class="{ 'filter-trigger-active': hasActiveFilter }" @click="openFilter">
          <text class="filter-trigger-icon">☰</text>
          <text class="filter-trigger-text">筛选</text>
          <text class="filter-arrow" :class="{ 'filter-arrow-up': filterOpen }">›</text>
        </view>
        <view v-if="filterTags.length" class="filter-tags">
          <view v-for="tag in filterTags" :key="tag" class="filter-tag">
            <text class="filter-tag-text">{{ tag }}</text>
          </view>
        </view>
      </view>
      <text class="stats-text-inline">{{ total }} 条</text>
    </view>

    <!-- 筛选面板（展开/收起） -->
    <view v-if="filterOpen" class="filter-panel">
      <view class="filter-mask" @click="cancelFilter"></view>
      <view class="filter-panel-body">
        <!-- 排序 -->
        <view class="filter-row">
          <text class="filter-row-label">排序</text>
          <view class="filter-row-chips">
            <view
              v-for="tab in sortTabs"
              :key="tab.value"
              class="fc"
              :class="{ 'fc-active': tmpSort === tab.value, 'fc-gravity': tab.value === 'hot' }"
              @click="tmpSort = tab.value"
            >
              <text class="fc-text" :class="{ 'fc-text-active': tmpSort === tab.value }">{{ tab.label }}</text>
              <view v-if="tab.value === 'hot'" class="gravity-tooltip">基于 Hacker News 经典重力算法：高评分的新鲜资讯排在前面，随时间自然下沉</view>
            </view>
          </view>
        </view>
        <!-- 时效 -->
        <view class="filter-row">
          <text class="filter-row-label">时效</text>
          <view class="filter-row-chips">
            <view
              v-for="opt in ageOptions"
              :key="opt.value"
              class="fc"
              :class="{ 'fc-active': tmpAge === opt.value }"
              @click="tmpAge = opt.value"
            >
              <text class="fc-text" :class="{ 'fc-text-active': tmpAge === opt.value }">{{ opt.label }}</text>
            </view>
          </view>
        </view>
        <!-- 来源 -->
        <view class="filter-row">
          <text class="filter-row-label">来源</text>
          <view class="filter-row-chips filter-row-chips-wrap">
            <view class="fc" :class="{ 'fc-active': !tmpSource }" @click="tmpSource = ''">
              <text class="fc-text" :class="{ 'fc-text-active': !tmpSource }">全部</text>
            </view>
            <view
              v-for="src in cnSources"
              :key="src"
              class="fc"
              :class="{ 'fc-active': tmpSource === src }"
              @click="tmpSource = src"
            >
              <text class="fc-text" :class="{ 'fc-text-active': tmpSource === src }">{{ src }}</text>
            </view>
            <view class="fc-divider"></view>
            <view
              v-for="src in enSources"
              :key="src"
              class="fc"
              :class="{ 'fc-active': tmpSource === src }"
              @click="tmpSource = src"
            >
              <text class="fc-text" :class="{ 'fc-text-active': tmpSource === src }">{{ src }}</text>
            </view>
          </view>
        </view>
        <!-- 评分 -->
        <view class="filter-row filter-row-last">
          <text class="filter-row-label">评分</text>
          <view class="filter-row-chips">
            <view
              v-for="s in scoreOptions"
              :key="s"
              class="fc"
              :class="{ 'fc-active': tmpScore === s }"
              @click="tmpScore = s"
            >
              <text class="fc-text" :class="{ 'fc-text-active': tmpScore === s }">≥{{ s }}</text>
            </view>
          </view>
        </view>
        <!-- 底部操作栏 -->
        <view class="filter-footer">
          <view class="filter-reset-btn" @click="resetTmp">
            <text class="filter-reset-text">重置</text>
          </view>
          <view class="filter-confirm-btn" @click="confirmFilter">
            <text class="filter-confirm-text">确认</text>
          </view>
        </view>
      </view>
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

            <!-- Tags -->
            <view v-if="item.tags && item.tags.length" class="news-tags">
              <text v-for="tag in item.tags" :key="tag" class="news-tag news-tag-clickable" @click.stop="onTagSearch(tag)">{{ tag }}</text>
            </view>

            <view class="news-meta">
              <text class="meta-source">{{ item.source }}</text>
              <text class="meta-dot">·</text>
              <text class="meta-time">{{ formatTime(item.created_at) }}</text>
              <!-- Hacker Gravity 指标 (hot 模式下显示) -->
              <template v-if="currentSort === 'hot' && item.ranking_score != null">
                <text class="meta-dot">·</text>
                <view class="gravity-badge" :class="gravityClass(item.ranking_score)">
                  <text class="gravity-icon">⚡</text>
                  <text class="gravity-value">{{ formatGravity(item.ranking_score) }}</text>
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

    <!-- 底部备案信息 -->
    </template>
    <view class="site-footer">
      <text class="footer-icp" @click="onOpenUrl('https://beian.miit.gov.cn/')">蜀ICP备2026006985号</text>
      <text class="footer-copy">© 2026 Rick</text>
    </view>
  </view>
</template>

<script>
import { fetchNews, searchNews, fetchHotTopics } from '../../utils/api.js'

const PAGE_SIZE = 20
const SEARCH_HISTORY_KEY = 'alphareader_search_history'
const MAX_HISTORY = 10

export default {
  data() {
    return {
      newsList: [],
      total: 0,
      offset: 0,
      loading: true,
      loadingMore: false,
      noMore: false,
      filterOpen: false,
      // 实际生效的筛选值
      minScore: 5,
      currentSource: '',
      currentSort: 'hot',
      maxAgeHours: 72,
      // 面板内暂存值（点确认后才写入实际值）
      tmpSort: 'hot',
      tmpAge: 72,
      tmpSource: '',
      tmpScore: 5,
      promptCopied: false,
      scoreOptions: [5, 6, 7, 8, 9],
      cnSources: ['财联社', '华尔街见闻'],
      enSources: ['MarketWatch', 'Seeking Alpha', 'TechCrunch', 'Finnhub'],
      sortTabs: [
        { value: 'hot', label: 'Gravity' },
        { value: 'latest', label: '最新' },
        { value: 'score', label: '评分' },
      ],
      ageOptions: [
        { value: 24, label: '24h' },
        { value: 48, label: '48h' },
        { value: 72, label: '3天' },
        { value: 168, label: '7天' },
        { value: 0, label: '不限' },
      ],
      // ── 搜索相关 ──
      searchMode: false,
      searchFocused: false,
      searchQuery: '',
      searchSubmitted: false,
      searchList: [],
      searchTotal: 0,
      searchOffset: 0,
      searchLoading: false,
      searchLoadingMore: false,
      searchNoMore: false,
      searchHistory: [],
      hotTopics: [],
      _searchDebounceTimer: null,
    }
  },

  computed: {
    sortLabel() {
      const tab = this.sortTabs.find(t => t.value === this.currentSort)
      return tab ? tab.label : ''
    },
    hasActiveFilter() {
      return this.currentSort !== 'hot' || this.minScore !== 5 || this.currentSource !== '' || this.maxAgeHours !== 72
    },
    /** 外层筛选按钮右侧展示的标签列表 */
    filterTags() {
      const tags = []
      const tab = this.sortTabs.find(t => t.value === this.currentSort)
      if (tab && this.currentSort !== 'hot') tags.push(tab.label)
      if (this.currentSort === 'hot') tags.push('Gravity')
      const age = this.ageOptions.find(a => a.value === this.maxAgeHours)
      if (age && this.maxAgeHours !== 72) tags.push(age.label)
      if (this.currentSource) tags.push(this.currentSource)
      if (this.minScore !== 5) tags.push(`≥${this.minScore}`)
      return tags
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
    if (this.searchMode && this.searchSubmitted) {
      this.searchLoadMore()
    } else {
      this.loadMore()
    }
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
          max_age_hours: this.maxAgeHours || undefined,
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
          max_age_hours: this.maxAgeHours || undefined,
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

    /** 打开筛选面板 — 同步当前值到暂存 */
    openFilter() {
      this.tmpSort = this.currentSort
      this.tmpAge = this.maxAgeHours
      this.tmpSource = this.currentSource
      this.tmpScore = this.minScore
      this.filterOpen = true
    },

    /** 确认筛选 — 暂存值写入实际值并加载 */
    confirmFilter() {
      this.currentSort = this.tmpSort
      this.maxAgeHours = this.tmpAge
      this.currentSource = this.tmpSource
      this.minScore = this.tmpScore
      this.filterOpen = false
      this.resetAndLoad()
    },

    /** 取消 — 关闭面板不应用 */
    cancelFilter() {
      this.filterOpen = false
    },

    /** 重置暂存值为默认 */
    resetTmp() {
      this.tmpSort = 'hot'
      this.tmpAge = 72
      this.tmpSource = ''
      this.tmpScore = 6
    },

    /** 灵感按钮：用前端已有 newsList 同步组装 Prompt 并复制（iOS Safari 兼容） */
    onInspireCopy() {
      if (this.promptCopied) return
      const list = this.newsList
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

      // iOS Safari 兼容：同步调用 navigator.clipboard（在顶层 click 事件中）
      // #ifdef H5
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(prompt).then(() => {
          this.promptCopied = true
          uni.showToast({ title: 'Prompt 已复制', icon: 'success' })
          setTimeout(() => { this.promptCopied = false }, 3000)
        }).catch(() => {
          this._fallbackCopy(prompt)
        })
      } else {
        this._fallbackCopy(prompt)
      }
      // #endif
      // #ifndef H5
      uni.setClipboardData({
        data: prompt,
        success: () => {
          this.promptCopied = true
          uni.showToast({ title: 'Prompt 已复制', icon: 'success' })
          setTimeout(() => { this.promptCopied = false }, 3000)
        },
      })
      // #endif
    },

    /** Clipboard fallback（旧浏览器 / iOS 低版本） */
    _fallbackCopy(text) {
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
          this.promptCopied = true
          uni.showToast({ title: 'Prompt 已复制', icon: 'success' })
          setTimeout(() => { this.promptCopied = false }, 3000)
        } else {
          uni.showToast({ title: '复制失败，请手动复制', icon: 'none' })
        }
      } catch {
        uni.showToast({ title: '复制失败', icon: 'none' })
      }
      // #endif
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
      if (score >= 6) return 'score-low'
      return 'score-muted'
    },

    formatScore(score) {
      if (score == null) return '-'
      return Number(score).toFixed(1)
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

    /** Hacker Gravity 值格式化 — 统一保留1位小数 */
    formatGravity(score) {
      if (score == null) return ''
      return Number(score).toFixed(1)
    },

    /** Hacker Gravity 等级 class */
    gravityClass(score) {
      if (score >= 1.0) return 'gravity-high'
      if (score >= 0.3) return 'gravity-medium'
      if (score >= 0.05) return 'gravity-normal'
      return 'gravity-low'
    },

    // ── 搜索相关方法 ──

    /** 搜索框获得焦点 */
    onSearchFocus() {
      this.searchFocused = true
      this.searchMode = true
      this.loadSearchHistory()
      this.loadHotTopics()
    },

    /** 搜索输入 (带防抖) */
    onSearchInput(e) {
      this.searchQuery = e.detail.value
      this.searchSubmitted = false
    },

    /** 回车确认搜索 */
    onSearchConfirm() {
      const q = this.searchQuery.trim()
      if (!q) return
      this.addToHistory(q)
      this.doSearch()
    },

    /** 点击热门话题/历史快速搜索 */
    onQuickSearch(keyword) {
      this.searchQuery = keyword
      this.addToHistory(keyword)
      this.doSearch()
    },

    /** 点击新闻标签触发搜索 */
    onTagSearch(tag) {
      this.searchMode = true
      this.searchFocused = true
      this.searchQuery = tag
      this.addToHistory(tag)
      this.loadSearchHistory()
      this.loadHotTopics()
      this.doSearch()
    },

    /** 清除搜索输入 */
    onClearSearch() {
      this.searchQuery = ''
      this.searchSubmitted = false
      this.searchList = []
      this.searchTotal = 0
    },

    /** 退出搜索模式 */
    onExitSearch() {
      this.searchMode = false
      this.searchFocused = false
      this.searchQuery = ''
      this.searchSubmitted = false
      this.searchList = []
      this.searchTotal = 0
      this.searchOffset = 0
    },

    /** 执行搜索 */
    async doSearch() {
      const q = this.searchQuery.trim()
      if (!q) return
      this.searchSubmitted = true
      this.searchLoading = true
      this.searchList = []
      this.searchOffset = 0
      this.searchNoMore = false
      try {
        const data = await searchNews({ q, limit: PAGE_SIZE, offset: 0 })
        this.searchList = data.items || []
        this.searchTotal = data.total || 0
        this.searchOffset = this.searchList.length
        this.searchNoMore = this.searchOffset >= this.searchTotal
      } catch (e) {
        console.error('搜索失败:', e)
        uni.showToast({ title: '搜索失败', icon: 'none' })
      } finally {
        this.searchLoading = false
      }
    },

    /** 搜索加载更多 */
    async searchLoadMore() {
      if (this.searchLoadingMore || this.searchNoMore || this.searchLoading) return
      this.searchLoadingMore = true
      try {
        const data = await searchNews({
          q: this.searchQuery.trim(),
          limit: PAGE_SIZE,
          offset: this.searchOffset,
        })
        const items = data.items || []
        this.searchList = this.searchList.concat(items)
        this.searchTotal = data.total || 0
        this.searchOffset += items.length
        this.searchNoMore = items.length < PAGE_SIZE || this.searchOffset >= this.searchTotal
      } catch (e) {
        console.error('搜索加载更多失败:', e)
      } finally {
        this.searchLoadingMore = false
      }
    },

    /** 格式化相关度分数 */
    formatRelevance(score) {
      if (score == null) return ''
      // 映射到百分比展示
      const pct = Math.min(score * 100, 99.9)
      return pct < 1 ? pct.toFixed(2) : pct.toFixed(1)
    },

    /** 加载搜索历史 */
    loadSearchHistory() {
      try {
        const raw = uni.getStorageSync(SEARCH_HISTORY_KEY)
        this.searchHistory = raw ? JSON.parse(raw) : []
      } catch { this.searchHistory = [] }
    },

    /** 添加搜索历史 */
    addToHistory(keyword) {
      let history = this.searchHistory.filter(h => h !== keyword)
      history.unshift(keyword)
      if (history.length > MAX_HISTORY) history = history.slice(0, MAX_HISTORY)
      this.searchHistory = history
      try { uni.setStorageSync(SEARCH_HISTORY_KEY, JSON.stringify(history)) } catch {}
    },

    /** 清除搜索历史 */
    clearHistory() {
      this.searchHistory = []
      try { uni.removeStorageSync(SEARCH_HISTORY_KEY) } catch {}
    },

    /** 加载热门话题 */
    async loadHotTopics() {
      if (this.hotTopics.length) return
      try {
        const data = await fetchHotTopics()
        this.hotTopics = data.topics || []
      } catch { /* ignore */ }
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
  color: #8c8c9a;
  margin-top: 6rpx;
  letter-spacing: 1rpx;
}

/* ── Search Bar ── */
.search-bar {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin: 16rpx 0 8rpx;
}
.search-input-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  background: #ffffff;
  border-radius: 36rpx;
  padding: 16rpx 24rpx;
  border: 2rpx solid #e8e8ed;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.search-bar-focus .search-input-wrap {
  border-color: #4285f4;
  box-shadow: 0 2rpx 12rpx rgba(66, 133, 244, 0.15);
}
.search-icon {
  font-size: 28rpx;
  margin-right: 12rpx;
  flex-shrink: 0;
}
.search-input {
  flex: 1;
  font-size: 28rpx;
  color: #1a1a2e;
  background: transparent;
  border: none;
  outline: none;
  line-height: 1.4;
}
.search-clear {
  padding: 4rpx 8rpx;
  margin-left: 8rpx;
  flex-shrink: 0;
  cursor: pointer;
}
.search-clear-icon {
  font-size: 32rpx;
  color: #b0b0be;
  font-weight: 500;
}
.search-cancel {
  flex-shrink: 0;
  padding: 8rpx 4rpx;
  cursor: pointer;
}
.search-cancel-text {
  font-size: 28rpx;
  color: #4285f4;
  font-weight: 500;
}

/* ── Search Panel (History + Hot Topics) ── */
.search-panel {
  padding: 16rpx 0;
}
.sp-section {
  margin-bottom: 28rpx;
}
.sp-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16rpx;
}
.sp-section-title {
  font-size: 26rpx;
  color: #6b6b7b;
  font-weight: 600;
}
.sp-clear-btn {
  padding: 4rpx 16rpx;
  cursor: pointer;
}
.sp-clear-text {
  font-size: 24rpx;
  color: #b0b0be;
}
.sp-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 12rpx;
}
.sp-tag {
  padding: 12rpx 24rpx;
  background: #ffffff;
  border-radius: 24rpx;
  border: 1rpx solid #e8e8ed;
  cursor: pointer;
  transition: background-color 0.15s;
}
.sp-tag:active {
  background: #f0f2f5;
}
.sp-tag-hot {
  background: rgba(66, 133, 244, 0.06);
  border-color: rgba(66, 133, 244, 0.2);
}
.sp-tag-text {
  font-size: 24rpx;
  color: #3a3a4a;
}
.sp-tag-hot .sp-tag-text {
  color: #4285f4;
}

/* ── Search Results ── */
.search-results {
  padding-bottom: 20rpx;
}
.search-results-header {
  padding: 8rpx 0 16rpx;
}
.search-results-count {
  font-size: 24rpx;
  color: #8c8c9a;
}

/* ── Search Highlight ── */
.search-highlight :deep(mark) {
  background: rgba(66, 133, 244, 0.18);
  color: #1a73e8;
  font-weight: 600;
  padding: 0 2rpx;
  border-radius: 4rpx;
}

/* ── Relevance Badge ── */
.relevance-badge {
  display: flex;
  align-items: center;
  gap: 4rpx;
  padding: 2rpx 12rpx;
  background: rgba(66, 133, 244, 0.08);
  border-radius: 16rpx;
}
.relevance-label {
  font-size: 20rpx;
  color: #8c8c9a;
}
.relevance-value {
  font-size: 20rpx;
  color: #4285f4;
  font-weight: 600;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}

/* ── Filter Trigger Bar ── */
.filter-trigger-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 12rpx 0 8rpx;
}
.filter-trigger-left {
  display: flex;
  align-items: center;
  gap: 12rpx;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}
.filter-trigger-btn {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 14rpx 24rpx;
  background: #ffffff;
  border-radius: 32rpx;
  border: 2rpx solid #e0e0e6;
  flex-shrink: 0;
  cursor: pointer;
  transition: border-color 0.2s, background-color 0.2s, box-shadow 0.2s;
}
.filter-trigger-active {
  border-color: #4285f4;
  background: #f0f6ff;
}
.filter-trigger-icon {
  font-size: 26rpx;
  color: #6b6b7b;
}
.filter-trigger-text {
  font-size: 26rpx;
  color: #3a3a4a;
  font-weight: 500;
}
.filter-arrow {
  font-size: 28rpx;
  color: #8c8c9a;
  transform: rotate(90deg);
  transition: transform 0.25s;
}
.filter-arrow-up {
  transform: rotate(-90deg);
}
.filter-tags {
  display: flex;
  align-items: center;
  gap: 8rpx;
  overflow: hidden;
}
.filter-tag {
  padding: 6rpx 16rpx;
  background: #e8f0fe;
  border-radius: 20rpx;
  flex-shrink: 0;
}
.filter-tag-text {
  font-size: 22rpx;
  color: #4285f4;
  font-weight: 500;
  white-space: nowrap;
}
.stats-text-inline {
  font-size: 22rpx;
  color: #8c8c9a;
  flex-shrink: 0;
  margin-left: 12rpx;
}

/* ── Filter Panel ── */
.filter-panel {
  position: fixed;
  left: 0;
  top: 0;
  right: 0;
  bottom: 0;
  z-index: 999;
  display: flex;
  justify-content: center;
}
.filter-mask {
  position: absolute;
  left: 0;
  top: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.35);
}
.filter-panel-body {
  position: relative;
  z-index: 1;
  background: #ffffff;
  border-radius: 0 0 28rpx 28rpx;
  padding: 32rpx 32rpx 0;
  box-shadow: 0 8rpx 32rpx rgba(0, 0, 0, 0.1);
  width: 100%;
}
.filter-row {
  display: flex;
  align-items: flex-start;
  padding-bottom: 28rpx;
  border-bottom: 1rpx solid #f2f2f5;
  margin-bottom: 24rpx;
}
.filter-row-last {
  border-bottom: none;
  margin-bottom: 0;
  padding-bottom: 16rpx;
}
.filter-row-label {
  font-size: 26rpx;
  color: #8c8c9a;
  width: 80rpx;
  flex-shrink: 0;
  font-weight: 500;
  padding-top: 10rpx;
}
.filter-row-chips {
  display: flex;
  flex-wrap: nowrap;
  gap: 16rpx;
  flex: 1;
}
.filter-row-chips-wrap {
  flex-wrap: wrap;
}

/* ── Filter Chip (fc) ── */
.fc {
  flex: 1;
  min-width: 0;
  padding: 16rpx 0;
  border-radius: 12rpx;
  background: #f5f5f7;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color 0.2s, transform 0.1s;
}
.filter-row-chips-wrap .fc {
  flex: none;
  padding: 12rpx 24rpx;
}
.fc-active {
  background: #f0f6ff;
}
.fc-text {
  font-size: 26rpx;
  color: #3a3a4a;
  white-space: nowrap;
}
.fc-text-active {
  color: #1a1a2e;
  font-weight: 700;
}
.fc-divider {
  width: 100%;
  height: 0;
}

/* ── Gravity Tooltip (CSS-only) ── */
.fc-gravity {
  position: relative;
}
.gravity-tooltip {
  display: none;
}
@media (hover: hover) {
  .fc-gravity:hover .gravity-tooltip {
    display: block;
    position: absolute;
    top: calc(100% + 10px);
    left: 50%;
    transform: translateX(-50%);
    width: 240px;
    padding: 10px 14px;
    background: #1a1a2e;
    color: rgba(255, 255, 255, 0.92);
    font-size: 12px;
    line-height: 1.6;
    border-radius: 8px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
    z-index: 10;
    pointer-events: none;
    white-space: normal;
  }
  .fc-gravity:hover .gravity-tooltip::before {
    content: '';
    position: absolute;
    bottom: 100%;
    left: 50%;
    transform: translateX(-50%);
    border: 6px solid transparent;
    border-bottom-color: #1a1a2e;
  }
}

/* ── Filter Footer ── */
.filter-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24rpx 0;
  border-top: 1rpx solid #f2f2f5;
  gap: 24rpx;
}
.filter-reset-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20rpx 0;
  border-radius: 16rpx;
  border: 2rpx solid #e0e0e6;
  cursor: pointer;
  transition: background-color 0.2s;
}
.filter-reset-text {
  font-size: 28rpx;
  color: #6b6b7b;
  font-weight: 500;
}
.filter-confirm-btn {
  flex: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20rpx 0;
  border-radius: 16rpx;
  background: #4285f4;
  cursor: pointer;
  transition: background-color 0.2s, box-shadow 0.2s;
}
.filter-confirm-text {
  font-size: 28rpx;
  color: #ffffff;
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
  cursor: pointer;
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
.score-high {
  background: linear-gradient(135deg, #34c759, #28a745);
}
.score-medium {
  background: linear-gradient(135deg, #ff9500, #e8870e);
}
.score-normal {
  background: linear-gradient(135deg, #f0b429, #d4981e);
}
.score-low {
  background: linear-gradient(135deg, #5ac778, #48b066);
}
.score-muted {
  background: linear-gradient(135deg, #a0a0b0, #8c8c9a);
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

/* ── Tags ── */
.news-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8rpx;
  margin-top: 12rpx;
}
.news-tag {
  display: inline-block;
  font-size: 22rpx;
  color: #4285f4;
  background: rgba(66, 133, 244, 0.08);
  border-radius: 6rpx;
  padding: 4rpx 12rpx;
  line-height: 1.6;
}
.news-tag-clickable {
  cursor: pointer;
  transition: background-color 0.15s;
}
.news-tag-clickable:active {
  background: rgba(66, 133, 244, 0.2);
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

/* ── Gravity Badge ── */
.gravity-badge {
  display: flex;
  align-items: center;
  gap: 4rpx;
  padding: 2rpx 12rpx;
  border-radius: 16rpx;
}
.gravity-icon {
  font-size: 20rpx;
}
.gravity-value {
  font-size: 20rpx;
  font-weight: 600;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.gravity-high {
  background: rgba(255, 59, 48, 0.12);
}
.gravity-high .gravity-value {
  color: #ff3b30;
}
.gravity-medium {
  background: rgba(255, 149, 0, 0.12);
}
.gravity-medium .gravity-value {
  color: #ff9500;
}
.gravity-normal {
  background: rgba(52, 199, 89, 0.12);
}
.gravity-normal .gravity-value {
  color: #34c759;
}
.gravity-low {
  background: rgba(142, 142, 147, 0.12);
}
.gravity-low .gravity-value {
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

/* ── Site Footer ── */
.site-footer {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 40rpx 0 60rpx;
  gap: 8rpx;
}
.footer-icp {
  font-size: 22rpx;
  color: #b0b0be;
  text-decoration: underline;
}
.footer-copy {
  font-size: 22rpx;
  color: #b0b0be;
}

/* ═══════════════════════════════════════════════════════════
   PC / Tablet 适配 (屏幕宽度 > 768px)
   uni-app H5 下 750rpx = 屏幕宽度，PC 宽屏时 rpx 值会被放大。
   使用 @media 覆盖关键布局，限制内容宽度、优化交互体验。
   ═══════════════════════════════════════════════════════════ */
@media screen and (min-width: 768px) {
  /* 整体容器：限宽居中 */
  .container {
    max-width: 800px;
    margin: 0 auto;
    padding: 0 24px;
  }

  /* ── Search Bar (PC) ── */
  .search-bar {
    margin: 12px 0 8px;
    gap: 10px;
  }
  .search-input-wrap {
    border-radius: 22px;
    padding: 10px 18px;
    border-width: 1px;
  }
  .search-icon { font-size: 15px; margin-right: 8px; }
  .search-input { font-size: 15px; }
  .search-clear-icon { font-size: 18px; }
  .search-cancel-text { font-size: 15px; }
  .search-input-wrap:hover {
    border-color: #c0c0cc;
  }
  .search-bar-focus .search-input-wrap:hover {
    border-color: #4285f4;
  }
  .sp-section { margin-bottom: 18px; }
  .sp-section-title { font-size: 14px; }
  .sp-clear-text { font-size: 13px; }
  .sp-tags { gap: 8px; }
  .sp-tag {
    padding: 7px 16px;
    border-radius: 16px;
  }
  .sp-tag:hover { background: #f0f2f5; }
  .sp-tag-hot:hover { background: rgba(66, 133, 244, 0.1); }
  .sp-tag-text { font-size: 13px; }
  .search-results-count { font-size: 13px; }
  .relevance-badge {
    gap: 3px;
    padding: 1px 8px;
    border-radius: 10px;
  }
  .relevance-label { font-size: 11px; }
  .relevance-value { font-size: 11px; }

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

  /* ── Filter Trigger Bar ── */
  .filter-trigger-bar {
    margin: 10px 0 8px;
  }
  .filter-trigger-left {
    gap: 8px;
  }
  .filter-trigger-btn {
    gap: 6px;
    padding: 8px 16px;
    border-radius: 20px;
    border-width: 1px;
  }
  .filter-trigger-btn:hover {
    border-color: #4285f4;
    background: #f0f6ff;
    box-shadow: 0 2px 8px rgba(66, 133, 244, 0.15);
  }
  .filter-trigger-icon {
    font-size: 14px;
  }
  .filter-trigger-text {
    font-size: 14px;
  }
  .filter-arrow {
    font-size: 15px;
  }
  .filter-tags {
    gap: 6px;
  }
  .filter-tag {
    padding: 3px 10px;
    border-radius: 12px;
  }
  .filter-tag-text {
    font-size: 12px;
  }
  .stats-text-inline {
    font-size: 12px;
    margin-left: 8px;
  }

  /* ── Filter Panel (PC: 居中限宽 + 圆角) ── */
  .filter-panel-body {
    max-width: 800px;
    margin: 0 auto;
    border-radius: 0 0 16px 16px;
    padding: 24px 28px 0;
    box-shadow: 0 8px 40px rgba(0, 0, 0, 0.12);
  }
  .filter-row {
    padding-bottom: 18px;
    margin-bottom: 16px;
    border-bottom-width: 1px;
  }
  .filter-row-last {
    padding-bottom: 12px;
  }
  .filter-row-label {
    font-size: 14px;
    width: 50px;
    padding-top: 7px;
  }
  .filter-row-chips {
    gap: 10px;
  }
  .fc {
    padding: 9px 0;
    border-radius: 8px;
    transition: background-color 0.15s, transform 0.1s;
  }
  .fc:hover {
    background: #eef1f5;
    transform: translateY(-1px);
  }
  .fc-active:hover {
    background: #e4edfc;
  }
  .filter-row-chips-wrap .fc {
    padding: 7px 16px;
  }
  .fc-text {
    font-size: 14px;
  }
  .filter-footer {
    padding: 16px 0;
    gap: 16px;
    border-top-width: 1px;
  }
  .filter-reset-btn {
    padding: 10px 0;
    border-radius: 10px;
    border-width: 1px;
  }
  .filter-reset-btn:hover {
    background: #f5f5f7;
  }
  .filter-reset-text {
    font-size: 14px;
  }
  .filter-confirm-btn {
    padding: 10px 0;
    border-radius: 10px;
  }
  .filter-confirm-btn:hover {
    background: #3b78e7;
    box-shadow: 0 4px 12px rgba(66, 133, 244, 0.3);
  }
  .filter-confirm-text {
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
  .card-wrapper {
    border-radius: 14px;
    box-shadow: 0 1px 12px rgba(0, 0, 0, 0.06);
  }

  /* ── News Card ── */
  .news-card {
    padding: 20px 24px;
    transition: background-color 0.2s;
  }
  .news-card:hover {
    background-color: #fafbfc;
  }
  .news-card:active {
    background-color: #f5f6f8;
  }

  /* ── Score Badge ── */
  .score-badge {
    width: 48px;
    height: 32px;
    border-radius: 8px;
    margin-right: 16px;
    margin-top: 4px;
  }
  .score-num {
    font-size: 15px;
  }

  /* ── News Body ── */
  .news-title {
    font-size: 16px;
    line-height: 1.5;
  }
  .news-summary {
    font-size: 13.5px;
    margin-top: 6px;
    line-height: 1.6;
    -webkit-line-clamp: 3;
  }

  /* ── Tags ── */
  .news-tags {
    gap: 6px;
    margin-top: 8px;
  }
  .news-tag {
    font-size: 12px;
    border-radius: 4px;
    padding: 2px 8px;
  }
  .news-tag-clickable:hover {
    background: rgba(66, 133, 244, 0.18);
  }

  /* ── Meta ── */
  .news-meta {
    margin-top: 10px;
    gap: 6px;
  }
  .meta-source,
  .meta-dot,
  .meta-time {
    font-size: 12px;
  }

  /* ── Gravity Badge ── */
  .gravity-badge {
    gap: 3px;
    padding: 1px 8px;
    border-radius: 10px;
  }
  .gravity-icon {
    font-size: 11px;
  }
  .gravity-value {
    font-size: 11px;
  }

  /* ── Load More ── */
  .load-more {
    padding: 24px 0;
  }
  .load-more-text {
    font-size: 13px;
  }

  /* ── Site Footer ── */
  .site-footer {
    padding: 32px 0 48px;
    gap: 6px;
  }
  .footer-icp {
    font-size: 12px;
    cursor: pointer;
  }
  .footer-icp:hover {
    color: #8c8c9a;
  }
  .footer-copy {
    font-size: 12px;
  }
}

/* ═══════════════════════════════════════════════════════════
   大屏 (≥1200px) — 进一步优化阅读体验
   ═══════════════════════════════════════════════════════════ */
@media screen and (min-width: 1200px) {
  .container {
    max-width: 860px;
  }
  .news-summary {
    -webkit-line-clamp: 4;
    line-height: 1.65;
  }
}
</style>
