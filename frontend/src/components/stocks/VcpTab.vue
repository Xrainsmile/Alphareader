<template>
  <view>
    <view class="stocks-header">
      <text class="stocks-title">VCP 策略</text>
      <text class="stocks-subtitle">波动收缩形态 · Volatility Contraction Pattern</text>
    </view>

    <view class="info-bar">
      <text class="info-date">数据日期: {{ vcpDate || '--' }}</text>
      <text class="info-date">共 {{ filteredList.length }}/{{ vcpList.length }} 只</text>
    </view>

    <IndustryConceptFilter
      ref="filterRef"
      :industry-options="industryOptions"
      :concept-options="conceptOptions"
      @change="onFilterChange"
    />

    <!-- VCP 表格头 -->
    <view class="vcp-table-header">
      <text class="vth vth-rank">#</text>
      <text class="vth vth-name">名称/代码</text>
      <text class="vth vth-price">收盘价</text>
      <text class="vth vth-vcp">VCP</text>
      <text class="vth vth-flow">资金流入</text>
      <text class="vth vth-action">交易</text>
    </view>

    <EmptyState v-if="vcpLoading" text="加载中..." bg="var(--color-bg-card)" radius="0 0 16rpx 16rpx" />
    <EmptyState v-else-if="filteredList.length === 0" :text="vcpList.length === 0 ? '暂无白名单数据' : '无匹配结果，请调整筛选条件'" bg="var(--color-bg-card)" radius="0 0 16rpx 16rpx" />
    <view v-else class="stock-list">
      <view
        v-for="(item, idx) in filteredList"
        :key="item.ts_code"
        class="vcp-row"
        :class="{ 'stock-row-alt': idx % 2 === 1 }"
        @click="onRowClick(item, idx)"
      >
        <!-- 主行第一行：核心指标 -->
        <view class="vcp-row-main">
          <view class="col vcp-col-rank"><text class="rank-num" :class="rankClass(idx)">{{ idx + 1 }}</text></view>
          <view class="col vcp-col-name">
            <view style="display: flex; align-items: center; gap: 4rpx;">
              <text class="stock-name">{{ item.name || item.ts_code }}</text>
              <text v-if="catalystMap[item.ts_code]" class="catalyst-fire" title="有新闻催化剂">🔥</text>
            </view>
            <text class="stock-code">{{ item.ts_code }}{{ item.industry ? ' · ' + item.industry : '' }}</text>
          </view>
          <view class="col vcp-col-price"><text class="close-price">{{ formatPrice(item.current_price) }}</text></view>
          <view class="col vcp-col-vcp">
            <view class="vcp-badge" :class="vcpClass(item.vcp_score)">
              <text class="vcp-val">{{ formatVcp(item.vcp_score) }}</text>
            </view>
          </view>
          <view class="col vcp-col-flow">
            <text class="flow-val" :class="pctValClass(item.fund_flow_net)">
              {{ item.fund_flow_net != null ? (item.fund_flow_net >= 0 ? '+' : '') + item.fund_flow_net.toFixed(0) + '万' : '--' }}
            </text>
          </view>
          <view class="col vcp-col-action">
            <!-- #ifdef H5 -->
            <a :href="item.futu_url" class="futu-link" @click.stop>
              <text class="futu-icon">📈</text>
            </a>
            <!-- #endif -->
          </view>
        </view>

        <!-- 主行第二行：题材标签 -->
        <view v-if="item.concepts" class="vcp-row-concepts">
          <text
            v-for="tag in item.concepts.split(', ').slice(0, 4)"
            :key="tag"
            class="concept-tag"
          >{{ tag }}</text>
        </view>

        <!-- 展开行：完整详情 -->
        <view v-if="expandedIdx === idx" class="vcp-expand">
          <view v-if="catalystMap[item.ts_code]" class="vcp-expand-row">
            <text class="vcp-expand-label">🔥 催化剂</text>
            <text class="vcp-expand-val" style="color: var(--color-up);">
              {{ catalystMap[item.ts_code].catalyst_summary || `${catalystMap[item.ts_code].news_count}条高分新闻命中` }}
            </text>
          </view>
          <view class="vcp-expand-row">
            <text class="vcp-expand-label">行业</text>
            <text class="vcp-expand-val">{{ item.industry || '--' }}</text>
          </view>
          <view class="vcp-expand-row">
            <text class="vcp-expand-label">题材</text>
            <text class="vcp-expand-val vcp-concepts">{{ item.concepts || '--' }}</text>
          </view>
          <view class="vcp-expand-row">
            <text class="vcp-expand-label">主力净流入</text>
            <text class="vcp-expand-val" :class="pctValClass(item.fund_flow_net)">
              {{ item.fund_flow_net != null ? (item.fund_flow_net >= 0 ? '+' : '') + item.fund_flow_net.toFixed(2) + '万' : '--' }}
            </text>
          </view>
          <view class="vcp-expand-row">
            <text class="vcp-expand-label">EPS增长</text>
            <text class="vcp-expand-val" :class="pctValClass(item.eps_growth)">{{ formatPctVal(item.eps_growth) }}</text>
          </view>
          <view class="vcp-expand-row">
            <text class="vcp-expand-label">营收同比</text>
            <text class="vcp-expand-val" :class="pctValClass(item.revenue_yoy)">{{ formatPctVal(item.revenue_yoy) }}</text>
          </view>
          <view class="vcp-expand-row">
            <text class="vcp-expand-label">主营业务</text>
            <text class="vcp-expand-val vcp-business">{{ item.main_business || '--' }}</text>
          </view>
          <view class="vcp-expand-row">
            <text class="vcp-expand-label">EMA</text>
            <text class="vcp-expand-val">20d: {{ formatPrice(item.ema20) }}　50d: {{ formatPrice(item.ema50) }}　120d: {{ formatPrice(item.ema120) }}</text>
          </view>

          <!-- VCP 形态识别（纯算法，人在环上复核） -->
          <view class="vcp-analysis" v-if="vcpAnalysis[item.ts_code]">
            <view class="vcp-ana-head">
              <text class="vcp-ana-title">📐 VCP 形态识别</text>
              <text class="vcp-ana-badge" :class="vcpAnalysis[item.ts_code].vcp_detected ? 'on' : 'off'">
                {{ vcpAnalysis[item.ts_code].vcp_detected ? '已识别' : '未识别' }}
              </text>
            </view>

            <template v-if="vcpAnalysis[item.ts_code].data_available === false">
              <text class="vcp-ana-reason">{{ vcpAnalysis[item.ts_code].reason }}</text>
            </template>

            <template v-else>
              <view class="vcp-metric-grid">
                <view class="vcp-metric">
                  <text class="vcp-m-label">收缩次数</text>
                  <text class="vcp-m-val">{{ vcpAnalysis[item.ts_code].contractions }}</text>
                </view>
                <view class="vcp-metric">
                  <text class="vcp-m-label">振幅递减</text>
                  <text class="vcp-m-val" :class="vcpAnalysis[item.ts_code].decay_ok ? 'ok' : 'no'">{{ vcpAnalysis[item.ts_code].decay_ok ? '✓' : '✗' }}</text>
                </view>
                <view class="vcp-metric">
                  <text class="vcp-m-label">量能递减</text>
                  <text class="vcp-m-val" :class="vcpAnalysis[item.ts_code].vol_decay_ok ? 'ok' : 'no'">{{ vcpAnalysis[item.ts_code].vol_decay_ok ? '✓' : '✗' }}</text>
                </view>
                <view class="vcp-metric">
                  <text class="vcp-m-label">高点递减*</text>
                  <text class="vcp-m-val" :class="vcpAnalysis[item.ts_code].high_ok ? 'ok' : 'no'">{{ vcpAnalysis[item.ts_code].high_ok ? '✓' : '✗' }}</text>
                </view>
                <view class="vcp-metric">
                  <text class="vcp-m-label">距枢轴</text>
                  <text class="vcp-m-val" :class="vcpAnalysis[item.ts_code].near_pivot ? 'ok' : 'warn'">
                    {{ vcpAnalysis[item.ts_code].pivot_distance_pct != null ? vcpAnalysis[item.ts_code].pivot_distance_pct + '%' : '—' }}
                  </text>
                </view>
                <view class="vcp-metric">
                  <text class="vcp-m-label">枢轴价</text>
                  <text class="vcp-m-val">{{ formatPrice(vcpAnalysis[item.ts_code].pivot_suggested) }}</text>
                </view>
              </view>

              <text class="vcp-ana-reason">{{ vcpAnalysis[item.ts_code].reason }}</text>
              <text class="vcp-ana-note">* 高点递减仅参考、非硬门槛（末次回升常逼近枢轴略高）。最终以你在决策面板拨「VCP 已确认」为准。</text>

              <view class="vcp-kline-wrap" v-if="vcpChartOf(item.ts_code)">
                <!-- #ifdef H5 -->
                <svg xmlns="http://www.w3.org/2000/svg" :viewBox="`0 0 ${vcpChartOf(item.ts_code).W} ${vcpChartOf(item.ts_code).H}`" class="vcp-kline-svg">
                  <rect v-for="(s,si) in vcpChartOf(item.ts_code).segs" :key="'seg'+si"
                    :x="s.x1" y="8" :width="Math.max(2,s.x2-s.x1)" height="150" fill="rgba(120,120,200,0.07)" />
                  <g v-for="(c,ci) in vcpChartOf(item.ts_code).candles" :key="'c'+ci">
                    <line :x1="c.x" :x2="c.x" :y1="c.yh" :y2="c.yl" :stroke="c.color" stroke-width="0.6"/>
                    <rect :x="c.x - vcpChartOf(item.ts_code).cw/2" :y="c.yTop" :width="vcpChartOf(item.ts_code).cw" :height="c.h" :fill="c.color"/>
                  </g>
                  <rect v-for="(v,vi) in vcpChartOf(item.ts_code).volBars" :key="'v'+vi"
                    :x="v.x - vcpChartOf(item.ts_code).cw/2" :y="168 + (32 - v.h)" :width="vcpChartOf(item.ts_code).cw" :height="v.h"
                    :fill="v.up ? 'rgba(235,75,75,0.32)' : 'rgba(48,184,110,0.32)'"/>
                  <line v-if="vcpChartOf(item.ts_code).pivotY != null" x1="0" :y1="vcpChartOf(item.ts_code).pivotY" x2="400" :y2="vcpChartOf(item.ts_code).pivotY" stroke="#f5a623" stroke-width="1" stroke-dasharray="4,3"/>
                  <g v-for="(sp,spi) in vcpChartOf(item.ts_code).swings" :key="'sp'+spi">
                    <circle :cx="sp.x" :cy="sp.y" r="2.6" :fill="sp.type==='H' ? '#eb4b4b' : '#30b86e'" stroke="#fff" stroke-width="0.6"/>
                  </g>
                </svg>
                <!-- #endif -->
                <view class="vcp-kline-legend">
                  <text class="vcp-leg"><text class="vcp-dot h"></text>摆动高点</text>
                  <text class="vcp-leg"><text class="vcp-dot l"></text>摆动低点</text>
                  <text class="vcp-leg"><text class="vcp-line"></text>枢轴价</text>
                  <text class="vcp-leg"><text class="vcp-band"></text>收缩段</text>
                </view>
              </view>

              <view class="vcp-segs" v-if="vcpAnalysis[item.ts_code].segments && vcpAnalysis[item.ts_code].segments.length">
                <view class="vcp-seg-row" v-for="(seg,si) in vcpAnalysis[item.ts_code].segments" :key="si">
                  <text class="vcp-seg-idx">第{{ si+1 }}次</text>
                  <text class="vcp-seg-amp">振幅 {{ seg.amplitude_pct }}%</text>
                  <text class="vcp-seg-vol">量 {{ formatVol(seg.avg_volume) }}</text>
                </view>
              </view>
            </template>
          </view>

          <view class="vcp-analysis" v-else-if="vcpAnalyzing === item.ts_code">
            <text class="vcp-ana-reason">VCP 分析中…</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import IndustryConceptFilter from './IndustryConceptFilter.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { fetchVCPWatchlist, fetchVCPFilters, batchCheckCatalyst, peekVCPWatchlist, peekVCPFilters, peekCatalyst, fetchVcpAnalyze } from '@/utils/api'

