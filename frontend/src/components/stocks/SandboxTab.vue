<template>
  <view>
    <!-- 净值概览卡 -->
    <view class="sb-hero-card">
      <view class="sb-hero-top">
        <text class="sb-hero-since">成立于 2026.02.13</text>
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
            <path :d="navAreaPath" fill="url(#navFill)" />
            <path :d="navCurvePath" fill="none" :stroke="navTrendColor" stroke-width="2" stroke-linecap="round" />
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

    <!-- 持仓分布环状图 -->
    <view v-if="holdingsPie.length > 1" class="sb-pie-card">
      <view class="sb-pie-header">
        <text class="sb-pie-title">持仓分布</text>
        <text class="sb-pie-sub">仓位 {{ holdingsPositionPct }}%</text>
      </view>
      <view class="sb-pie-body">
        <!-- #ifdef H5 -->
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" class="sb-pie-svg">
          <circle cx="100" cy="100" r="70" fill="none" stroke="#f0f2f5" stroke-width="28" />
          <circle
            v-for="(seg, i) in pieSegments"
            :key="i"
            cx="100" cy="100" r="70"
            fill="none"
            :stroke="seg.color"
            stroke-width="28"
            :stroke-dasharray="seg.dash"
            :stroke-dashoffset="seg.offset"
            style="transition: stroke-dasharray 0.5s, stroke-dashoffset 0.5s"
          />
          <text x="100" y="94" text-anchor="middle" font-size="22" font-weight="800" fill="#1a1a2e">
            {{ sbSummary.holding_count || 0 }}
          </text>
          <text x="100" y="116" text-anchor="middle" font-size="11" fill="#8c8c9a">只持仓</text>
        </svg>
        <!-- #endif -->
        <view class="sb-pie-legend">
          <view
            v-for="(item, i) in holdingsPie"
            :key="i"
            class="sb-legend-item"
          >
            <view class="sb-legend-dot" :style="{ background: pieColors[i % pieColors.length] }"></view>
            <text class="sb-legend-name">{{ item.name }}</text>
            <text class="sb-legend-pct">{{ item.pct }}%</text>
          </view>
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
          :class="{ 'sb-tag-active': sbFilter === 'watching' }"
          @click="toggleStatusFilter('watching')"
        >
          <text class="sb-tag-label">观察中</text>
          <text class="sb-tag-num">{{ sbSummary.watching_count || 0 }}支</text>
        </view>
        <view
          class="sb-tag sb-tag-gray"
          :class="{ 'sb-tag-active': sbFilter === 'holding' }"
          @click="toggleStatusFilter('holding')"
        >
          <text class="sb-tag-label">持仓中</text>
          <text class="sb-tag-num">{{ sbSummary.holding_count || 0 }}支</text>
        </view>
      </view>

      <!-- 筛选 + 搜索栏 -->
      <view class="sb-filter-bar">
        <view
          class="sb-filter-chip"
          :class="{ 'sb-filter-chip-active': sbHoldingOnly }"
          @click="toggleHoldingOnly"
        >
          <text class="sb-filter-chip-text">持仓票</text>
        </view>
        <view class="sb-search-wrap">
          <text class="sb-search-icon">🔍</text>
          <input
            class="sb-search-input"
            type="text"
            placeholder="代码 / 名称"
            :value="sbSearchQuery"
            @input="onSbSearchInput"
            @confirm="onSbSearchConfirm"
          />
          <text v-if="sbSearchQuery" class="sb-search-clear" @click="onSbClearSearch">✕</text>
        </view>
      </view>
    </view>

    <!-- 加载 / 空态 -->
    <EmptyState v-if="sbLoading" text="加载中..." bg="var(--color-bg-card)" radius="16rpx" style="margin-top: 12rpx;" />
    <EmptyState v-else-if="sbStocks.length === 0" text="暂无数据" bg="var(--color-bg-card)" radius="16rpx" style="margin-top: 12rpx;" />

    <!-- 股票列表 -->
    <view v-else class="sb-stock-list">
      <view
        v-for="item in sbStocks"
        :key="item.id"
        class="sb-stock-card"
        :class="{ 'sb-card-highlight': isHoldingRetain(item) }"
        @click="goToDetail(item.id)"
      >
        <view v-if="isHoldingRetain(item)" class="sb-highlight-bar">
          <text class="sb-highlight-icon">●</text>
          <text class="sb-highlight-text">持仓中</text>
        </view>

        <view class="sb-card-top">
          <view class="sb-card-name-row">
            <text class="sb-stock-name">{{ item.name }}</text>
            <text class="sb-stock-code">（{{ item.ts_code }}）</text>
          </view>
          <view class="sb-status-badge" :class="'sb-status-' + item.status">
            <text class="sb-status-text">{{ statusLabel(item.status) }}</text>
          </view>
        </view>

        <template v-if="item.latest_analysis">
          <view class="sb-score-row">
            <text class="sb-score-label">综合评分：</text>
            <text class="sb-score-big" :class="scoreClass(item.latest_analysis.score)">{{ item.latest_analysis.score.toFixed(1) }}</text>
            <text class="sb-score-max">/ 5.0</text>
          </view>
          <text class="sb-verdict">{{ item.latest_analysis.verdict }}</text>
          <view class="sb-action-row">
            <view class="sb-meta-info">
              <text class="sb-analysis-count">{{ item.analysis_count || 0 }}条记录</text>
              <text class="sb-analysis-dot">·</text>
              <text class="sb-analysis-date">{{ formatShortDate(item.analysis_latest_at || item.latest_analysis.created_at) }}</text>
            </view>
          </view>
        </template>

        <view v-if="item.position_pct > 0" class="sb-card-bottom">
          <view class="sb-position-bar-wrap">
            <view class="sb-position-bar" :style="{ width: item.position_pct + '%' }"></view>
          </view>
          <text class="sb-shares">持仓 {{ item.position_pct }}%</text>
        </view>

        <view class="sb-card-arrow">
          <text class="arrow-icon">›</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { fetchSandboxOverview, fetchSandboxStocks as apiFetchSandboxStocks } from '@/utils/api'
