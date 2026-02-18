<template>
  <view class="stocks-container">
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
      <!-- 搜索 Loading -->
      <view v-if="searchLoading" class="empty-state">
        <text class="empty-text">搜索中...</text>
      </view>

      <!-- 搜索提示信息 (无结果) -->
      <view v-else-if="searchMessage" class="empty-state">
        <text class="empty-text">{{ searchMessage }}</text>
      </view>

      <!-- 搜索结果列表 -->
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
            <view class="col col-rank">
              <text class="rank-num">{{ idx + 1 }}</text>
            </view>
            <view class="col col-name">
              <text class="stock-name">{{ item.name }}</text>
              <text class="stock-code">{{ item.ts_code }}</text>
            </view>
            <view class="col col-close">
              <text class="close-price">{{ formatPrice(item.close) }}</text>
            </view>
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

    <!-- 以下为原有排行榜 (非搜索模式时显示) -->
    <template v-if="!searchMode">
      <!-- 数据日期 & 状态 -->
      <view class="info-bar">
        <text class="info-date">数据日期: {{ dataDate || '--' }}</text>
        <view v-if="isTrading" class="trading-badge">
          <text class="trading-dot">●</text>
          <text class="trading-text">盘中</text>
        </view>
      </view>

      <!-- 表头 -->
      <view class="table-header">
        <text class="th th-rank">#</text>
        <text class="th th-name">名称/代码</text>
        <text class="th th-close">收盘价</text>
        <text class="th th-pct">涨跌幅</text>
        <text class="th th-rs">RS</text>
      </view>

      <!-- Loading -->
      <view v-if="loading" class="empty-state">
        <text class="empty-text">加载中...</text>
      </view>

      <!-- Empty -->
      <view v-else-if="stockList.length === 0" class="empty-state">
        <text class="empty-text">暂无数据</text>
      </view>

      <!-- Stock List -->
      <view v-else class="stock-list">
        <view
          v-for="(item, idx) in stockList"
          :key="item.ts_code"
          class="stock-row"
          :class="{ 'stock-row-alt': idx % 2 === 1 }"
        >
          <view class="col col-rank">
            <text class="rank-num" :class="rankClass(idx)">{{ idx + 1 }}</text>
          </view>
          <view class="col col-name">
            <text class="stock-name">{{ item.name }}</text>
            <text class="stock-code">{{ item.ts_code }}</text>
          </view>
          <view class="col col-close">
            <text class="close-price">{{ formatPrice(item.close) }}</text>
          </view>
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

    <!-- Footer -->
    <view class="site-footer">
      <text class="footer-icp" @click="onOpenIcp">蜀ICP备2026006985号</text>
      <text class="footer-copy">© 2026 Rick</text>
    </view>
  </view>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { fetchRSRating, searchStocks } from '@/utils/api'

const stockList = ref([])
const dataDate = ref('')
const loading = ref(true)
const descExpanded = ref(false)

// ── 搜索相关 ──
const searchMode = ref(false)
const searchFocused = ref(false)
const searchQuery = ref('')
const searchSubmitted = ref(false)
const searchList = ref([])
const searchLoading = ref(false)
const searchMessage = ref('')

// 判断当前是否在 A 股交易时段
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

// ── 搜索方法 ──

const onSearchFocus = () => {
  searchFocused.value = true
  searchMode.value = true
}

const onSearchInput = (e) => {
  searchQuery.value = e.detail.value
  searchSubmitted.value = false
  searchMessage.value = ''
}

const onSearchConfirm = () => {
  const q = searchQuery.value.trim()
  if (!q) return
  doSearch()
}

const onClearSearch = () => {
  searchQuery.value = ''
  searchSubmitted.value = false
  searchList.value = []
  searchMessage.value = ''
}

const onExitSearch = () => {
  searchMode.value = false
  searchFocused.value = false
  searchQuery.value = ''
  searchSubmitted.value = false
  searchList.value = []
  searchMessage.value = ''
}

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