const props = defineProps({
  market: { type: String, default: 'CN' },
})
const emit = defineEmits(['stock-select'])

const onRowClick = (item, idx) => {
  const willExpand = expandedIdx.value !== idx
  expandedIdx.value = willExpand ? idx : -1
  if (willExpand) loadVcp(item)
  emit('stock-select', { ts_code: item.ts_code, name: item.name })
}

const vcpList = ref([])
const vcpDate = ref('')
const vcpLoading = ref(false)
const expandedIdx = ref(-1)
const filterRef = ref(null)

// 催化剂映射 {ts_code: {has_catalyst, heat_score, ...}}
const catalystMap = ref({})

// 筛选器选项
const industryOptions = ref([])
const conceptOptions = ref([])

// 筛选器选中状态
const filterIndustries = ref([])
const filterConcepts = ref([])

const filteredList = computed(() => {
  let list = vcpList.value
  if (filterIndustries.value.length > 0) {
    list = list.filter(item => item.industry && filterIndustries.value.includes(item.industry))
  }
  if (filterConcepts.value.length > 0) {
    list = list.filter(item => {
      if (!item.concepts) return false
      return filterConcepts.value.some(c => item.concepts.includes(c))
    })
  }
  return list
})

const onFilterChange = ({ industries, concepts }) => {
  filterIndustries.value = industries
  filterConcepts.value = concepts
}

