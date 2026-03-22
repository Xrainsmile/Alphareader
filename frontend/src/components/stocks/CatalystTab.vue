<template>
  <view>
    <view class="stocks-header">
      <text class="stocks-title">🔥 催化剂</text>
      <text class="stocks-subtitle">新闻催化 × 技术面交叉验证 · Catalyst × Technical</text>
    </view>

    <view class="info-bar">
      <text class="info-date">数据日期: {{ catalystDate || '--' }}</text>
      <text class="info-date">共 {{ catalystList.length }} 只</text>
    </view>

    <!-- 分类筛选条 -->
    <view class="catalyst-filter-bar">
      <view
        v-for="f in filterOptions"
        :key="f.value"
        class="catalyst-filter-item"
        :class="{ 'catalyst-filter-active': activeFilter === f.value }"
        @click="activeFilter = f.value"
      >
        <text class="catalyst-filter-icon">{{ f.icon }}</text>
        <text class="catalyst-filter-label">{{ f.label }}</text>
        <text class="catalyst-filter-count">{{ filterCounts[f.value] || 0 }}</text>
      </view>
    </view>

    <!-- 催化剂列表 -->
    <EmptyState v-if="loading" text="加载中..." bg="var(--color-bg-card)" radius="0 0 16rpx 16rpx" />
    <EmptyState v-else-if="filteredList.length === 0" text="暂无催化剂标的" bg="var(--color-bg-card)" radius="0 0 16rpx 16rpx" />
    <view v-else class="stock-list">
      <view
        v-for="(item, idx) in filteredList"
        :key="item.ts_code"
        class="catalyst-row"
        :class="{ 'stock-row-alt': idx % 2 === 1 }"
        @click="expandedIdx = expandedIdx === idx ? -1 : idx"
      >
        <!-- 主行 -->
        <view class="catalyst-row-main">
          <view class="col catalyst-col-rank">
            <text class="rank-num" :class="rankClass(idx)">{{ idx + 1 }}</text>
          </view>
          <view class="col catalyst-col-name">
            <view class="catalyst-name-row">
              <text class="stock-name">{{ item.name || item.ts_code }}</text>
              <view class="confirm-badge" :class="confirmClass(item.confirm_level)">
                <text class="confirm-text">{{ confirmLabel(item.confirm_level) }}</text>
              </view>
            </view>
            <text class="stock-code">{{ item.ts_code }}</text>
          </view>
          <view class="col catalyst-col-heat">
            <view class="heat-badge" :class="heatClass(item.heat_score)">
              <text class="heat-val">🔥 {{ item.heat_score.toFixed(0) }}</text>
            </view>
          </view>
          <view class="col catalyst-col-news">
            <text class="news-count">{{ item.news_count }}条</text>
            <text class="top-score">最高{{ item.top_score }}分</text>
          </view>
          <view class="col catalyst-col-action">
            <!-- #ifdef H5 -->
            <a :href="item.futu_url" class="futu-link" @click.stop>
              <text class="futu-icon">📈</text>
            </a>
            <!-- #endif -->
          </view>
        </view>

        <!-- 催化剂类型标签 -->
        <view v-if="item.catalyst_types && item.catalyst_types.length" class="catalyst-tags-row">
          <text
            v-for="tag in item.catalyst_types"
            :key="tag"
            class="catalyst-type-tag"
          >{{ tag }}</text>
          <text v-if="item.in_vcp" class="cross-tag vcp-tag">VCP {{ formatScore(item.vcp_score) }}</text>
          <text v-if="item.in_trend" class="cross-tag trend-tag">趋势 {{ formatScore(item.trend_score) }}</text>
          <text v-if="item.rs_rating" class="cross-tag rs-tag">RS {{ item.rs_rating }}</text>
        </view>

        <!-- 展开行：详情 -->
        <view v-if="expandedIdx === idx" class="catalyst-expand">
          <view class="catalyst-expand-row">
            <text class="catalyst-expand-label">催化剂摘要</text>
            <text class="catalyst-expand-val catalyst-summary">{{ item.catalyst_summary || '--' }}</text>
          </view>
          <view v-if="item.news_titles && item.news_titles.length" class="catalyst-expand-row">
            <text class="catalyst-expand-label">相关新闻</text>
            <view class="catalyst-news-list">
              <text
                v-for="(title, tIdx) in item.news_titles"
                :key="tIdx"
                class="catalyst-news-item"
              >• {{ title }}</text>
            </view>
          </view>
          <view class="catalyst-expand-row">
            <text class="catalyst-expand-label">平均评分</text>
            <text class="catalyst-expand-val">{{ item.avg_score.toFixed(1) }}</text>
          </view>
          <view v-if="item.avg_sentiment != null" class="catalyst-expand-row">
            <text class="catalyst-expand-label">情绪倾向</text>
            <text class="catalyst-expand-val" :class="sentimentClass(item.avg_sentiment)">
              {{ sentimentLabel(item.avg_sentiment) }}
            </text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { fetchCatalystStocks } from '@/utils/api'

