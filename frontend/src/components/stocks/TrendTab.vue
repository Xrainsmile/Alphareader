<template>
  <view>
    <view class="stocks-header">
      <text class="stocks-title">右侧趋势</text>
      <text class="stocks-subtitle">双均线趋势突破 · Dual MA Trend Breakout</text>
    </view>

    <view class="info-bar">
      <text class="info-date">数据日期: {{ trendDate || '--' }}</text>
      <text class="info-date">共 {{ filteredList.length }}/{{ trendList.length }} 只</text>
    </view>

    <IndustryConceptFilter
      ref="filterRef"
      :industry-options="industryOptions"
      :concept-options="conceptOptions"
      @change="onFilterChange"
    />

    <!-- 趋势表格头 -->
    <view class="vcp-table-header">
      <text class="vth vth-rank">#</text>
      <text class="vth vth-name">名称/代码</text>
      <text class="vth vth-price">收盘价</text>
      <text class="vth vth-vcp">趋势分</text>
      <text class="vth vth-flow">资金流入</text>
      <text class="vth vth-action">交易</text>
    </view>

    <EmptyState v-if="trendLoading" text="加载中..." bg="var(--color-bg-card)" radius="0 0 16rpx 16rpx" />
    <EmptyState v-else-if="filteredList.length === 0" :text="trendList.length === 0 ? '今天没有符合策略的标的' : '无匹配结果，请调整筛选条件'" bg="var(--color-bg-card)" radius="0 0 16rpx 16rpx" />
    <view v-else class="stock-list">
      <view
        v-for="(item, idx) in filteredList"
        :key="item.ts_code"
        class="vcp-row"
        :class="{ 'stock-row-alt': idx % 2 === 1 }"
        @click="expandedIdx = expandedIdx === idx ? -1 : idx"
      >
        <!-- 主行：核心指标 -->
        <view class="vcp-row-main">
          <view class="col vcp-col-rank"><text class="rank-num" :class="rankClass(idx)">{{ idx + 1 }}</text></view>
          <view class="col vcp-col-name">
            <text class="stock-name">{{ item.name || item.ts_code }}</text>
            <text class="stock-code">{{ item.ts_code }}{{ item.industry ? ' · ' + item.industry : '' }}</text>
          </view>
          <view class="col vcp-col-price"><text class="close-price">{{ formatPrice(item.current_price) }}</text></view>
          <view class="col vcp-col-vcp">
            <view class="vcp-badge" :class="trendScoreClass(item.trend_score)">
              <text class="vcp-val">{{ formatTrendScore(item.trend_score) }}</text>
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

        <!-- 题材标签 -->
        <view v-if="item.concepts" class="vcp-row-concepts">
          <text
            v-for="tag in item.concepts.split(', ').slice(0, 4)"
            :key="tag"
            class="concept-tag"
          >{{ tag }}</text>
        </view>

        <!-- 展开行：完整详情 -->
        <view v-if="expandedIdx === idx" class="vcp-expand">
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
            <text class="vcp-expand-label">ADX(14)</text>
            <text class="vcp-expand-val">{{ item.adx != null ? item.adx.toFixed(1) : '--' }}</text>
          </view>
          <view class="vcp-expand-row">
            <text class="vcp-expand-label">RSI(14)</text>
            <text class="vcp-expand-val">{{ item.rsi != null ? item.rsi.toFixed(1) : '--' }}</text>
          </view>
          <view class="vcp-expand-row">
            <text class="vcp-expand-label">放量倍数</text>
            <text class="vcp-expand-val">{{ item.volume_ratio != null ? item.volume_ratio.toFixed(1) + 'x' : '--' }}</text>
          </view>
          <view class="vcp-expand-row">
            <text class="vcp-expand-label">主营业务</text>
            <text class="vcp-expand-val vcp-business">{{ item.main_business || '--' }}</text>
          </view>
          <view class="vcp-expand-row">
            <text class="vcp-expand-label">SMA</text>
            <text class="vcp-expand-val">20d: {{ formatPrice(item.ma20) }}　50d: {{ formatPrice(item.ma50) }}</text>
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
import { fetchTrendWatchlist, fetchTrendFilters } from '@/utils/api'

const trendList = ref([])
const trendDate = ref('')
const trendLoading = ref(false)
const expandedIdx = ref(-1)
const filterRef = ref(null)

// 筛选器选项
const industryOptions = ref([])
const conceptOptions = ref([])

// 筛选器选中状态
const filterIndustries = ref([])
const filterConcepts = ref([])

const filteredList = computed(() => {
  let list = trendList.value
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
  try {
    const data = await fetchTrendFilters()
    industryOptions.value = data.industries || []
    conceptOptions.value = data.concepts || []
  } catch (e) {
    console.error('加载趋势筛选项失败:', e)
  }
}

const loadData = async () => {
  trendLoading.value = true
  try {
    const data = await fetchTrendWatchlist({})
    trendList.value = data.items || []
    trendDate.value = data.date || ''
  } catch (e) {
    console.error('加载趋势白名单失败:', e)
    uni.showToast({ title: '加载失败', icon: 'none' })
  } finally {
    trendLoading.value = false
  }
}

// 工具函数
const formatPrice = (v) => v == null ? '--' : Number(v).toFixed(2)
const formatTrendScore = (v) => v == null ? '--' : Number(v).toFixed(3)
const trendScoreClass = (v) => {
  if (v == null) return 'vcp-level-none'
  return v >= 0.70 ? 'vcp-level-hot' : v >= 0.50 ? 'vcp-level-warm' : v >= 0.30 ? 'vcp-level-normal' : 'vcp-level-cool'
}
const pctValClass = (v) => v == null ? '' : v > 0 ? 'val-up' : v < 0 ? 'val-down' : ''
const rankClass = (idx) => idx < 3 ? 'rank-top' : idx < 10 ? 'rank-high' : ''

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