const loadFilters = async () => {
  const hit = peekVCPFilters(props.market)
  if (hit) {
    industryOptions.value = hit.industries || []
    conceptOptions.value = hit.concepts || []
    return
  }
  try {
    const data = await fetchVCPFilters(props.market)
    industryOptions.value = data.industries || []
    conceptOptions.value = data.concepts || []
  } catch (e) {
    console.error('加载 VCP 筛选项失败:', e)
  }
}

// 催化剂状态：命中缓存则零转圈填充，否则发请求（失败不影响主功能）
const loadCatalyst = async (codes) => {
  if (!codes.length) return
  const hit = peekCatalyst(codes)
  if (hit) {
    catalystMap.value = hit.items || {}
    return
  }
  try {
    const catData = await batchCheckCatalyst(codes)
    catalystMap.value = catData.items || {}
  } catch (e) {
    console.warn('加载催化剂状态失败（不影响主功能）:', e)
  }
}

const loadData = async () => {
  // 命中白名单缓存：同步填充，完全不进 loading 分支（零转圈）
  const listHit = peekVCPWatchlist(props.market)
  if (listHit) {
    vcpList.value = listHit.items || []
    vcpDate.value = listHit.date || ''
    await loadCatalyst(vcpList.value.map(i => i.ts_code).filter(Boolean))
    return
  }

  vcpLoading.value = true
  try {
    const data = await fetchVCPWatchlist({ market: props.market })
    vcpList.value = data.items || []
    vcpDate.value = data.date || ''
    await loadCatalyst(vcpList.value.map(i => i.ts_code).filter(Boolean))
  } catch (e) {
    console.error('加载 VCP 白名单失败:', e)
    uni.showToast({ title: '加载失败', icon: 'none' })
  } finally {
    vcpLoading.value = false
  }
}

