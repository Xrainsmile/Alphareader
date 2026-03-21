<template>
  <view>
    <view class="stocks-header">
      <text class="stocks-title">价投策略</text>
      <text class="stocks-subtitle">巴菲特式价值投资 · Value Investing</text>
    </view>

    <view class="info-bar">
      <text class="info-date">共 {{ filteredList.length }}/{{ valueList.length }} 只</text>
    </view>

    <!-- 价投筛选器 — 名称搜索 -->
    <view v-if="indDropdown" class="icf-overlay" @click="indDropdown = false"></view>

    <view class="vcp-filters">
      <view class="vcp-search-section">
        <view class="vcp-search-bar" :class="{ 'vcp-search-bar-focus': indDropdown }" @click.stop="indDropdown = !indDropdown">
          <view class="vcp-search-input-wrap">
            <text class="vcp-search-icon">🔍</text>
            <input
              class="vcp-search-input"
              type="text"
              v-model="searchQuery"
              placeholder="搜索代码/名称..."
              @focus="indDropdown = false"
              @click.stop
            />
            <view v-if="searchQuery" class="vcp-search-clear" @click.stop="searchQuery = ''">
              <text class="vcp-search-clear-icon">×</text>
            </view>
          </view>
        </view>
      </view>
    </view>

    <!-- 价投表格头 -->
    <view class="vcp-table-header">
      <text class="vth vth-rank">#</text>
      <text class="vth vth-name">名称/代码</text>
      <text class="vth vth-price">收盘价</text>
      <text class="vth vth-flow">状态</text>
      <text class="vth vth-action">交易</text>
    </view>

    <EmptyState v-if="valueLoading" text="加载中..." bg="var(--color-bg-card)" radius="0 0 16rpx 16rpx" />
    <EmptyState v-else-if="filteredList.length === 0" :text="valueList.length === 0 ? '暂无价投标的' : '无匹配结果'" bg="var(--color-bg-card)" radius="0 0 16rpx 16rpx" />
    <view v-else class="stock-list">
      <view
        v-for="(item, idx) in filteredList"
        :key="item.ts_code"
        class="vcp-row"
        :class="{ 'stock-row-alt': idx % 2 === 1 }"
        @click="expandedIdx = expandedIdx === idx ? -1 : idx"
      >
        <!-- 主行：核心信息 -->
        <view class="vcp-row-main">
          <view class="col vcp-col-rank"><text class="rank-num" :class="rankClass(idx)">{{ idx + 1 }}</text></view>
          <view class="col vcp-col-name">
            <text class="stock-name">{{ item.name || item.ts_code }}</text>
            <text class="stock-code">{{ item.ts_code }}{{ item.industry ? ' · ' + item.industry : '' }}</text>
          </view>
          <view class="col vcp-col-price"><text class="close-price">{{ formatPrice(item.current_price) }}</text></view>
          <view class="col vcp-col-flow">
            <view class="value-status-badge" :class="'value-status-' + item.status">
              <text class="value-status-text">{{ item.status === 'holding' ? '持仓' : '观察' }}</text>
            </view>
          </view>
          <view class="col vcp-col-action">
            <!-- #ifdef H5 -->
            <a :href="item.futu_url" class="futu-link" @click.stop>
              <text class="futu-icon">📈</text>
            </a>
            <!-- #endif -->
          </view>
        </view>

        <!-- 题材标签行 -->
        <view v-if="item.concepts" class="vcp-row-concepts">
          <text
            v-for="tag in item.concepts.split(', ').slice(0, 4)"
            :key="tag"
            class="concept-tag"
          >{{ tag }}</text>
        </view>

        <!-- 展开行：详情 -->
        <view v-if="expandedIdx === idx" class="vcp-expand">
          <view class="vcp-expand-row">
            <text class="vcp-expand-label">行业</text>
            <text class="vcp-expand-val">{{ item.industry || '--' }}</text>
          </view>
          <view class="vcp-expand-row">
            <text class="vcp-expand-label">题材</text>
            <text class="vcp-expand-val vcp-concepts">{{ item.concepts || '--' }}</text>
          </view>
          <view v-if="item.reason" class="vcp-expand-row">
            <text class="vcp-expand-label">投资理由</text>
            <text class="vcp-expand-val vcp-business">{{ item.reason }}</text>
          </view>
          <view class="vcp-expand-row">
            <text class="vcp-expand-label">加入时间</text>
            <text class="vcp-expand-val">{{ item.added_at ? item.added_at.split('T')[0] : '--' }}</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { fetchValueWatchlist } from '@/utils/api'

const valueList = ref([])
const valueLoading = ref(false)
const expandedIdx = ref(-1)
const searchQuery = ref('')
const indDropdown = ref(false)

const filteredList = computed(() => {
  const kw = searchQuery.value.trim().toLowerCase()
  if (!kw) return valueList.value
  return valueList.value.filter(item => {
    const code = (item.ts_code || '').toLowerCase()
    const name = (item.name || '').toLowerCase()
    return code.includes(kw) || name.includes(kw)
  })
})

const loadData = async () => {
  valueLoading.value = true
  try {
    const data = await fetchValueWatchlist()
    valueList.value = data.items || []
  } catch (e) {
    console.error('加载价投白名单失败:', e)
    uni.showToast({ title: '加载失败', icon: 'none' })
  } finally {
    valueLoading.value = false
  }
}

const formatPrice = (v) => v == null ? '--' : Number(v).toFixed(2)
const rankClass = (idx) => idx < 3 ? 'rank-top' : idx < 10 ? 'rank-high' : ''

const init = () => { loadData() }

defineExpose({ init })

onMounted(() => {
  init()
})
</script>
