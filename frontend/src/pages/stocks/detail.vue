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
          <text class="detail-name">{{ stock.name }}</text>
          <text class="detail-code">{{ stock.ts_code }}</text>
        </view>
        <view class="header-right">
          <view class="status-badge" :class="'status-' + stock.status">
            <text class="status-text">{{ statusLabel(stock.status) }}</text>
          </view>
          <view v-if="stock.net_shares > 0" class="shares-info">
            <text class="shares-text">持仓 {{ stock.net_shares }} 股</text>
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
          :class="{ 'analysis-expanded': expandedId === item.id }"
          @click="toggleExpand(item.id)"
        >
          <!-- 头部：评分 + 动作 + 时间 -->
          <view class="analysis-top">
            <view class="analysis-score-row">
              <view class="score-badge" :class="scoreClass(item.score)">
                <text class="score-text">{{ item.score.toFixed(1) }}</text>
              </view>
              <view class="discipline-badge" :class="'disc-' + item.discipline_action">
                <text class="disc-text">{{ disciplineLabel(item.discipline_action) }}</text>
              </view>
            </view>
            <text class="analysis-date">{{ formatDate(item.created_at) }}</text>
          </view>

          <!-- 哨子 Verdict（始终显示） -->
          <text class="analysis-verdict">{{ item.verdict }}</text>

          <!-- 风控标签 -->
          <view v-if="item.risk_type" class="risk-row">
            <view class="risk-tag" :class="'risk-' + item.risk_type">
              <text class="risk-label">{{ item.risk_type === 'top' ? 'Top' : 'Bottom' }}</text>
              <text v-if="item.risk_price" class="risk-price">¥{{ item.risk_price }}</text>
            </view>
          </view>

          <!-- 展开详情 -->
          <view v-if="expandedId === item.id" class="analysis-detail">
            <view class="detail-item">
              <text class="detail-label">趋势判断</text>
              <text class="detail-text">{{ item.trend }}</text>
            </view>
            <view class="detail-item">
              <text class="detail-label">形态识别</text>
              <text class="detail-text">{{ item.pattern }}</text>
            </view>
            <view class="detail-item">
              <text class="detail-label">量价行为</text>
              <text class="detail-text">{{ item.volume_price }}</text>
            </view>
            <view v-if="item.risk_note" class="detail-item">
              <text class="detail-label">风控说明</text>
              <text class="detail-text">{{ item.risk_note }}</text>
            </view>
            <view class="detail-item">
              <text class="detail-label">亏盈思考</text>
              <text class="detail-text">{{ item.pnl_thinking }}</text>
            </view>
          </view>
          <view class="expand-hint">
            <text class="expand-text">{{ expandedId === item.id ? '收起' : '展开详情' }}</text>
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
            <text class="trade-shares">× {{ item.shares }} 股</text>
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
const expandedId = ref(null)

const statusLabel = (s) => ({ holding: '持仓', watching: '观察', exited: '退出' }[s] || s)

const disciplineLabel = (d) => ({ retain: '留存', gray: '灰度', research: '用研', churn: '流失' }[d] || d)

const scoreClass = (score) => {
  if (score >= 4) return 'score-high'
  if (score >= 2.5) return 'score-mid'
  return 'score-low'
}

const formatDate = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