// 工具函数
const formatPrice = (v) => v == null ? '--' : Number(v).toFixed(2)
const formatVcp = (v) => v == null ? '--' : Number(v).toFixed(3)
const vcpClass = (v) => {
  if (v == null) return 'vcp-level-none'
  return v >= 0.50 ? 'vcp-level-hot' : v >= 0.30 ? 'vcp-level-warm' : v >= 0.10 ? 'vcp-level-normal' : 'vcp-level-cool'
}
const formatPctVal = (v) => {
  if (v == null) return '--'
  const n = Number(v)
  return (n >= 0 ? '+' : '') + n.toFixed(1) + '%'
}
const pctValClass = (v) => v == null ? '' : v > 0 ? 'val-up' : v < 0 ? 'val-down' : ''
const rankClass = (idx) => idx < 3 ? 'rank-top' : idx < 10 ? 'rank-high' : ''

// ── VCP 形态识别（展开行内实时分析，人在环上）──
const vcpAnalysis = ref({})   // ts_code -> 分析结果
  const vcpAnalyzing = ref('')    // 正在分析的 ts_code

  const loadVcp = async (item) => {
    const code = item.ts_code
    if (!code || vcpAnalyzing.value === code) return
    // 快路径：优先用 watchlist 已带回的 vcp_auto（批量回填结果，含判定+K线），零延迟渲染
    if (item.vcp_auto && typeof item.vcp_auto === 'object' && 'vcp_detected' in item.vcp_auto) {
      vcpAnalysis.value[code] = item.vcp_auto
      return
    }
    if (vcpAnalysis.value[code]) return
    vcpAnalyzing.value = code
    try {
      const r = await fetchVcpAnalyze({ market: props.market, symbol: code })
      vcpAnalysis.value[code] = r
    } catch (e) {
      vcpAnalysis.value[code] = {
        data_available: true, vcp_detected: false,
        reason: 'VCP 分析失败：' + (e.message || '网络错误'),
      }
    } finally {
      if (vcpAnalyzing.value === code) vcpAnalyzing.value = ''
    }
  }

