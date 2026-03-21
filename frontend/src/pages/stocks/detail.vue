<template>
  <view class="detail-container">
    <!-- Loading -->
    <view v-if="loading" class="loading-state">
      <text class="loading-text">加载中...</text>
    </view>

    <template v-else-if="stock">
      <!-- 股票头部 -->
      <view class="detail-header">
        <view class="header-info">
          <view class="header-name-row">
            <text class="detail-name">{{ stock.name }}</text>
            <text class="detail-code">（{{ stock.ts_code }}）</text>
          </view>
        </view>
        <view class="header-right">
          <view class="status-badge" :class="'status-' + stock.status">
            <text class="status-text">{{ statusLabel(stock.status) }}</text>
          </view>
        </view>
      </view>

      <!-- 加入理由 -->
      <view v-if="stock.reason" class="reason-card">
        <text class="reason-label">加入理由</text>
        <text class="reason-text">{{ stock.reason }}</text>
      </view>

      <!-- 推演卡片流 -->
      <view class="section-header">
        <text class="section-title">推演记录</text>
        <text class="section-count">{{ analyses.length }} 条</text>
      </view>

      <view v-if="analyses.length === 0" class="empty-card">
        <text class="empty-text">暂无推演记录</text>
      </view>

      <view v-else class="analysis-list">
        <view
          v-for="item in analyses"
          :key="item.id"
          class="analysis-card"
        >
          <!-- 时间 + 综合评分 -->
          <view class="a-score-section">
            <view class="a-score-left">
              <text class="a-score-label">综合评分：</text>
              <text class="a-score-big" :class="scoreClass(item.score)">{{ item.score.toFixed(1) }}</text>
              <text class="a-score-max">/ 5.0</text>
            </view>
            <text class="a-created-time">{{ formatDate(item.created_at) }}</text>
          </view>

          <!-- 盘面逻辑推演 -->
          <view class="a-logic-section">
            <view class="a-logic-header">
              <view class="a-logic-bar"></view>
              <text class="a-logic-title">盘面逻辑推演</text>
            </view>

            <!-- 趋势 -->
            <view class="a-block-item">
              <text class="a-block-heading">趋势 (TREND)</text>
              <text class="a-block-body">{{ item.trend }}</text>
            </view>

            <!-- 形态 -->
            <view class="a-block-item">
              <text class="a-block-heading">形态 (SETUP)</text>
              <text class="a-block-body">{{ item.pattern }}</text>
            </view>

            <!-- 量价 -->
            <view class="a-block-item">
              <text class="a-block-heading">量价 (P&V)</text>
              <text class="a-block-body">{{ item.volume_price }}</text>
            </view>

            <!-- 交易计划 Plan -->
            <view v-if="item.plan" class="a-block-item">
              <text class="a-block-heading">交易计划 (PLAN)</text>
              <text class="a-block-body">{{ item.plan }}</text>
            </view>

            <!-- 亏盈思考 -->
            <view v-if="item.pnl_thinking" class="a-block-item">
              <text class="a-block-heading">亏盈思考</text>
              <text class="a-block-body">{{ item.pnl_thinking }}</text>
            </view>

            <!-- 哨子 Verdict -->
            <view class="a-block-item a-block-verdict">
              <text class="a-block-heading">哨子 Verdict</text>
              <text class="a-block-body a-verdict-body">{{ item.verdict }}</text>
            </view>
          </view>
        </view>
      </view>

      <!-- 交易记录 -->
      <view class="section-header">
        <text class="section-title">交易记录</text>
        <text class="section-count">{{ trades.length }} 笔</text>
      </view>

      <view v-if="trades.length === 0" class="empty-card">
        <text class="empty-text">暂无交易记录</text>
      </view>

      <view v-else class="trade-list">
        <view
          v-for="item in trades"
          :key="item.id"
          class="trade-row"
        >
          <view class="trade-left">
            <view class="trade-action" :class="'action-' + item.action">
              <text class="action-text">{{ item.action === 'buy' ? '买入' : '卖出' }}</text>
            </view>
            <view class="trade-info">
              <text class="trade-date">{{ item.trade_date }}</text>
              <text v-if="item.note" class="trade-note">{{ item.note }}</text>
            </view>
          </view>
          <view class="trade-right">
            <text class="trade-price">¥{{ item.price }}</text>
          </view>
        </view>
      </view>
    </template>

    <!-- 错误 -->
    <view v-else class="empty-card" style="margin-top: 60rpx">
      <text class="empty-text">未找到该股票</text>
    </view>
  </view>
</template>

