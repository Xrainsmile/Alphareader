<template>
  <view class="stocks-container">
    <!-- Tab Bar -->
    <view class="tab-bar">
      <view
        class="tab-item"
        :class="{ 'tab-active': activeTab === 'rs' }"
        @click="activeTab = 'rs'"
      >
        <text class="tab-text">RS Rating</text>
      </view>
      <view
        class="tab-item"
        :class="{ 'tab-active': activeTab === 'sandbox' }"
        @click="switchToSandbox"
      >
        <text class="tab-text">模拟仓</text>
      </view>
    </view>

    <!-- ═══════════════════════════════════════════════════════
         RS Rating Tab
         ═══════════════════════════════════════════════════════ -->
    <template v-if="activeTab === 'rs'">
      <!-- Header -->
      <view class="stocks-header">
        <text class="stocks-title">RS Rating</text>
        <text class="stocks-subtitle">相对强度排行 · RS Rating > 80</text>
        <view class="rs-desc" :class="{ 'rs-desc-expanded': descExpanded }" @click="descExpanded = !descExpanded">
          <text class="rs-desc-text">RS Rating（相对强度评级）是衡量股票相对于市场整体表现强弱的量化指标，由《投资者商业日报》（Investor's Business Daily, IBD）开发并广泛应用于成长股投资中。该评级通过对比某只股票在过去52周内的价格表现，与全市场所有上市股票进行排名，得出一个1到99之间的分数，分数越高，代表该股票的表现优于市场中越高比例的个股。例如，RS Rating为90，意味着该股票在过去一年中表现优于90%的其他股票。</text>
        </view>
      </view>

      <!-- 搜索栏 -->
      <view class="search-bar" :class="{ 'search-bar-focus': searchFocused }">
        <view class="search-input-wrap">
          <text class="search-icon">🔍</text>
          <input
            class="search-input"
            type="text"
            placeholder="搜索代码/名称/拼音首字母..."
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

      <!-- 搜索结果 -->
      <template v-if="searchMode && searchSubmitted">
        <view v-if="searchLoading" class="empty-state">
          <text class="empty-text">搜索中...</text>
        </view>
        <view v-else-if="searchMessage" class="empty-state">
          <text class="empty-text">{{ searchMessage }}</text>
        </view>
        <template v-else-if="searchList.length > 0">
          <view class="info-bar">
            <text class="info-date">找到 {{ searchList.length }} 条结果</text>
          </view>
          <view class="table-header">
            <text class="th th-rank">#</text>
            <text class="th th-name">名称/代码</text>
            <text class="th th-close">收盘价</text>
            <text class="th th-pct">涨跌幅</text>
            <text class="th th-rs">RS</text>
          </view>
          <view class="stock-list">
            <view
              v-for="(item, idx) in searchList"
              :key="item.ts_code"
              class="stock-row"
              :class="{ 'stock-row-alt': idx % 2 === 1 }"
            >
              <view class="col col-rank"><text class="rank-num">{{ idx + 1 }}</text></view>
              <view class="col col-name">
                <text class="stock-name">{{ item.name }}</text>
                <text class="stock-code">{{ item.ts_code }}</text>
              </view>
              <view class="col col-close"><text class="close-price">{{ formatPrice(item.close) }}</text></view>
              <view class="col col-pct">
                <view class="change-badge" :class="changeClass(item.pct_change)">
                  <text class="change-text">{{ formatPct(item.pct_change) }}</text>
                </view>
                <text class="change-abs">{{ formatChange(item.change) }}</text>
              </view>
              <view class="col col-rs">
                <view class="rs-badge" :class="rsClass(item.rs_rating)">
                  <text class="rs-value">{{ item.rs_rating }}</text>
                </view>
              </view>
            </view>
          </view>
        </template>
      </template>

      <!-- RS 排行榜 -->
      <template v-if="!searchMode">
        <view class="info-bar">
          <text class="info-date">数据日期: {{ dataDate || '--' }}</text>
          <view v-if="isTrading" class="trading-badge">
            <text class="trading-dot">●</text>
            <text class="trading-text">盘中</text>
          </view>
        </view>
        <view class="table-header">
          <text class="th th-rank">#</text>
          <text class="th th-name">名称/代码</text>
          <text class="th th-close">收盘价</text>
          <text class="th th-pct">涨跌幅</text>
          <text class="th th-rs">RS</text>
        </view>
        <view v-if="loading" class="empty-state">
          <text class="empty-text">加载中...</text>
        </view>
        <view v-else-if="stockList.length === 0" class="empty-state">
          <text class="empty-text">暂无数据</text>
        </view>
        <view v-else class="stock-list">
          <view
            v-for="(item, idx) in stockList"
            :key="item.ts_code"
            class="stock-row"
            :class="{ 'stock-row-alt': idx % 2 === 1 }"
          >
            <view class="col col-rank"><text class="rank-num" :class="rankClass(idx)">{{ idx + 1 }}</text></view>
            <view class="col col-name">
              <text class="stock-name">{{ item.name }}</text>
              <text class="stock-code">{{ item.ts_code }}</text>
            </view>
            <view class="col col-close"><text class="close-price">{{ formatPrice(item.close) }}</text></view>
            <view class="col col-pct">
              <view class="change-badge" :class="changeClass(item.pct_change)">
                <text class="change-text">{{ formatPct(item.pct_change) }}</text>
              </view>
              <text class="change-abs">{{ formatChange(item.change) }}</text>
            </view>
            <view class="col col-rs">
              <view class="rs-badge" :class="rsClass(item.rs_rating)">
                <text class="rs-value">{{ item.rs_rating }}</text>
              </view>
            </view>
          </view>
        </view>
      </template>
    </template>

    <!-- ═══════════════════════════════════════════════════════
         模拟仓 Tab
         ═══════════════════════════════════════════════════════ -->
    <template v-if="activeTab === 'sandbox'">
      <!-- 净值概览卡 -->
      <view class="sb-hero-card">
        <view class="sb-hero-top">
          <text class="sb-hero-since">成立于 2026.02.24</text>
        </view>
        <view class="sb-hero-body">
          <view class="sb-hero-left">
            <text class="sb-nav-big" :class="sbSummary.total_pnl >= 0 ? '' : 'sb-nav-down'">
              {{ sbSummary.latest_nav?.toFixed(4) || '1.0000' }}
            </text>
            <text class="sb-nav-sub">当前单位净值</text>
          </view>
        </view>
        <!-- 圆滑净值曲线 SVG -->
        <view v-if="navSeries.length > 1" class="sb-nav-chart">
          <view class="sb-nav-chart-inner" :style="{ height: '160rpx' }">
            <!-- #ifdef H5 -->
            <svg xmlns="http://www.w3.org/2000/svg" :viewBox="`0 0 ${navChartWidth} ${navChartHeight}`" class="sb-svg-chart">
              <defs>
                <linearGradient id="navFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" :stop-color="navTrendColor" stop-opacity="0.2" />
                  <stop offset="100%" :stop-color="navTrendColor" stop-opacity="0.02" />
                </linearGradient>
              </defs>
              <!-- 面积填充 -->
              <path :d="navAreaPath" fill="url(#navFill)" />
              <!-- 曲线 -->
              <path :d="navCurvePath" fill="none" :stroke="navTrendColor" stroke-width="2" stroke-linecap="round" />
              <!-- 基准线 -->
              <line x1="0" :y1="navBaseY" :x2="navChartWidth" :y2="navBaseY" stroke="#d0d0d8" stroke-width="0.5" stroke-dasharray="4,3" />
            </svg>
            <!-- #endif -->
          </view>
        </view>
        <!-- 收益率指标行 -->
        <view class="sb-metric-row">
          <view class="sb-metric-item">
            <text class="sb-metric-label">成立以来</text>
            <text class="sb-metric-val" :class="pnlClass(sbSummary.pnl_since_inception)">
              {{ formatPnlVal(sbSummary.pnl_since_inception) }}
            </text>
          </view>
          <view class="sb-metric-item">
            <text class="sb-metric-label">近一年</text>
            <text class="sb-metric-val" :class="pnlClass(sbSummary.pnl_1y)">
              {{ formatPnlVal(sbSummary.pnl_1y) }}
            </text>
          </view>
          <view class="sb-metric-item">
            <text class="sb-metric-label">近三月</text>
            <text class="sb-metric-val" :class="pnlClass(sbSummary.pnl_3m)">
              {{ formatPnlVal(sbSummary.pnl_3m) }}
            </text>
          </view>
          <view class="sb-metric-item">
            <text class="sb-metric-label">今年以来</text>
            <text class="sb-metric-val" :class="pnlClass(sbSummary.pnl_ytd)">
              {{ formatPnlVal(sbSummary.pnl_ytd) }}
            </text>
          </view>
        </view>
      </view>

      <!-- 观察池快照 -->
      <view class="sb-snapshot">
        <view class="sb-snapshot-header">
          <text class="sb-snapshot-title">观察池快照 ({{ sbSummary.total_active || 0 }}支)</text>
          <text class="sb-snapshot-time">{{ sbSummary.latest_date || '' }}</text>
        </view>
        <view class="sb-snapshot-tags">
          <view
            class="sb-tag sb-tag-retain"
            :class="{ 'sb-tag-active': sbFilter === 'retain' }"
            @click="toggleDisciplineFilter('retain')"
          >
            <text class="sb-tag-label">留存 Retain</text>
            <text class="sb-tag-num">{{ sbSummary.retain_count || 0 }}支</text>
          </view>
          <view
            class="sb-tag sb-tag-gray"
            :class="{ 'sb-tag-active': sbFilter === 'gray' }"
            @click="toggleDisciplineFilter('gray')"
          >
            <text class="sb-tag-label">灰度 Gray</text>
            <text class="sb-tag-num">{{ sbSummary.gray_count || 0 }}支</text>
          </view>
          <view
            class="sb-tag sb-tag-research"
            :class="{ 'sb-tag-active': sbFilter === 'research' }"
            @click="toggleDisciplineFilter('research')"
          >
            <text class="sb-tag-label">用研 Research</text>
            <text class="sb-tag-num">{{ sbSummary.research_count || 0 }}支</text>
          </view>
          <view
            class="sb-tag sb-tag-churn"
            :class="{ 'sb-tag-active': sbFilter === 'churn' }"
            @click="toggleDisciplineFilter('churn')"
          >
            <text class="sb-tag-label">流失 Churn</text>
            <text class="sb-tag-num">{{ sbSummary.churn_count || 0 }}支</text>
          </view>
        </view>
      </view>

      <!-- 加载 / 空态 -->
      <view v-if="sbLoading" class="empty-state">
        <text class="empty-text">加载中...</text>
      </view>
      <view v-else-if="sbStocks.length === 0" class="empty-state" style="border-radius: 16rpx; margin-top: 12rpx;">
        <text class="empty-text">暂无数据</text>
      </view>

      <!-- 股票列表 -->
      <view v-else class="sb-stock-list">
        <view
          v-for="item in sbStocks"
          :key="item.id"
          class="sb-stock-card"
          @click="goToDetail(item.id)"
        >
          <!-- 头部: 名称 + 状态 -->
          <view class="sb-card-top">
            <view class="sb-card-name-row">
              <text class="sb-stock-name">{{ item.name }}</text>
              <text class="sb-stock-code">（{{ item.ts_code }}）</text>
            </view>
            <view class="sb-status-badge" :class="'sb-status-' + (item.latest_analysis ? item.latest_analysis.discipline_action : 'retain')">
              <text class="sb-status-text">{{ disciplineLabel(item.latest_analysis ? item.latest_analysis.discipline_action : 'retain') }}</text>
            </view>
          </view>

          <!-- 推演摘要 -->
          <template v-if="item.latest_analysis">
            <!-- 评分 -->
            <view class="sb-score-row">
              <text class="sb-score-label">综合评分：</text>
              <text class="sb-score-big" :class="scoreClass(item.latest_analysis.score)">{{ item.latest_analysis.score.toFixed(1) }}</text>
              <text class="sb-score-max">/ 5.0</text>
            </view>

            <!-- 哨子 Verdict -->
            <text class="sb-verdict">{{ item.latest_analysis.verdict }}</text>

            <!-- 动作标签 + 风控 -->
            <view class="sb-action-row">
              <view class="sb-disc-badge" :class="'sb-disc-' + item.latest_analysis.discipline_action">
                <text class="sb-disc-text">{{ disciplineLabel(item.latest_analysis.discipline_action) }}</text>
              </view>
              <text class="sb-analysis-date">{{ formatShortDate(item.latest_analysis.created_at) }}</text>
            </view>
          </template>

          <view v-if="item.net_shares > 0" class="sb-card-bottom">
            <text class="sb-shares">持仓 {{ item.net_shares }} 股</text>
          </view>

          <view class="sb-card-arrow">
            <text class="arrow-icon">›</text>
          </view>
        </view>
      </view>
    </template>

    <!-- Footer -->
    <view class="site-footer">
      <text class="footer-icp" @click="onOpenIcp">蜀ICP备2026006985号</text>
      <text class="footer-copy">© 2026 Rick</text>
    </view>
  </view>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { fetchRSRating, searchStocks, fetchSandboxOverview, fetchSandboxStocks as apiFetchSandboxStocks } from '@/utils/api'