const toggleExpand = (id) => {
  expandedId.value = expandedId.value === id ? null : id
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
  align-items: flex-start;
  padding: 24rpx 0 16rpx;
}
.header-info { display: flex; flex-direction: column; }
.detail-name {
  font-size: 40rpx; font-weight: 800; color: #1a1a2e;
  font-family: 'SF Pro Display', 'PingFang SC', -apple-system, sans-serif;
}
.detail-code {
  font-size: 24rpx; color: #b0b0be; margin-top: 4rpx;
  font-family: 'SF Mono', 'Menlo', monospace;
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
.shares-info { }
.shares-text { font-size: 22rpx; color: #8c8c9a; }

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

/* ── Analysis Cards ── */
.analysis-list { }
.analysis-card {
  background: #ffffff;
  border-radius: 16rpx;
  padding: 24rpx;
  margin-bottom: 12rpx;
  box-shadow: 0 1rpx 8rpx rgba(0, 0, 0, 0.04);
  cursor: pointer;
  transition: box-shadow 0.15s;
}
.analysis-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10rpx;
}
.analysis-score-row { display: flex; align-items: center; gap: 10rpx; }

.score-badge {
  padding: 4rpx 16rpx; border-radius: 10rpx;
  min-width: 52rpx; text-align: center;
}
.score-text { font-size: 26rpx; font-weight: 800; color: #fff; }
.score-high { background: #22c55e; }
.score-mid { background: #f59e0b; }
.score-low { background: #ef4444; }

.discipline-badge { padding: 4rpx 14rpx; border-radius: 8rpx; }
.disc-text { font-size: 22rpx; font-weight: 600; }
.disc-retain { background: rgba(59, 130, 246, 0.1); }
.disc-retain .disc-text { color: #3b82f6; }
.disc-gray { background: rgba(142, 142, 147, 0.1); }
.disc-gray .disc-text { color: #8e8e93; }
.disc-research { background: rgba(168, 85, 247, 0.1); }
.disc-research .disc-text { color: #a855f7; }
.disc-churn { background: rgba(239, 68, 68, 0.1); }
.disc-churn .disc-text { color: #ef4444; }

.analysis-date { font-size: 22rpx; color: #b0b0be; }

.analysis-verdict {
  font-size: 28rpx; font-weight: 600; color: #1a1a2e;
  line-height: 1.5; display: block; margin-bottom: 6rpx;
}

.risk-row { display: flex; gap: 10rpx; margin-top: 8rpx; }
.risk-tag {
  display: flex; align-items: center; gap: 6rpx;
  padding: 6rpx 14rpx; border-radius: 8rpx;
}
.risk-label { font-size: 22rpx; font-weight: 700; }
.risk-price { font-size: 24rpx; font-weight: 700; font-family: 'SF Pro Display', 'DIN Alternate', sans-serif; }
.risk-top { background: rgba(239, 68, 68, 0.08); }
.risk-top .risk-label, .risk-top .risk-price { color: #ef4444; }
.risk-bottom { background: rgba(34, 197, 94, 0.08); }
.risk-bottom .risk-label, .risk-bottom .risk-price { color: #22c55e; }

.analysis-detail {
  margin-top: 16rpx;
  padding-top: 16rpx;
  border-top: 1rpx solid #f0f0f2;
}
.detail-item { margin-bottom: 14rpx; }
.detail-label {
  font-size: 22rpx; color: #8c8c9a; font-weight: 600; display: block; margin-bottom: 4rpx;
}
.detail-text {
  font-size: 26rpx; color: #4a4a5a; line-height: 1.6; display: block;
}

.expand-hint {
  margin-top: 10rpx;
  text-align: center;
}
.expand-text { font-size: 22rpx; color: #4285f4; font-weight: 500; }

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
  .detail-name { font-size: 24px; }
  .detail-code { font-size: 13px; }
  .status-badge { padding: 3px 12px; border-radius: 10px; }
  .status-text { font-size: 13px; }
  .shares-text { font-size: 12px; }

  .reason-card { padding: 14px 18px; border-radius: 12px; }
  .reason-label { font-size: 12px; }
  .reason-text { font-size: 14px; }

  .section-header { padding: 16px 0 8px; }
  .section-title { font-size: 17px; }
  .section-count { font-size: 13px; }

  .empty-card { border-radius: 12px; padding: 48px 0; }
  .empty-text { font-size: 15px; }

  .analysis-card { padding: 18px; margin-bottom: 8px; border-radius: 12px; }
  .analysis-card:hover { box-shadow: 0 2px 16px rgba(0, 0, 0, 0.08); }
  .score-badge { padding: 2px 10px; border-radius: 6px; min-width: 32px; }
  .score-text { font-size: 14px; }
  .discipline-badge { padding: 2px 10px; border-radius: 5px; }
  .disc-text { font-size: 12px; }
  .analysis-date { font-size: 12px; }
  .analysis-verdict { font-size: 15px; }
  .risk-tag { padding: 3px 10px; border-radius: 5px; }
  .risk-label { font-size: 12px; }
  .risk-price { font-size: 13px; }
  .detail-label { font-size: 12px; }
  .detail-text { font-size: 14px; }
  .expand-text { font-size: 12px; }

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
