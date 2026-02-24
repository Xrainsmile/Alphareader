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
          <!-- 综合评分 -->
          <view class="a-score-section">
            <text class="a-score-label">综合评分：</text>
            <text class="a-score-big" :class="scoreClass(item.score)">{{ item.score.toFixed(1) }}</text>
            <text class="a-score-max">/ 5.0</text>
          </view>

          <!-- 盘面逻辑推演 -->
          <view class="a-logic-section">
            <view class="a-logic-header">
              <view class="a-logic-bar"></view>
              <text class="a-logic-title">盘面逻辑推演</text>
            </view>

            <view class="a-logic-item">
              <text class="a-logic-sub">· 趋势 (TREND)</text>
              <text class="a-logic-text-bold">{{ extractTitle(item.trend) }}</text>
              <text v-if="extractDesc(item.trend)" class="a-logic-text">{{ extractDesc(item.trend) }}</text>
            </view>

            <view class="a-logic-item">
              <text class="a-logic-sub">· 形态 (SETUP)</text>
              <text class="a-logic-text-bold">{{ extractTitle(item.pattern) }}</text>
              <text v-if="extractDesc(item.pattern)" class="a-logic-text">{{ extractDesc(item.pattern) }}</text>
            </view>

            <view class="a-logic-item">
              <text class="a-logic-sub">· 量价 (P&V)</text>
              <text class="a-logic-text-bold">{{ extractTitle(item.volume_price) }}</text>
              <text v-if="extractDesc(item.volume_price)" class="a-logic-text">{{ extractDesc(item.volume_price) }}</text>
            </view>
          </view>

          <!-- 纪律与计划 -->
          <view class="a-discipline-section">
            <view class="a-logic-header">
              <view class="a-logic-bar"></view>
              <text class="a-logic-title">纪律与计划</text>
            </view>

            <view class="a-discipline-content">
              <view class="a-disc-row">
                <view class="discipline-badge" :class="'disc-' + item.discipline_action">
                  <text class="disc-text">{{ disciplineLabel(item.discipline_action) }}</text>
                </view>
                <text class="a-disc-date">{{ formatDate(item.created_at) }}</text>
              </view>

              <!-- 风控 -->
              <view v-if="item.risk_type" class="a-risk-block">
                <view class="risk-tag" :class="'risk-' + item.risk_type">
                  <text class="risk-label">{{ item.risk_type === 'top' ? 'Top' : 'Bottom' }}</text>
                  <text v-if="item.risk_price" class="risk-price">¥{{ item.risk_price }}</text>
                </view>
                <text v-if="item.risk_note" class="a-risk-note">{{ item.risk_note }}</text>
              </view>
            </view>
          </view>

          <!-- 亏盈思考 -->
          <view v-if="item.pnl_thinking" class="a-pnl-section">
            <text class="a-pnl-label">亏盈思考</text>
            <text class="a-pnl-text">{{ item.pnl_thinking }}</text>
          </view>

          <!-- 哨子 Verdict -->
          <view class="a-verdict-section">
            <text class="a-verdict-label">哨子 Verdict</text>
            <text class="a-verdict-text">{{ item.verdict }}</text>
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

const loading = ref(true)
const stock = ref(null)
const analyses = ref([])
const trades = ref([])

const statusLabel = (s) => ({ holding: '持仓', watching: '观察', exited: '退出' }[s] || s)

const disciplineLabel = (d) => ({ retain: '留存', gray: '灰度', research: '用研', churn: '流失' }[d] || d)

const scoreClass = (score) => {
  if (score >= 4) return 'a-score-high'
  if (score >= 2.5) return 'a-score-mid'
  return 'a-score-low'
}

// 从文本中提取标题行（第一句 / 换行前）和描述部分
const extractTitle = (text) => {
  if (!text) return ''
  const parts = text.split(/[，。\n]/)
  return parts[0] || text
}
const extractDesc = (text) => {
  if (!text) return ''
  const idx = text.search(/[，。\n]/)
  if (idx < 0) return ''
  const rest = text.slice(idx + 1).trim()
  return rest || ''
}

const formatDate = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

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
  background: #f0f2f5;
  padding: 0 24rpx 48rpx;
}