// ── 格式化方法 ──

const formatPrice = (v) => {
  if (v == null) return '--'
  return Number(v).toFixed(2)
}

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

const changeClass = (v) => {
  if (v == null) return 'change-flat'
  return v > 0 ? 'change-up' : v < 0 ? 'change-down' : 'change-flat'
}

const rankClass = (idx) => {
  if (idx < 3) return 'rank-top'
  if (idx < 10) return 'rank-high'
  return ''
}

const rsClass = (rating) => {
  if (rating >= 90) return 'rs-hot'
  if (rating >= 70) return 'rs-warm'
  if (rating >= 50) return 'rs-normal'
  return 'rs-cool'
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
  bottom: 0;
  right: 0;
  padding: 0 20rpx 0 40rpx;
  background: linear-gradient(90deg, transparent, rgba(240, 242, 245, 1) 40%);
  font-size: 20rpx;
  color: #8c8c9a;
  line-height: 40rpx;
}
.rs-desc-expanded {
  max-height: 600rpx;
}
.rs-desc-expanded::after {
  display: none;
}
.rs-desc-text {
  font-size: 22rpx;
  color: #8c8c9a;
  line-height: 1.7;
  display: block;
}

/* ── Info Bar ── */
.info-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12rpx 0 16rpx;
}
.info-date {
  font-size: 24rpx;
  color: #8c8c9a;
}
.trading-badge {
  display: flex;
  align-items: center;
  gap: 6rpx;
  padding: 4rpx 16rpx;
  background: rgba(255, 59, 48, 0.08);
  border-radius: 20rpx;
}
.trading-dot {
  font-size: 16rpx;
  color: #ff3b30;
  animation: pulse 1.5s infinite;
}
.trading-text {
  font-size: 22rpx;
  color: #ff3b30;
  font-weight: 500;
}
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

/* ── Table Header ── */
.table-header {
  display: flex;
  align-items: center;
  padding: 18rpx 20rpx;
  background: #ffffff;
  border-radius: 16rpx 16rpx 0 0;
  border-bottom: 2rpx solid #f0f0f2;
}
.th {
  font-size: 22rpx;
  color: #8c8c9a;
  font-weight: 600;
}
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

/* ── Stock Row ── */
.stock-row {
  display: flex;
  align-items: center;
  padding: 22rpx 20rpx;
  border-bottom: 1rpx solid #f8f8fa;
}
.stock-row-alt {
  background: #fafbfc;
}
.stock-row:last-child {
  border-bottom: none;
}

/* ── Columns ── */
.col { display: flex; flex-direction: column; justify-content: center; }
.col-rank { width: 60rpx; align-items: center; }
.col-name { flex: 1; padding-left: 12rpx; }
.col-close { width: 140rpx; align-items: flex-end; }
.col-pct { width: 160rpx; align-items: flex-end; }
.col-rs { width: 80rpx; align-items: center; }