import { stockStatusLabel } from '@/utils/formatters'

const sbLoading = ref(false)
const sbStocks = ref([])
const sbSummary = ref({})
const navSeries = ref([])
const holdingsPie = ref([])
const sbFilter = ref('')
const sbHoldingOnly = ref(false)
const sbSearchQuery = ref('')

// 环状图配色
const pieColors = ['#3b82f6', '#f59e0b', '#22c55e', '#a855f7', '#ef4444', '#06b6d4', '#ec4899', '#8b5cf6', '#14b8a6', '#f97316', '#d0d0d8']

// 仓位百分比
const holdingsPositionPct = computed(() => {
  const data = holdingsPie.value
  if (!data || data.length === 0) return 0
  const cashItem = data.find(d => d.ts_code === '')
  const cashPct = cashItem ? cashItem.pct : 0
  return (100 - cashPct).toFixed(1)
})

// 环状图弧段计算
const pieSegments = computed(() => {
  const data = holdingsPie.value
  if (!data || data.length === 0) return []
  const circumference = 2 * Math.PI * 70
  const segments = []
  let accumulated = 0
  for (let i = 0; i < data.length; i++) {
    const arc = (data[i].pct / 100) * circumference
    segments.push({
      color: pieColors[i % pieColors.length],
      dash: `${arc} ${circumference - arc}`,
      offset: -(circumference * 0.25 + accumulated),
    })
    accumulated += arc
  }
  return segments
})

const statusLabel = stockStatusLabel

const isHoldingRetain = (item) => item.status === 'holding'

const scoreClass = (score) => {
  if (score >= 4) return 'sb-score-high'
  if (score >= 2.5) return 'sb-score-mid'
  return 'sb-score-low'
}

const formatShortDate = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const isToday = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
  if (isToday) return `今天 ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
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

const toggleStatusFilter = (status) => {
  sbFilter.value = sbFilter.value === status ? '' : status
  loadStocks()
}

const toggleHoldingOnly = () => {
  sbHoldingOnly.value = !sbHoldingOnly.value
  loadStocks()
}

const onSbSearchInput = (e) => { sbSearchQuery.value = e.detail.value }
const onSbSearchConfirm = () => { loadStocks() }
const onSbClearSearch = () => { sbSearchQuery.value = ''; loadStocks() }

const loadData = async () => {
  sbLoading.value = true
  try {
    const [overview, stocks] = await Promise.all([
      fetchSandboxOverview(90),
      apiFetchSandboxStocks('', sbFilter.value, sbSearchQuery.value, sbHoldingOnly.value),
    ])
    sbSummary.value = overview.summary || {}
    navSeries.value = overview.nav_series || []
    holdingsPie.value = overview.holdings_pie || []
    sbStocks.value = stocks.items || []
  } catch (e) {
    console.error('加载模拟仓失败:', e)
  } finally {
    sbLoading.value = false
  }
}

const loadStocks = async () => {
  try {
    const data = await apiFetchSandboxStocks('', sbFilter.value, sbSearchQuery.value, sbHoldingOnly.value)
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

const init = () => { loadData() }

defineExpose({ init })

onMounted(() => {
  init()
})
</script>