.loading-state {
  display: flex;
  justify-content: center;
  padding: 200rpx 0;
}
.loading-text { font-size: 28rpx; color: #b0b0be; }

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
  font-size: 36rpx; font-weight: 800; color: #1a1a2e;
  font-family: 'SF Pro Display', 'PingFang SC', -apple-system, sans-serif;
}
.detail-code {
  font-size: 24rpx; color: #8c8c9a; font-weight: 500;
}
.header-right { display: flex; flex-direction: column; align-items: flex-end; gap: 8rpx; }
.status-badge {
  padding: 6rpx 18rpx; border-radius: 16rpx;
}
.status-text { font-size: 24rpx; font-weight: 600; }
.status-holding { background: #dcfce7; }
.status-holding .status-text { color: #16a34a; }
.status-watching { background: #dbeafe; }
.status-watching .status-text { color: #2563eb; }
.status-exited { background: #f3f4f6; }
.status-exited .status-text { color: #6b7280; }

/* ── Reason Card ── */
.reason-card {
  background: #ffffff;
  border-radius: 16rpx;
  padding: 20rpx 24rpx;
  margin-bottom: 16rpx;
  box-shadow: 0 1rpx 8rpx rgba(0, 0, 0, 0.04);
}
.reason-label { font-size: 22rpx; color: #8c8c9a; font-weight: 600; display: block; margin-bottom: 6rpx; }
.reason-text { font-size: 26rpx; color: #4a4a5a; line-height: 1.6; display: block; }

/* ── Section Header ── */
.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20rpx 4rpx 12rpx;
}
.section-title { font-size: 30rpx; font-weight: 700; color: #1a1a2e; }
.section-count { font-size: 24rpx; color: #b0b0be; }

/* ── Empty Card ── */
.empty-card {
  background: #ffffff;
  border-radius: 16rpx;
  padding: 80rpx 0;
  text-align: center;
  box-shadow: 0 1rpx 8rpx rgba(0, 0, 0, 0.04);
}
.empty-text { font-size: 28rpx; color: #b0b0be; }

/* ═══ Analysis Cards — 设计稿风格 ═══ */
.analysis-list { }
.analysis-card {
  background: #ffffff;
  border-radius: 16rpx;
  padding: 28rpx;
  margin-bottom: 16rpx;
  box-shadow: 0 1rpx 8rpx rgba(0, 0, 0, 0.04);
}

/* 综合评分 */
.a-score-section {
  display: flex; align-items: baseline; gap: 6rpx;
  margin-bottom: 20rpx;
  padding-bottom: 18rpx;
  border-bottom: 1rpx solid #f0f0f2;
}
.a-score-label { font-size: 24rpx; color: #8c8c9a; font-weight: 500; }
.a-score-big {
  font-size: 48rpx; font-weight: 900;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
  line-height: 1;
}
.a-score-high { color: #1a1a2e; }
.a-score-mid { color: #f59e0b; }
.a-score-low { color: #ef4444; }
.a-score-max { font-size: 24rpx; color: #b0b0be; font-weight: 500; }

/* 盘面逻辑推演 */
.a-logic-section {
  margin-bottom: 20rpx;
}
.a-logic-header {
  display: flex; align-items: center; gap: 10rpx;
  margin-bottom: 16rpx;
}
.a-logic-bar {
  width: 6rpx; height: 28rpx; background: #3b82f6; border-radius: 3rpx;
}
.a-logic-title {
  font-size: 28rpx; font-weight: 700; color: #1a1a2e;
}
.a-logic-item {
  padding-left: 16rpx;
  margin-bottom: 16rpx;
}
.a-logic-sub {
  font-size: 22rpx; color: #8c8c9a; font-weight: 500;
  display: block; margin-bottom: 4rpx;
}
.a-logic-text-bold {
  font-size: 28rpx; font-weight: 700; color: #1a1a2e;
  display: block; line-height: 1.4;
}
.a-logic-text {
  font-size: 24rpx; color: #6a6a7a; line-height: 1.6;
  display: block; margin-top: 4rpx;
}

/* 纪律与计划 */
.a-discipline-section {
  margin-bottom: 20rpx;
}
.a-discipline-content {
  padding-left: 16rpx;
}
.a-disc-row {
  display: flex; align-items: center; gap: 12rpx;
  margin-bottom: 10rpx;
}
.discipline-badge { padding: 6rpx 16rpx; border-radius: 10rpx; }
.disc-text { font-size: 24rpx; font-weight: 700; }
.disc-retain { background: rgba(59, 130, 246, 0.1); }
.disc-retain .disc-text { color: #3b82f6; }
.disc-gray { background: rgba(142, 142, 147, 0.1); }
.disc-gray .disc-text { color: #8e8e93; }
.disc-research { background: rgba(168, 85, 247, 0.1); }
.disc-research .disc-text { color: #a855f7; }
.disc-churn { background: rgba(239, 68, 68, 0.1); }
.disc-churn .disc-text { color: #ef4444; }
.a-disc-date { font-size: 22rpx; color: #b0b0be; }

.a-risk-block {
  margin-top: 8rpx;
}
.risk-tag {
  display: inline-flex; align-items: center; gap: 6rpx;
  padding: 6rpx 14rpx; border-radius: 8rpx;
}
.risk-label { font-size: 22rpx; font-weight: 700; }
.risk-price { font-size: 24rpx; font-weight: 700; font-family: 'SF Pro Display', 'DIN Alternate', sans-serif; }
.risk-top { background: rgba(239, 68, 68, 0.08); }
.risk-top .risk-label, .risk-top .risk-price { color: #ef4444; }
.risk-bottom { background: rgba(34, 197, 94, 0.08); }
.risk-bottom .risk-label, .risk-bottom .risk-price { color: #22c55e; }
.a-risk-note {
  font-size: 24rpx; color: #6a6a7a; line-height: 1.6;
  display: block; margin-top: 8rpx;
}

/* 亏盈思考 */
.a-pnl-section {
  background: #f8f9fb; border-radius: 12rpx;
  padding: 16rpx 20rpx; margin-bottom: 16rpx;
}
.a-pnl-label {
  font-size: 22rpx; color: #8c8c9a; font-weight: 600;
  display: block; margin-bottom: 6rpx;
}
.a-pnl-text {
  font-size: 24rpx; color: #4a4a5a; line-height: 1.6; display: block;
}

/* 哨子 Verdict */
.a-verdict-section {
  background: #f0f4ff; border-radius: 12rpx;
  padding: 16rpx 20rpx;
}
.a-verdict-label {
  font-size: 22rpx; color: #3b82f6; font-weight: 600;
  display: block; margin-bottom: 6rpx;
}
.a-verdict-text {
  font-size: 26rpx; color: #1a1a2e; font-weight: 600;
  line-height: 1.5; display: block;
}

/* ── Trade List ── */
.trade-list {
  background: #ffffff;
  border-radius: 16rpx;
  overflow: hidden;
  box-shadow: 0 1rpx 8rpx rgba(0, 0, 0, 0.04);
}
.trade-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20rpx 24rpx;
  border-bottom: 1rpx solid #f0f0f2;
}
.trade-row:last-child { border-bottom: none; }
.trade-left { display: flex; align-items: center; gap: 14rpx; }
.trade-action {
  padding: 6rpx 16rpx; border-radius: 8rpx;
}
.action-text { font-size: 24rpx; font-weight: 700; }
.action-buy { background: rgba(255, 59, 48, 0.1); }
.action-buy .action-text { color: #ff3b30; }
.action-sell { background: rgba(52, 199, 89, 0.1); }
.action-sell .action-text { color: #34c759; }
.trade-info { display: flex; flex-direction: column; }
.trade-date { font-size: 24rpx; color: #4a4a5a; font-weight: 500; }
.trade-note { font-size: 22rpx; color: #b0b0be; margin-top: 2rpx; }
.trade-right { display: flex; flex-direction: column; align-items: flex-end; }
.trade-price {
  font-size: 28rpx; font-weight: 700; color: #1a1a2e;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.trade-shares { font-size: 22rpx; color: #8c8c9a; margin-top: 2rpx; }

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

  .a-logic-bar { width: 3px; height: 16px; }
  .a-logic-title { font-size: 15px; }
  .a-logic-sub { font-size: 12px; }
  .a-logic-text-bold { font-size: 15px; }
  .a-logic-text { font-size: 13px; }
  .a-logic-item { padding-left: 10px; margin-bottom: 10px; }

  .discipline-badge { padding: 3px 12px; border-radius: 6px; }
  .disc-text { font-size: 13px; }
  .a-disc-date { font-size: 12px; }
  .risk-tag { padding: 3px 10px; border-radius: 5px; }
  .risk-label { font-size: 12px; }
  .risk-price { font-size: 13px; }
  .a-risk-note { font-size: 13px; }

  .a-pnl-section { padding: 10px 14px; border-radius: 8px; }
  .a-pnl-label { font-size: 12px; }
  .a-pnl-text { font-size: 13px; }

  .a-verdict-section { padding: 10px 14px; border-radius: 8px; }
  .a-verdict-label { font-size: 12px; }
  .a-verdict-text { font-size: 14px; }

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