// 把后端 bars + swing_points + segments 转成 SVG 坐标（蜡烛 + 量能 + 标注）
const vcpChartOf = (code) => {
  const r = vcpAnalysis.value[code]
  if (!r || !r.data_available || !r.bars || !r.bars.length) return null
  const bars = r.bars
  const n = bars.length
  const W = 400, H = 210, padX = 6, top = 8, chartH = 150, volTop = 168, volH = 32
  let low = Infinity, high = -Infinity, maxVol = 0
  for (const b of bars) {
    if (b.low < low) low = b.low
    if (b.high > high) high = b.high
    if ((b.volume || 0) > maxVol) maxVol = b.volume || 0
  }
  if (!isFinite(low) || !isFinite(high) || high <= low) return null
  const range = high - low
  const xOf = (i) => padX + (n === 1 ? 0 : (i / (n - 1)) * (W - 2 * padX))
  const yOf = (p) => top + (1 - (p - low) / range) * chartH
  const cw = Math.max(1, ((W - 2 * padX) / n) * 0.66)
  const candles = bars.map((b, i) => {
    const up = b.close >= b.open
    const yTop = Math.min(yOf(b.open), yOf(b.close))
    const h = Math.max(1.5, Math.abs(yOf(b.open) - yOf(b.close)))
    return { x: xOf(i), yh: yOf(b.high), yl: yOf(b.low), yTop, h, color: up ? '#eb4b4b' : '#30b86e' }
  })
  const volBars = bars.map((b, i) => ({
    x: xOf(i), h: ((b.volume || 0) / (maxVol || 1)) * volH, up: b.close >= b.open,
  }))
  const dateIdx = {}
  bars.forEach((b, i) => { dateIdx[b.date] = i })
  const swings = (r.swing_points || []).map(s => {
    const i = dateIdx[s.date]
    if (i === undefined) return null
    return { x: xOf(i), y: yOf(s.price), type: s.type }
  }).filter(Boolean)
  const segs = (r.segments || []).map(s => ({ x1: xOf(s.start_idx), x2: xOf(s.end_idx) }))
  const pivotY = r.pivot_suggested != null ? yOf(r.pivot_suggested) : null
  return { W, H, candles, volBars, swings, segs, pivotY, cw }
}

const formatVol = (v) => {
  if (v == null) return '--'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(1) + '万'
  return Math.round(v).toString()
}

// 暴露加载方法给父组件
const init = () => {
  loadData()
  loadFilters()
}

defineExpose({ init })

onMounted(() => {
  init()
})
</script>
