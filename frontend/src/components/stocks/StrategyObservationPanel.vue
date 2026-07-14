<template>
  <view class="sop">
    <!-- ═══ 个股信号视图（点击候选股后）═══ -->
    <view v-if="selectedStock" class="sop-block">
      <view class="sop-stock-head">
        <view class="sop-stock-name">
          <text class="sop-stock-title">{{ stockSignal ? stockSignal.name : selectedStock.name }}</text>
          <text class="sop-stock-code">{{ selectedStock.ts_code }}</text>
        </view>
        <view class="sop-back" @click="onReturn">返回概览</view>
      </view>

      <EmptyState v-if="signalLoading" text="加载信号中..." bg="transparent" />
      <view v-else-if="stockSignal" class="sop-signal">
        <view class="sop-maturity" :class="maturityClass">{{ stockSignal.maturity }}</view>

        <view class="sop-sig-row">
          <text class="sop-sig-k">中期趋势</text>
          <text class="sop-sig-v" :class="trendClass">{{ stockSignal.mid_trend }}</text>
        </view>
        <view class="sop-sig-row">
          <text class="sop-sig-k">波动收缩</text>
          <text class="sop-sig-v">{{ stockSignal.vol_contraction.status }}</text>
        </view>
        <view class="sop-sig-sub" v-if="stockSignal.vol_contraction.detail">{{ stockSignal.vol_contraction.detail }}</view>

        <view class="sop-sig-row">
          <text class="sop-sig-k">成交量收缩</text>
          <text class="sop-sig-v">
            {{ stockSignal.volume_contraction.status }}
            <text v-if="stockSignal.volume_contraction.change_pct != null">（{{ stockSignal.volume_contraction.change_pct }}%）</text>
          </text>
        </view>

        <view class="sop-sig-row">
          <text class="sop-sig-k">枢轴位距离</text>
          <text class="sop-sig-v" v-if="stockSignal.pivot_distance_pct != null">{{ stockSignal.pivot_distance_pct }}%</text>
          <text class="sop-sig-v" v-else>--</text>
        </view>
        <view class="sop-sig-row">
          <text class="sop-sig-k">突破确认</text>
          <text class="sop-sig-v" :class="stockSignal.breakout_confirmed ? 'sop-up' : 'sop-muted'">
            {{ stockSignal.breakout_confirmed ? '已确认' : '尚未确认' }}
          </text>
        </view>

        <view class="sop-risk-box">
          <text class="sop-risk-title">风险提示</text>
          <view v-for="(r, i) in stockSignal.risk_hints" :key="i" class="sop-risk-item">⚠ {{ r }}</view>
        </view>
      </view>
      <view v-else class="sop-empty">暂无该标的信号数据</view>
    </view>

    <!-- ═══ 策略概览视图 ═══ -->
    <template v-else>
      <EmptyState v-if="loading" text="加载策略观察中..." bg="transparent" />

      <view v-else-if="comingSoon" class="sop-block">
        <view class="sop-block-title">策略画像</view>
        <view class="sop-profile-name">{{ profile && profile.name }}</view>
        <view class="sop-coming">该策略正在准备中，敬请期待。</view>
      </view>

      <view v-else-if="overview" class="sop-wrap">
        <!-- 策略画像 -->
        <view class="sop-block">
          <view class="sop-block-title">策略画像</view>
          <view class="sop-profile-name">{{ profile.name }}</view>
          <view class="sop-profile-type" v-if="profile.type">{{ profile.type }}</view>
          <view class="sop-row" v-if="profile.target"><text class="sop-k">目标</text><text class="sop-v">{{ profile.target }}</text></view>
          <view class="sop-row" v-if="profile.suitable_market"><text class="sop-k">适合环境</text><text class="sop-v">{{ profile.suitable_market }}</text></view>
          <view class="sop-row" v-if="profile.typical_cycle"><text class="sop-k">典型周期</text><text class="sop-v">{{ profile.typical_cycle }}</text></view>
          <view class="sop-core" v-if="profile.core_signals && profile.core_signals.length">
            <text class="sop-core-title">核心信号</text>
            <view v-for="(s, i) in profile.core_signals" :key="i" class="sop-core-item">· {{ s }}</view>
          </view>
        </view>

        <!-- 市场适配 -->
        <view class="sop-block" v-if="adaptability">
          <view class="sop-block-title">市场适配</view>
          <view class="sop-adapt-head">
            <text class="sop-level" :class="levelClass">{{ adaptability.level_label }}</text>
            <text class="sop-score">{{ adaptability.total_score }}<text class="sop-score-max">/100</text></text>
          </view>
          <view
            v-for="d in adaptability.dimensions"
            :key="d.key"
            class="sop-dim"
            @click="toggleDim(d.key)"
          >
            <view class="sop-dim-row">
              <text class="sop-dim-name">{{ d.name }}</text>
              <text class="sop-dim-score">{{ d.score }}/{{ d.max }}</text>
            </view>
            <text class="sop-dim-status" :class="'sop-st-' + d.status">{{ d.status_label }}</text>
            <view v-if="expandedDim === d.key" class="sop-dim-detail">{{ d.detail }}</view>
          </view>
          <view class="sop-conclusion">{{ adaptability.conclusion }}</view>
          <view v-if="adaptability.data_delayed" class="sop-delay">部分市场指标暂未更新，结果仅供参考</view>
        </view>

        <!-- 筛选摘要 -->
        <view class="sop-block" v-if="filterSummary">
          <view class="sop-block-title">筛选摘要</view>
          <view class="sop-sum-grid">
            <view class="sop-sum-cell">
              <text class="sop-sum-num">{{ filterSummary.base_count }}</text>
              <text class="sop-sum-lab">基础符合</text>
            </view>
            <view class="sop-sum-cell">
              <text class="sop-sum-num">{{ filterSummary.observe_count }}</text>
              <text class="sop-sum-lab">重点观察</text>
            </view>
            <view class="sop-sum-cell">
              <text class="sop-sum-num">{{ filterSummary.breakout_confirm }}</text>
              <text class="sop-sum-lab">突破确认</text>
            </view>
            <view class="sop-sum-cell">
              <text class="sop-sum-num">+{{ filterSummary.new_count }}</text>
              <text class="sop-sum-lab">较昨日新增</text>
            </view>
          </view>
          <text class="sop-date" v-if="filterSummary.data_date">数据日期：{{ filterSummary.data_date }}</text>
        </view>

        <!-- 风险提示 -->
        <view class="sop-block" v-if="profile && profile.risk_hints && profile.risk_hints.length">
          <view class="sop-block-title">风险提示</view>
          <view v-for="(r, i) in profile.risk_hints" :key="i" class="sop-risk">⚠ {{ r }}</view>
        </view>

        <!-- 免责声明 -->
        <view class="sop-disclaimer">数据仅供研究与辅助判断，不构成投资建议</view>
      </view>

      <view v-else class="sop-block">
        <view class="sop-empty">策略数据加载失败</view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { fetchStrategyOverview, fetchStrategyStockSignal } from '@/utils/api'