/* ── Rank ── */
.rank-num {
  font-size: 24rpx;
  color: #8c8c9a;
  font-weight: 600;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.rank-top {
  color: #ff3b30;
  font-weight: 800;
}
.rank-high {
  color: #ff9500;
  font-weight: 700;
}

/* ── Name & Code ── */
.stock-name {
  font-size: 28rpx;
  font-weight: 600;
  color: #1a1a2e;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.stock-code {
  font-size: 22rpx;
  color: #b0b0be;
  margin-top: 4rpx;
  font-family: 'SF Mono', 'Menlo', monospace;
}

/* ── Close Price ── */
.close-price {
  font-size: 28rpx;
  font-weight: 600;
  color: #1a1a2e;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}

/* ── Change Badge ── */
.change-badge {
  padding: 4rpx 14rpx;
  border-radius: 8rpx;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.change-text {
  font-size: 24rpx;
  font-weight: 600;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.change-up {
  background: rgba(255, 59, 48, 0.1);
}
.change-up .change-text {
  color: #ff3b30;
}
.change-down {
  background: rgba(52, 199, 89, 0.1);
}
.change-down .change-text {
  color: #34c759;
}
.change-flat {
  background: rgba(142, 142, 147, 0.1);
}
.change-flat .change-text {
  color: #8e8e93;
}
.change-abs {
  font-size: 20rpx;
  color: #b0b0be;
  margin-top: 2rpx;
  text-align: right;
}

/* ── RS Badge ── */
.rs-badge {
  width: 60rpx;
  height: 44rpx;
  border-radius: 10rpx;
  display: flex;
  align-items: center;
  justify-content: center;
}
.rs-value {
  font-size: 24rpx;
  font-weight: 700;
  color: #ffffff;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.rs-hot {
  background: linear-gradient(135deg, #ff3b30, #ff6b5a);
}
.rs-warm {
  background: linear-gradient(135deg, #ff9500, #ffb340);
}
.rs-normal {
  background: linear-gradient(135deg, #f0b429, #d4981e);
}
.rs-cool {
  background: linear-gradient(135deg, #8e8e93, #a8a8ae);
}

/* ── Empty State ── */
.empty-state {
  display: flex;
  justify-content: center;
  align-items: center;
  padding: 120rpx 0;
  background: #ffffff;
  border-radius: 0 0 16rpx 16rpx;
}
.empty-text {
  font-size: 28rpx;
  color: #b0b0be;
}

/* ── Footer ── */
.site-footer {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 48rpx 0 72rpx;
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
   PC / Tablet 适配 (≥768px)
   ═══════════════════════════════════════════════════════════ */
@media screen and (min-width: 768px) {
  .stocks-container {
    max-width: 860px;
    margin: 0 auto;
    padding: 0 24px;
  }
  .stocks-header {
    padding: 24px 0 12px;
  }
  .stocks-title {
    font-size: 26px;
    letter-spacing: 0.5px;
  }
  .stocks-subtitle {
    font-size: 13px;
    margin-top: 4px;
  }

  /* ── Search Bar (PC) ── */
  .search-bar {
    margin: 8px 0 8px;
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
  .rs-desc {
    margin-top: 8px;
    padding: 10px 14px;
    border-radius: 8px;
    max-height: 40px;
  }
  .rs-desc::after {
    padding: 0 14px 0 30px;
    font-size: 11px;
    line-height: 20px;
  }
  .rs-desc-expanded {
    max-height: 300px;
  }
  .rs-desc-text {
    font-size: 12px;
  }
  .info-bar {
    padding: 8px 0 12px;
  }
  .info-date {
    font-size: 13px;
  }
  .trading-badge {
    gap: 4px;
    padding: 2px 10px;
    border-radius: 12px;
  }
  .trading-dot { font-size: 9px; }
  .trading-text { font-size: 12px; }

  .table-header {
    padding: 12px 16px;
    border-radius: 12px 12px 0 0;
    border-bottom-width: 1px;
  }
  .th { font-size: 12px; }
  .th-rank { width: 36px; }
  .th-name { padding-left: 8px; }
  .th-close { width: 90px; }
  .th-pct { width: 110px; }
  .th-rs { width: 50px; }

  .stock-list {
    border-radius: 0 0 12px 12px;
    box-shadow: 0 1px 12px rgba(0, 0, 0, 0.05);
  }
  .stock-row {
    padding: 14px 16px;
    transition: background-color 0.15s;
  }
  .stock-row:hover {
    background-color: #f5f7fa;
  }

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

  .site-footer {
    padding: 32px 0 48px;
    gap: 6px;
  }
  .footer-icp {
    font-size: 12px;
    cursor: pointer;
  }
  .footer-icp:hover { color: #8c8c9a; }
  .footer-copy { font-size: 12px; }
}
</style>