const activeTab = ref('rs')

// ═══════════════════════════════════════════════════════
// RS Rating
// ═══════════════════════════════════════════════════════

const stockList = ref([])
const dataDate = ref('')
const loading = ref(true)
const descExpanded = ref(false)

const searchMode = ref(false)
const searchFocused = ref(false)
const searchQuery = ref('')
const searchSubmitted = ref(false)
const searchList = ref([])
const searchLoading = ref(false)
const searchMessage = ref('')

const isTrading = computed(() => {
  const now = new Date()
  const day = now.getDay()
  if (day === 0 || day === 6) return false
  const h = now.getHours()
  const m = now.getMinutes()
  const t = h * 60 + m
  return t >= 570 && t <= 900
})

onMounted(async () => {
  try {
    const data = await fetchRSRating({ min_rating: 80, top_n: 5000 })
    stockList.value = data.items || []
    dataDate.value = data.date || ''
  } catch (e) {
    console.error('加载 RS Rating 失败:', e)
    uni.showToast({ title: '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
})

const onSearchFocus = () => { searchFocused.value = true; searchMode.value = true }
const onSearchInput = (e) => { searchQuery.value = e.detail.value; searchSubmitted.value = false; searchMessage.value = '' }
const onSearchConfirm = () => { if (searchQuery.value.trim()) doSearch() }
const onClearSearch = () => { searchQuery.value = ''; searchSubmitted.value = false; searchList.value = []; searchMessage.value = '' }
const onExitSearch = () => { searchMode.value = false; searchFocused.value = false; onClearSearch() }

const doSearch = async () => {
  const q = searchQuery.value.trim()
  if (!q) return
  searchSubmitted.value = true
  searchLoading.value = true
  searchList.value = []
  searchMessage.value = ''
  try {
    const data = await searchStocks({ q })
    searchList.value = data.items || []
    searchMessage.value = data.message || ''
  } catch (e) {
    console.error('搜索失败:', e)
    uni.showToast({ title: '搜索失败', icon: 'none' })
  } finally {
    searchLoading.value = false
  }
}

const formatPrice = (v) => v == null ? '--' : Number(v).toFixed(2)
const formatPct = (v) => {
  if (v == null) return '--'
  const n = Number(v)
  return (n >= 0 ? '+' : '') + n.toFixed(2) + '%'
}
const formatChange = (v) => {
  if (v == null) return ''
  const n = Number(v)
  return (n >= 0 ? '+' : '') + n.toFixed(2)
}
const changeClass = (v) => v == null ? 'change-flat' : v > 0 ? 'change-up' : v < 0 ? 'change-down' : 'change-flat'
const rankClass = (idx) => idx < 3 ? 'rank-top' : idx < 10 ? 'rank-high' : ''
const rsClass = (rating) => rating >= 90 ? 'rs-hot' : rating >= 70 ? 'rs-warm' : rating >= 50 ? 'rs-normal' : 'rs-cool'

// ═══════════════════════════════════════════════════════
// 模拟仓
// ═══════════════════════════════════════════════════════

const sbLoading = ref(false)
const sbStocks = ref([])
const sbSummary = ref({})
const navSeries = ref([])
const sbFilter = ref('')
let sbLoaded = false

const statusLabel = (s) => ({ holding: '持仓', watching: '观察', exited: '退出' }[s] || s)

const disciplineLabel = (d) => ({ retain: '留存', gray: '灰度', research: '用研', churn: '流失' }[d] || d)

const scoreClass = (score) => {
  if (score >= 4) return 'sb-score-high'
  if (score >= 2.5) return 'sb-score-mid'
  return 'sb-score-low'
}

const formatShortDate = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()}`
}

const pnlClass = (v) => {
  const n = v || 0
  return n > 0 ? 'metric-up' : n < 0 ? 'metric-down' : 'metric-neutral'
}

const formatPnlVal = (v) => {
  const n = v || 0
  return (n >= 0 ? '+' : '') + n.toFixed(2) + '%'
}

const toggleDisciplineFilter = (action) => {
  sbFilter.value = sbFilter.value === action ? '' : action
  loadSandboxStocks()
}

const switchToSandbox = () => {
  activeTab.value = 'sandbox'
  if (!sbLoaded) {
    sbLoaded = true
    loadSandboxData()
  }
}

const loadSandboxData = async () => {
  sbLoading.value = true
  try {
    const [overview, stocks] = await Promise.all([
      fetchSandboxOverview(90),
      apiFetchSandboxStocks('', sbFilter.value),
    ])
    sbSummary.value = overview.summary || {}
    navSeries.value = overview.nav_series || []
    sbStocks.value = stocks.items || []
  } catch (e) {
    console.error('加载模拟仓失败:', e)
  } finally {
    sbLoading.value = false
  }
}

const loadSandboxStocks = async () => {
  try {
    const data = await apiFetchSandboxStocks('', sbFilter.value)
    sbStocks.value = data.items || []
  } catch (e) {
    console.error(e)
  }
}

// 净值 SVG 曲线计算
const navChartWidth = 400
const navChartHeight = 100

const navTrendColor = computed(() => {
  const series = navSeries.value
  if (series.length < 2) return '#3b82f6'
  return series[series.length - 1].nav >= 1.0 ? '#3b82f6' : '#22c55e'
})

const navSvgPoints = computed(() => {
  const series = navSeries.value
  if (series.length < 2) return []
  const navs = series.map(s => s.nav)
  const min = Math.min(...navs, 1) - 0.005
  const max = Math.max(...navs, 1) + 0.005
  const range = max - min || 1
  const pad = 4
  return series.map((s, i) => ({
    x: pad + (i / (series.length - 1)) * (navChartWidth - pad * 2),
    y: pad + (1 - (s.nav - min) / range) * (navChartHeight - pad * 2),
  }))
})

const navBaseY = computed(() => {
  const series = navSeries.value
  if (series.length < 2) return navChartHeight / 2
  const navs = series.map(s => s.nav)
  const min = Math.min(...navs, 1) - 0.005
  const max = Math.max(...navs, 1) + 0.005
  const pad = 4
  return pad + (1 - (1.0 - min) / (max - min || 1)) * (navChartHeight - pad * 2)
})

// Catmull-Rom → SVG cubic Bezier 平滑曲线
const navCurvePath = computed(() => {
  const pts = navSvgPoints.value
  if (pts.length < 2) return ''
  if (pts.length === 2) return `M${pts[0].x},${pts[0].y} L${pts[1].x},${pts[1].y}`

  let d = `M${pts[0].x},${pts[0].y}`
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(i - 1, 0)]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[Math.min(i + 2, pts.length - 1)]
    const t = 0.3
    const cp1x = p1.x + (p2.x - p0.x) * t
    const cp1y = p1.y + (p2.y - p0.y) * t
    const cp2x = p2.x - (p3.x - p1.x) * t
    const cp2y = p2.y - (p3.y - p1.y) * t
    d += ` C${cp1x.toFixed(1)},${cp1y.toFixed(1)} ${cp2x.toFixed(1)},${cp2y.toFixed(1)} ${p2.x.toFixed(1)},${p2.y.toFixed(1)}`
  }
  return d
})

const navAreaPath = computed(() => {
  const curve = navCurvePath.value
  if (!curve) return ''
  const pts = navSvgPoints.value
  return `${curve} L${pts[pts.length - 1].x},${navChartHeight} L${pts[0].x},${navChartHeight} Z`
})

const goToDetail = (id) => {
  uni.navigateTo({ url: `/pages/stocks/detail?id=${id}` })
}

const onOpenIcp = () => {
  // #ifdef H5
  window.open('https://beian.miit.gov.cn/', '_blank')
  // #endif
}
</script>

<style scoped>
.stocks-container {
  min-height: 100vh;
  background: #f0f2f5;
  padding: 0 24rpx;
}

/* ── Tab Bar ── */
.tab-bar {
  display: flex;
  gap: 0;
  background: #ffffff;
  border-radius: 12rpx;
  margin: 16rpx 0 12rpx;
  padding: 4rpx;
  box-shadow: 0 1rpx 8rpx rgba(0, 0, 0, 0.04);
}
.tab-item {
  flex: 1;
  padding: 16rpx 0;
  text-align: center;
  border-radius: 10rpx;
  transition: all 0.2s;
  cursor: pointer;
}
.tab-active {
  background: #1a1a2e;
}
.tab-text {
  font-size: 28rpx;
  font-weight: 600;
  color: #8c8c9a;
}
.tab-active .tab-text {
  color: #ffffff;
}

/* ── Header ── */
.stocks-header {
  padding: 28rpx 0 16rpx;
}
.stocks-title {
  font-size: 44rpx;
  font-weight: 800;
  color: #1a1a2e;
  letter-spacing: 1rpx;
  display: block;
  font-family: 'SF Pro Display', 'PingFang SC', -apple-system, sans-serif;
}
.stocks-subtitle {
  font-size: 24rpx;
  color: #8c8c9a;
  margin-top: 6rpx;
  letter-spacing: 1rpx;
  display: block;
}

/* ── Search Bar ── */
.search-bar {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin: 12rpx 0 8rpx;
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
.search-icon { font-size: 28rpx; margin-right: 12rpx; flex-shrink: 0; }
.search-input {
  flex: 1;
  font-size: 28rpx;
  color: #1a1a2e;
  background: transparent;
  border: none;
  outline: none;
  line-height: 1.4;
}
.search-clear { padding: 4rpx 8rpx; margin-left: 8rpx; flex-shrink: 0; cursor: pointer; }
.search-clear-icon { font-size: 32rpx; color: #b0b0be; font-weight: 500; }
.search-cancel { flex-shrink: 0; padding: 8rpx 4rpx; cursor: pointer; }
.search-cancel-text { font-size: 28rpx; color: #4285f4; font-weight: 500; }

/* ── RS Description ── */
.rs-desc {
  margin-top: 12rpx;
  padding: 16rpx 20rpx;
  background: rgba(140, 140, 154, 0.06);
  border-radius: 12rpx;
  overflow: hidden;
  max-height: 80rpx;
  transition: max-height 0.3s ease;
  position: relative;
}
.rs-desc::after {
  content: '...点击展开';
  position: absolute;
  bottom: 0; right: 0;
  padding: 0 20rpx 0 40rpx;
  background: linear-gradient(90deg, transparent, rgba(240, 242, 245, 1) 40%);
  font-size: 20rpx; color: #8c8c9a; line-height: 40rpx;
}
.rs-desc-expanded { max-height: 600rpx; }
.rs-desc-expanded::after { display: none; }
.rs-desc-text { font-size: 22rpx; color: #8c8c9a; line-height: 1.7; display: block; }

/* ── Info Bar ── */
.info-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12rpx 0 16rpx;
}
.info-date { font-size: 24rpx; color: #8c8c9a; }
.trading-badge {
  display: flex;
  align-items: center;
  gap: 6rpx;
  padding: 4rpx 16rpx;
  background: rgba(255, 59, 48, 0.08);
  border-radius: 20rpx;
}
.trading-dot { font-size: 16rpx; color: #ff3b30; animation: pulse 1.5s infinite; }
.trading-text { font-size: 22rpx; color: #ff3b30; font-weight: 500; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

/* ── Table Header ── */
.table-header {
  display: flex;
  align-items: center;
  padding: 18rpx 20rpx;
  background: #ffffff;
  border-radius: 16rpx 16rpx 0 0;
  border-bottom: 2rpx solid #f0f0f2;
}
.th { font-size: 22rpx; color: #8c8c9a; font-weight: 600; }
.th-rank { width: 60rpx; text-align: center; }
.th-name { flex: 1; padding-left: 12rpx; }
.th-close { width: 140rpx; text-align: right; }
.th-pct { width: 160rpx; text-align: right; }
.th-rs { width: 80rpx; text-align: center; }

/* ── Stock List ── */
.stock-list {
  background: #ffffff;
  border-radius: 0 0 16rpx 16rpx;
  overflow: hidden;
  box-shadow: 0 2rpx 16rpx rgba(0, 0, 0, 0.04);
}
.stock-row {
  display: flex;
  align-items: center;
  padding: 22rpx 20rpx;
  border-bottom: 1rpx solid #f8f8fa;
}
.stock-row-alt { background: #fafbfc; }
.stock-row:last-child { border-bottom: none; }
.col { display: flex; flex-direction: column; justify-content: center; }
.col-rank { width: 60rpx; align-items: center; }
.col-name { flex: 1; padding-left: 12rpx; }
.col-close { width: 140rpx; align-items: flex-end; }
.col-pct { width: 160rpx; align-items: flex-end; }
.col-rs { width: 80rpx; align-items: center; }

.rank-num {
  font-size: 24rpx; color: #8c8c9a; font-weight: 600;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.rank-top { color: #ff3b30; font-weight: 800; }
.rank-high { color: #ff9500; font-weight: 700; }

.stock-name {
  font-size: 28rpx; font-weight: 600; color: #1a1a2e; line-height: 1.3;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.stock-code { font-size: 22rpx; color: #b0b0be; margin-top: 4rpx; font-family: 'SF Mono', 'Menlo', monospace; }

.close-price {
  font-size: 28rpx; font-weight: 600; color: #1a1a2e;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}

.change-badge {
  padding: 4rpx 14rpx; border-radius: 8rpx;
  display: inline-flex; align-items: center; justify-content: center;
}
.change-text {
  font-size: 24rpx; font-weight: 600;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.change-up { background: rgba(255, 59, 48, 0.1); }
.change-up .change-text { color: #ff3b30; }
.change-down { background: rgba(52, 199, 89, 0.1); }
.change-down .change-text { color: #34c759; }
.change-flat { background: rgba(142, 142, 147, 0.1); }
.change-flat .change-text { color: #8e8e93; }
.change-abs { font-size: 20rpx; color: #b0b0be; margin-top: 2rpx; text-align: right; }

.rs-badge {
  width: 60rpx; height: 44rpx; border-radius: 10rpx;
  display: flex; align-items: center; justify-content: center;
}
.rs-value {
  font-size: 24rpx; font-weight: 700; color: #ffffff;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.rs-hot { background: linear-gradient(135deg, #ff3b30, #ff6b5a); }
.rs-warm { background: linear-gradient(135deg, #ff9500, #ffb340); }
.rs-normal { background: linear-gradient(135deg, #f0b429, #d4981e); }
.rs-cool { background: linear-gradient(135deg, #8e8e93, #a8a8ae); }

/* ── Empty State ── */
.empty-state {
  display: flex; justify-content: center; align-items: center;
  padding: 120rpx 0; background: #ffffff; border-radius: 0 0 16rpx 16rpx;
}
.empty-text { font-size: 28rpx; color: #b0b0be; }

/* ═══════════════════════════════════════════════════════
   模拟仓样式
   ═══════════════════════════════════════════════════════ */

/* ── 净值概览卡 ── */
.sb-hero-card {
  background: #ffffff;
  border-radius: 20rpx;
  padding: 28rpx 28rpx 24rpx;
  margin: 16rpx 0 0;
  box-shadow: 0 2rpx 16rpx rgba(0, 0, 0, 0.05);
}
.sb-hero-top { margin-bottom: 8rpx; }
.sb-hero-since {
  font-size: 22rpx; color: #8c8c9a; font-weight: 500;
}
.sb-hero-body {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 24rpx;
}
.sb-hero-left { display: flex; flex-direction: column; }
.sb-nav-big {
  font-size: 64rpx; font-weight: 900; color: #1a1a2e; line-height: 1.1;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
  letter-spacing: -1rpx;
}
.sb-nav-down { color: #22c55e; }
.sb-nav-sub {
  font-size: 22rpx; color: #8c8c9a; margin-top: 6rpx; font-weight: 500;
}

/* 迷你净值曲线 → SVG 圆滑曲线 */
.sb-nav-chart {
  margin: 16rpx 0 24rpx;
}
.sb-nav-chart-inner {
  width: 100%; position: relative; overflow: hidden; border-radius: 12rpx;
  background: #fafbfc;
}
.sb-svg-chart {
  width: 100%; height: 100%; display: block;
}

/* 指标行 */
.sb-metric-row {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12rpx;
}
.sb-metric-item {
  background: #f5f7fa; border-radius: 14rpx;
  padding: 18rpx 20rpx;
  display: flex; flex-direction: column; gap: 4rpx;
}
.sb-metric-label { font-size: 22rpx; color: #8c8c9a; font-weight: 500; }
.sb-metric-val {
  font-size: 32rpx; font-weight: 800;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.metric-up { color: #ef4444; }
.metric-down { color: #22c55e; }
.metric-neutral { color: #1a1a2e; }

/* ── 观察池快照 ── */
.sb-snapshot {
  margin-top: 24rpx; padding: 0 4rpx;
}
.sb-snapshot-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 16rpx;
}
.sb-snapshot-title { font-size: 30rpx; font-weight: 700; color: #1a1a2e; }
.sb-snapshot-time { font-size: 22rpx; color: #b0b0be; }
.sb-snapshot-tags {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12rpx;
}
.sb-tag {
  border-radius: 16rpx; padding: 20rpx 16rpx;
  display: flex; flex-direction: column; align-items: center; gap: 6rpx;
  cursor: pointer; transition: all 0.2s; border: 2rpx solid transparent;
}
.sb-tag-active { border-color: #1a1a2e; box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.1); }
.sb-tag-label { font-size: 22rpx; font-weight: 600; }
.sb-tag-num {
  font-size: 36rpx; font-weight: 800;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.sb-tag-retain { background: #eff6ff; }
.sb-tag-retain .sb-tag-label { color: #3b82f6; }
.sb-tag-retain .sb-tag-num { color: #1a1a2e; }
.sb-tag-gray { background: #f3f4f6; }
.sb-tag-gray .sb-tag-label { color: #6b7280; }
.sb-tag-gray .sb-tag-num { color: #1a1a2e; }
.sb-tag-research { background: #faf5ff; }
.sb-tag-research .sb-tag-label { color: #a855f7; }
.sb-tag-research .sb-tag-num { color: #1a1a2e; }
.sb-tag-churn { background: #fef2f2; }
.sb-tag-churn .sb-tag-label { color: #ef4444; }
.sb-tag-churn .sb-tag-num { color: #1a1a2e; }

/* ── 股票卡片 ── */
.sb-stock-list { margin-top: 16rpx; }
.sb-stock-card {
  background: #ffffff;
  border-radius: 16rpx;
  padding: 24rpx;
  margin-bottom: 16rpx;
  box-shadow: 0 1rpx 8rpx rgba(0, 0, 0, 0.04);
  position: relative;
  cursor: pointer;
  transition: box-shadow 0.15s;
}
.sb-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16rpx;
  padding-bottom: 14rpx;
  border-bottom: 1rpx solid #f0f0f2;
}
.sb-card-name-row {
  display: flex; align-items: baseline; gap: 4rpx;
}
.sb-stock-name { font-size: 32rpx; font-weight: 800; color: #1a1a2e; }
.sb-stock-code { font-size: 24rpx; color: #8c8c9a; font-weight: 500; }

.sb-status-badge {
  padding: 6rpx 16rpx;
  border-radius: 16rpx;
  display: inline-flex;
}
.sb-status-text { font-size: 22rpx; font-weight: 600; }
.sb-status-retain { background: #dbeafe; }
.sb-status-retain .sb-status-text { color: #2563eb; }
.sb-status-gray { background: #f3f4f6; }
.sb-status-gray .sb-status-text { color: #6b7280; }
.sb-status-research { background: #f3e8ff; }
.sb-status-research .sb-status-text { color: #9333ea; }
.sb-status-churn { background: #fef2f2; }
.sb-status-churn .sb-status-text { color: #dc2626; }

/* 评分 */
.sb-score-row {
  display: flex; align-items: baseline; gap: 6rpx; margin-bottom: 10rpx;
}
.sb-score-label { font-size: 24rpx; color: #8c8c9a; font-weight: 500; }
.sb-score-big {
  font-size: 42rpx; font-weight: 900;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.sb-score-high { color: #1a1a2e; }
.sb-score-mid { color: #f59e0b; }
.sb-score-low { color: #ef4444; }
.sb-score-max { font-size: 24rpx; color: #b0b0be; font-weight: 500; }

/* Verdict */
.sb-verdict {
  font-size: 26rpx; color: #4a4a5a; line-height: 1.6; display: block;
  margin-bottom: 12rpx;
}

/* 动作标签行 */
.sb-action-row {
  display: flex; align-items: center; gap: 10rpx;
}
.sb-disc-badge { padding: 4rpx 14rpx; border-radius: 8rpx; }
.sb-disc-text { font-size: 22rpx; font-weight: 600; }
.sb-disc-retain { background: rgba(59, 130, 246, 0.1); }
.sb-disc-retain .sb-disc-text { color: #3b82f6; }
.sb-disc-gray { background: rgba(142, 142, 147, 0.1); }
.sb-disc-gray .sb-disc-text { color: #8e8e93; }
.sb-disc-research { background: rgba(168, 85, 247, 0.1); }
.sb-disc-research .sb-disc-text { color: #a855f7; }
.sb-disc-churn { background: rgba(239, 68, 68, 0.1); }
.sb-disc-churn .sb-disc-text { color: #ef4444; }
.sb-analysis-date { font-size: 22rpx; color: #b0b0be; }

.sb-card-bottom { margin-top: 10rpx; }
.sb-shares { font-size: 22rpx; color: #8c8c9a; }

.sb-card-arrow {
  position: absolute;
  right: 24rpx;
  top: 50%;
  transform: translateY(-50%);
}
.arrow-icon { font-size: 36rpx; color: #d0d0d8; font-weight: 300; }

/* ── Footer ── */
.site-footer {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 48rpx 0 72rpx;
  gap: 8rpx;
}
.footer-icp { font-size: 22rpx; color: #b0b0be; text-decoration: underline; }
.footer-copy { font-size: 22rpx; color: #b0b0be; }

/* ═══════════════════════════════════════════════════════════
   PC / Tablet 适配 (≥768px)
   ═══════════════════════════════════════════════════════════ */
@media screen and (min-width: 768px) {
  .stocks-container {
    max-width: 860px;
    margin: 0 auto;
    padding: 0 24px;
  }

  /* Tab Bar */
  .tab-bar { margin: 12px 0 8px; padding: 3px; border-radius: 8px; }
  .tab-item { padding: 10px 0; border-radius: 7px; }
  .tab-text { font-size: 15px; }

  .stocks-header { padding: 24px 0 12px; }
  .stocks-title { font-size: 26px; letter-spacing: 0.5px; }
  .stocks-subtitle { font-size: 13px; margin-top: 4px; }

  .search-bar { margin: 8px 0 8px; gap: 10px; }
  .search-input-wrap { border-radius: 22px; padding: 10px 18px; border-width: 1px; }
  .search-icon { font-size: 15px; margin-right: 8px; }
  .search-input { font-size: 15px; }
  .search-clear-icon { font-size: 18px; }
  .search-cancel-text { font-size: 15px; }
  .search-input-wrap:hover { border-color: #c0c0cc; }
  .search-bar-focus .search-input-wrap:hover { border-color: #4285f4; }

  .rs-desc { margin-top: 8px; padding: 10px 14px; border-radius: 8px; max-height: 40px; }
  .rs-desc::after { padding: 0 14px 0 30px; font-size: 11px; line-height: 20px; }
  .rs-desc-expanded { max-height: 300px; }
  .rs-desc-text { font-size: 12px; }

  .info-bar { padding: 8px 0 12px; }
  .info-date { font-size: 13px; }
  .trading-badge { gap: 4px; padding: 2px 10px; border-radius: 12px; }
  .trading-dot { font-size: 9px; }
  .trading-text { font-size: 12px; }

  .table-header { padding: 12px 16px; border-radius: 12px 12px 0 0; border-bottom-width: 1px; }
  .th { font-size: 12px; }
  .th-rank { width: 36px; }
  .th-name { padding-left: 8px; }
  .th-close { width: 90px; }
  .th-pct { width: 110px; }
  .th-rs { width: 50px; }

  .stock-list { border-radius: 0 0 12px 12px; box-shadow: 0 1px 12px rgba(0, 0, 0, 0.05); }
  .stock-row { padding: 14px 16px; transition: background-color 0.15s; }
  .stock-row:hover { background-color: #f5f7fa; }

  .col-rank { width: 36px; }
  .col-name { padding-left: 8px; }
  .col-close { width: 90px; }
  .col-pct { width: 110px; }
  .col-rs { width: 50px; }

  .rank-num { font-size: 13px; }
  .stock-name { font-size: 15px; }
  .stock-code { font-size: 12px; margin-top: 2px; }
  .close-price { font-size: 15px; }
  .change-badge { padding: 2px 10px; border-radius: 6px; }
  .change-text { font-size: 13px; }
  .change-abs { font-size: 11px; }
  .rs-badge { width: 38px; height: 26px; border-radius: 6px; }
  .rs-value { font-size: 13px; }

  /* 模拟仓 PC 适配 */
  .sb-hero-card { padding: 20px 22px 18px; border-radius: 14px; margin-top: 12px; }
  .sb-hero-since { font-size: 12px; }
  .sb-nav-big { font-size: 40px; }
  .sb-nav-sub { font-size: 12px; }
  .sb-mini-chart, .sb-nav-chart-inner { height: 100px !important; }
  .sb-nav-chart { margin: 10px 0 18px; }
  .sb-metric-row { gap: 8px; grid-template-columns: 1fr 1fr 1fr 1fr; }
  .sb-metric-item { padding: 12px 16px; border-radius: 10px; }
  .sb-metric-label { font-size: 12px; }
  .sb-metric-val { font-size: 18px; }

  .sb-snapshot { margin-top: 18px; }
  .sb-snapshot-title { font-size: 16px; }
  .sb-snapshot-time { font-size: 12px; }
  .sb-snapshot-tags { gap: 8px; grid-template-columns: 1fr 1fr 1fr 1fr; }
  .sb-tag { padding: 14px 12px; border-radius: 10px; }
  .sb-tag-label { font-size: 12px; }
  .sb-tag-num { font-size: 22px; }

  .sb-stock-list { margin-top: 12px; }
  .sb-stock-card { padding: 18px; margin-bottom: 10px; border-radius: 12px; transition: box-shadow 0.15s; }
  .sb-stock-card:hover { box-shadow: 0 2px 16px rgba(0, 0, 0, 0.08); }
  .sb-card-top { margin-bottom: 12px; padding-bottom: 10px; }
  .sb-stock-name { font-size: 17px; }
  .sb-stock-code { font-size: 13px; }
  .sb-status-badge { padding: 3px 10px; border-radius: 10px; }
  .sb-status-text { font-size: 12px; }
  .sb-score-label { font-size: 13px; }
  .sb-score-big { font-size: 26px; }
  .sb-score-max { font-size: 13px; }
  .sb-verdict { font-size: 14px; }
  .sb-disc-badge { padding: 2px 10px; border-radius: 5px; }
  .sb-disc-text { font-size: 12px; }
  .sb-analysis-date { font-size: 12px; }
  .sb-shares { font-size: 12px; }
  .arrow-icon { font-size: 22px; }

  .site-footer { padding: 32px 0 48px; gap: 6px; }
  .footer-icp { font-size: 12px; cursor: pointer; }
  .footer-icp:hover { color: #8c8c9a; }
  .footer-copy { font-size: 12px; }
}
</style>