const props = defineProps({
  market: { type: String, default: 'CN' },
  strategyId: { type: String, default: 'vcp' },
  selectedStock: { type: Object, default: null }, // { ts_code, name }
})
const emit = defineEmits(['return-overview'])

// 美股 tab（us_vcp / us_trend…）归一化为规范策略 id，market 单独区分
const strategyId = computed(() => (props.strategyId || 'vcp').replace(/^us_/, '') || 'vcp')

const loading = ref(false)
const overview = ref(null)
const comingSoon = ref(false)
const profile = computed(() => overview.value && overview.value.profile ? overview.value.profile : null)
const adaptability = computed(() => overview.value && overview.value.adaptability ? overview.value.adaptability : null)
const filterSummary = computed(() => overview.value && overview.value.filter_summary ? overview.value.filter_summary : null)

const expandedDim = ref('')

const levelClass = computed(() => {
  if (!adaptability.value) return ''
  return 'sop-level-' + adaptability.value.level
})

// ── 个股信号 ──
const signalLoading = ref(false)
const stockSignal = ref(null)

const maturityClass = computed(() => {
  if (!stockSignal.value) return ''
  const m = stockSignal.value.maturity
  if (m === '突破确认') return 'sop-maturity-confirm'
  if (m === '接近突破') return 'sop-maturity-near'
  if (m === '观察中') return 'sop-maturity-watch'
  return 'sop-maturity-fail'
})
const trendClass = computed(() => {
  if (!stockSignal.value) return ''
  const t = stockSignal.value.mid_trend
  if (t === '向上') return 'sop-up'
  if (t === '偏弱') return 'sop-down'
  return 'sop-muted'
})

function toggleDim(key) {
  expandedDim.value = expandedDim.value === key ? '' : key
}

function onReturn() {
  stockSignal.value = null
  emit('return-overview')
}

async function loadOverview() {
  loading.value = true
  overview.value = null
  comingSoon.value = false
  try {
    const data = await fetchStrategyOverview({ market: props.market, strategyId: strategyId.value })
    if (data.coming_soon) {
      comingSoon.value = true
      overview.value = data
    } else {
      overview.value = data
    }
  } catch (e) {
    console.error('加载策略概览失败:', e)
    overview.value = null
  } finally {
    loading.value = false
  }
}

async function loadSignal() {
  if (!props.selectedStock) return
  signalLoading.value = true
  stockSignal.value = null
  try {
    const data = await fetchStrategyStockSignal({
      market: props.market,
      strategyId: strategyId.value,
      tsCode: props.selectedStock.ts_code,
    })
    stockSignal.value = data
  } catch (e) {
    console.warn('加载个股信号失败:', e)
    stockSignal.value = null
  } finally {
    signalLoading.value = false
  }
}

onMounted(loadOverview)
watch(() => [props.market, strategyId.value], () => {
  expandedDim.value = ''
  loadOverview()
})
watch(() => props.selectedStock, (s) => {
  if (s) loadSignal()
}, { immediate: false })
</script>