const catalystList = ref([])
const catalystDate = ref('')
const loading = ref(false)
const expandedIdx = ref(-1)
const activeFilter = ref('all')

const filterOptions = [
  { value: 'all', label: '全部', icon: '📊' },
  { value: 'double_confirmed', label: '双确认', icon: '🎯' },
  { value: 'strong_rs', label: '强RS', icon: '💪' },
  { value: 'catalyst_only', label: '观察池', icon: '👀' },
]

const filterCounts = computed(() => {
  const list = catalystList.value
  return {
    all: list.length,
    double_confirmed: list.filter(i => i.confirm_level === 'double_confirmed').length,
    strong_rs: list.filter(i => i.confirm_level === 'strong_rs').length,
    catalyst_only: list.filter(i => i.confirm_level === 'catalyst_only').length,
  }
})

const filteredList = computed(() => {
  if (activeFilter.value === 'all') return catalystList.value
  return catalystList.value.filter(i => i.confirm_level === activeFilter.value)
})

const loadData = async () => {
  loading.value = true
  try {
    const data = await fetchCatalystStocks({})
    catalystList.value = data.items || []
    catalystDate.value = data.date || ''
  } catch (e) {
    console.error('加载催化剂标的失败:', e)
    uni.showToast({ title: '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

// 工具函数
const formatScore = (v) => v == null ? '' : Number(v).toFixed(1)
const rankClass = (idx) => idx < 3 ? 'rank-top' : idx < 10 ? 'rank-high' : ''

const confirmClass = (level) => ({
  'confirm-double': level === 'double_confirmed',
  'confirm-strong': level === 'strong_rs',
  'confirm-only': level === 'catalyst_only',
})

const confirmLabel = (level) => ({
  double_confirmed: '🎯 双确认',
  strong_rs: '💪 强RS',
  catalyst_only: '👀 观察',
}[level] || level)

const heatClass = (v) => {
  if (v >= 50) return 'heat-fire'
  if (v >= 20) return 'heat-warm'
  return 'heat-normal'
}

const sentimentClass = (v) => v > 0 ? 'val-up' : v < 0 ? 'val-down' : ''
const sentimentLabel = (v) => {
  if (v >= 3) return `强烈看多 (${v.toFixed(1)})`
  if (v >= 1) return `偏多 (${v.toFixed(1)})`
  if (v <= -3) return `强烈看空 (${v.toFixed(1)})`
  if (v <= -1) return `偏空 (${v.toFixed(1)})`
  return `中性 (${v.toFixed(1)})`
}

// 暴露给父组件
const init = () => loadData()
defineExpose({ init })
onMounted(() => init())
</script>

<style scoped>
/* ── 筛选条 ── */
.catalyst-filter-bar {
  display: flex;
  gap: 12rpx;
  margin-bottom: 16rpx;
  overflow-x: auto;
}
.catalyst-filter-item {
  display: flex;
  align-items: center;
  gap: 6rpx;
  padding: 10rpx 18rpx;
  border-radius: 20rpx;
  background: var(--color-bg-card);
  border: 1rpx solid var(--color-border);
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.2s;
}
.catalyst-filter-active {
  background: var(--color-text-primary);
  border-color: var(--color-text-primary);
}
.catalyst-filter-icon { font-size: 24rpx; }
.catalyst-filter-label {
  font-size: 24rpx;
  font-weight: 600;
  color: var(--color-text-secondary);
}
.catalyst-filter-active .catalyst-filter-label { color: var(--color-text-white); }
.catalyst-filter-count {
  font-size: 22rpx;
  color: var(--color-text-muted);
  font-family: var(--font-numeric);
}
.catalyst-filter-active .catalyst-filter-count { color: var(--color-text-white); opacity: 0.8; }

/* ── 催化剂行 ── */
.catalyst-row {
  padding: 16rpx 20rpx;
  border-bottom: 1rpx solid var(--color-border);
}
.catalyst-row-main {
  display: flex;
  align-items: center;
  gap: 12rpx;
}
.catalyst-col-rank { width: 48rpx; }
.catalyst-col-name { flex: 1; min-width: 0; }
.catalyst-col-heat { width: 100rpx; align-items: center; }
.catalyst-col-news { width: 100rpx; align-items: flex-end; }
.catalyst-col-action { width: 56rpx; align-items: center; }

.catalyst-name-row {
  display: flex;
  align-items: center;
  gap: 8rpx;
}

/* ── 确认级别徽章 ── */
.confirm-badge {
  padding: 2rpx 10rpx;
  border-radius: 8rpx;
  flex-shrink: 0;
}
.confirm-double { background: rgba(34, 197, 94, 0.15); }
.confirm-strong { background: rgba(245, 158, 11, 0.15); }
.confirm-only { background: rgba(107, 114, 128, 0.1); }
.confirm-text { font-size: 20rpx; font-weight: 600; white-space: nowrap; }

/* ── 热度徽章 ── */
.heat-badge {
  padding: 4rpx 14rpx;
  border-radius: 12rpx;
}
.heat-fire { background: rgba(239, 68, 68, 0.15); }
.heat-warm { background: rgba(245, 158, 11, 0.12); }
.heat-normal { background: rgba(107, 114, 128, 0.08); }
.heat-val {
  font-size: 24rpx;
  font-weight: 700;
  color: var(--color-text-primary);
  font-family: var(--font-numeric);
}

.news-count {
  font-size: 24rpx;
  font-weight: 600;
  color: var(--color-text-primary);
}
.top-score {
  font-size: 20rpx;
  color: var(--color-text-muted);
}

/* ── 催化剂类型标签行 ── */
.catalyst-tags-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8rpx;
  margin-top: 10rpx;
  padding-left: 60rpx;
}
.catalyst-type-tag {
  font-size: 22rpx;
  padding: 2rpx 12rpx;
  border-radius: 6rpx;
  background: rgba(139, 92, 246, 0.1);
  color: var(--color-text-secondary);
}
.cross-tag {
  font-size: 22rpx;
  padding: 2rpx 12rpx;
  border-radius: 6rpx;
  font-weight: 600;
}
.vcp-tag { background: rgba(34, 197, 94, 0.12); color: var(--color-up); }
.trend-tag { background: rgba(59, 130, 246, 0.12); color: var(--color-accent); }
.rs-tag { background: rgba(245, 158, 11, 0.12); color: var(--color-warning); }

/* ── 展开详情 ── */
.catalyst-expand {
  margin-top: 12rpx;
  padding: 12rpx 16rpx;
  background: var(--color-bg-hover);
  border-radius: 12rpx;
}
.catalyst-expand-row {
  display: flex;
  padding: 6rpx 0;
  gap: 12rpx;
}
.catalyst-expand-label {
  font-size: 24rpx;
  color: var(--color-text-muted);
  flex-shrink: 0;
  width: 140rpx;
}
.catalyst-expand-val {
  font-size: 24rpx;
  color: var(--color-text-primary);
  flex: 1;
  min-width: 0;
}
.catalyst-summary {
  line-height: 1.5;
}
.catalyst-news-list {
  display: flex;
  flex-direction: column;
  gap: 6rpx;
  flex: 1;
}
.catalyst-news-item {
  font-size: 22rpx;
  color: var(--color-text-secondary);
  line-height: 1.4;
}

/* ── 响应式 ── */
@media screen and (min-width: 768px) {
  .catalyst-filter-bar { gap: 8px; margin-bottom: 12px; }
  .catalyst-filter-item { padding: 6px 14px; border-radius: 14px; }
  .catalyst-filter-icon { font-size: 14px; }
  .catalyst-filter-label { font-size: 13px; }
  .catalyst-filter-count { font-size: 12px; }
  .catalyst-row { padding: 12px 16px; }
  .catalyst-col-rank { width: 32px; }
  .catalyst-col-heat { width: 68px; }
  .catalyst-col-news { width: 68px; }
  .catalyst-col-action { width: 36px; }
  .catalyst-type-tag, .cross-tag { font-size: 12px; padding: 1px 8px; }
  .catalyst-tags-row { padding-left: 40px; gap: 6px; }
  .confirm-badge { padding: 1px 8px; }
  .confirm-text { font-size: 11px; }
  .heat-badge { padding: 2px 10px; border-radius: 8px; }
  .heat-val { font-size: 13px; }
  .news-count { font-size: 13px; }
  .top-score { font-size: 11px; }
  .catalyst-expand { margin-top: 8px; padding: 8px 12px; border-radius: 8px; }
  .catalyst-expand-label { font-size: 13px; width: 90px; }
  .catalyst-expand-val { font-size: 13px; }
  .catalyst-news-item { font-size: 12px; }
}
</style>