<script setup>
import { ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { fetchSandboxStockDetail } from '@/utils/api'
import { stockStatusLabel, formatDateTime } from '@/utils/formatters'

const loading = ref(true)
const stock = ref(null)
const analyses = ref([])
const trades = ref([])

// statusLabel, formatDate imported from formatters.js
const statusLabel = stockStatusLabel

const scoreClass = (score) => {
  if (score >= 4) return 'a-score-high'
  if (score >= 2.5) return 'a-score-mid'
  return 'a-score-low'
}

const formatDate = formatDateTime

onLoad(async (options) => {
  const id = options?.id
  if (!id) {
    loading.value = false
    return
  }

  // 设置导航标题
  uni.setNavigationBarTitle({ title: '加载中...' })

  try {
    const data = await fetchSandboxStockDetail(id)
    stock.value = data.stock
    analyses.value = data.analyses || []
    trades.value = data.trades || []
    uni.setNavigationBarTitle({ title: `${data.stock.name} ${data.stock.ts_code}` })
  } catch (e) {
    console.error('加载详情失败:', e)
    uni.showToast({ title: '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.detail-container {
  min-height: 100vh;
  background: var(--color-bg);
  padding: 0 24rpx 48rpx;
}

.loading-state {
  display: flex;
  justify-content: center;
  padding: 200rpx 0;
}
.loading-text { font-size: 28rpx; color: var(--color-text-placeholder); }

/* ── Header ── */
.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 24rpx 0 16rpx;
}
.header-info { display: flex; flex-direction: column; }
.header-name-row { display: flex; align-items: baseline; gap: 4rpx; }
.detail-name {
  font-size: 36rpx; font-weight: 800; color: var(--color-text-primary);
  font-family: var(--font-display);
}
.detail-code {
  font-size: 24rpx; color: var(--color-text-muted); font-weight: 500;
}
.header-right { display: flex; flex-direction: column; align-items: flex-end; gap: 8rpx; }
.status-badge {
  padding: 6rpx 18rpx; border-radius: 16rpx;
}
.status-text { font-size: 24rpx; font-weight: 600; }
.status-holding { background: var(--color-bg-success-light); }
.status-holding .status-text { color: var(--color-success-dark); }
.status-watching { background: var(--color-bg-info-light); }
.status-watching .status-text { color: var(--color-info-hover); }
.status-exited { background: var(--color-bg-neutral-light); }
.status-exited .status-text { color: var(--color-neutral); }

/* ── Reason Card ── */
.reason-card {
  background: var(--color-bg-card);
  border-radius: 16rpx;
  padding: 20rpx 24rpx;
  margin-bottom: 16rpx;
  box-shadow: 0 1rpx 8rpx rgba(0, 0, 0, 0.04);
}
.reason-label { font-size: 22rpx; color: var(--color-text-muted); font-weight: 600; display: block; margin-bottom: 6rpx; }
.reason-text { font-size: 26rpx; color: var(--color-text-body); line-height: 1.6; display: block; }

/* ── Section Header ── */
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20rpx 4rpx 12rpx;
}
.section-title { font-size: 30rpx; font-weight: 700; color: var(--color-text-primary); }
.section-count { font-size: 24rpx; color: var(--color-text-placeholder); }

/* ── Empty Card ── */
.empty-card {
  background: var(--color-bg-card);
  border-radius: 16rpx;
  padding: 80rpx 0;
  text-align: center;
  box-shadow: 0 1rpx 8rpx rgba(0, 0, 0, 0.04);
}
.empty-text { font-size: 28rpx; color: var(--color-text-placeholder); }

/* ═══ Analysis Cards — 设计稿风格 ═══ */
.analysis-list { }
.analysis-card {
  background: var(--color-bg-card);
  border-radius: 16rpx;
  padding: 28rpx;
  margin-bottom: 16rpx;
  box-shadow: 0 1rpx 8rpx rgba(0, 0, 0, 0.04);
}

/* 综合评分 */
.a-score-section {
  display: flex; align-items: baseline; justify-content: space-between;
  margin-bottom: 20rpx;
  padding-bottom: 18rpx;
  border-bottom: 1rpx solid var(--color-border-light);
}
.a-score-left { display: flex; align-items: baseline; gap: 6rpx; }
.a-score-label { font-size: 24rpx; color: var(--color-text-muted); font-weight: 500; }
.a-score-big {
  font-size: 48rpx; font-weight: 900;
  font-family: var(--font-numeric);
  line-height: 1;
}
.a-score-high { color: var(--color-text-primary); }
.a-score-mid { color: var(--color-warning-alt); }
.a-score-low { color: var(--color-up-alt); }
.a-score-max { font-size: 24rpx; color: var(--color-text-placeholder); font-weight: 500; }
.a-created-time { font-size: 22rpx; color: var(--color-text-placeholder); white-space: nowrap; }

/* 盘面逻辑推演 */
.a-logic-section {
  margin-bottom: 20rpx;
}
.a-logic-header {
  display: flex; align-items: center; gap: 10rpx;
  margin-bottom: 20rpx;
}
.a-logic-bar {
  width: 6rpx; height: 28rpx; background: var(--color-info); border-radius: 3rpx;
}
.a-logic-title {
  font-size: 28rpx; font-weight: 700; color: var(--color-text-primary);
}

/* 统一的 6 个平行 block 样式 */
.a-block-item {
  margin-bottom: 24rpx;
}
.a-block-item:last-child {
  margin-bottom: 0;
}
.a-block-heading {
  font-size: 28rpx; font-weight: 700; color: var(--color-text-primary);
  display: block; margin-bottom: 8rpx;
}
.a-block-body {
  font-size: 24rpx; color: var(--color-text-hint); line-height: 1.7;
  display: block;
}

/* 哨子 Verdict 特殊背景 */
.a-block-verdict {
  background: var(--color-bg-info-blend); border-radius: 12rpx;
  padding: 16rpx 20rpx;
}
.a-verdict-body {
  color: var(--color-text-primary); font-weight: 600; font-size: 26rpx;
}



/* ── Trade List ── */
.trade-list {
  background: var(--color-bg-card);
  border-radius: 16rpx;
  overflow: hidden;
  box-shadow: 0 1rpx 8rpx rgba(0, 0, 0, 0.04);
}
.trade-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20rpx 24rpx;
  border-bottom: 1rpx solid var(--color-border-light);
}
.trade-row:last-child { border-bottom: none; }
.trade-left { display: flex; align-items: center; gap: 14rpx; }
.trade-action {
  padding: 6rpx 16rpx; border-radius: 8rpx;
}
.action-text { font-size: 24rpx; font-weight: 700; }
.action-buy { background: rgba(255, 59, 48, 0.1); }
.action-buy .action-text { color: var(--color-up); }
.action-sell { background: rgba(52, 199, 89, 0.1); }
.action-sell .action-text { color: var(--color-down); }
.trade-info { display: flex; flex-direction: column; }
.trade-date { font-size: 24rpx; color: var(--color-text-body); font-weight: 500; }
.trade-note { font-size: 22rpx; color: var(--color-text-placeholder); margin-top: 2rpx; }
.trade-right { display: flex; flex-direction: column; align-items: flex-end; }
.trade-price {
  font-size: 28rpx; font-weight: 700; color: var(--color-text-primary);
  font-family: var(--font-numeric);
}
.trade-shares { font-size: 22rpx; color: var(--color-text-muted); margin-top: 2rpx; }

/* ═══ PC 适配 ═══ */
@media screen and (min-width: 768px) {
  .detail-container {
    max-width: 760px;
    margin: 0 auto;
    padding: 0 24px 32px;
  }
  .detail-header { padding: 18px 0 12px; }
  .detail-name { font-size: 22px; }
  .detail-code { font-size: 14px; }
  .status-badge { padding: 3px 12px; border-radius: 10px; }
  .status-text { font-size: 13px; }

  .reason-card { padding: 14px 18px; border-radius: 12px; }
  .reason-label { font-size: 12px; }
  .reason-text { font-size: 14px; }

  .section-header { padding: 16px 0 8px; }
  .section-title { font-size: 17px; }
  .section-count { font-size: 13px; }

  .empty-card { border-radius: 12px; padding: 48px 0; }
  .empty-text { font-size: 15px; }

  .analysis-card { padding: 20px; margin-bottom: 12px; border-radius: 12px; }

  .a-score-label { font-size: 13px; }
  .a-score-big { font-size: 30px; }
  .a-score-max { font-size: 13px; }
  .a-score-section { margin-bottom: 14px; padding-bottom: 12px; }
  .a-created-time { font-size: 12px; }

  .a-logic-bar { width: 3px; height: 16px; }
  .a-logic-title { font-size: 15px; }
  .a-block-heading { font-size: 15px; margin-bottom: 4px; }
  .a-block-body { font-size: 13px; }
  .a-block-item { margin-bottom: 16px; }
  .a-block-verdict { padding: 10px 14px; border-radius: 8px; }
  .a-verdict-body { font-size: 14px; }



  .trade-list { border-radius: 12px; }
  .trade-row { padding: 14px 18px; }
  .trade-action { padding: 3px 12px; border-radius: 5px; }
  .action-text { font-size: 13px; }
  .trade-date { font-size: 13px; }
  .trade-note { font-size: 12px; }
  .trade-price { font-size: 16px; }
  .trade-shares { font-size: 12px; }
}
</style>
