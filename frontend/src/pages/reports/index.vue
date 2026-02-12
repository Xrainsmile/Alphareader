<template>
  <view class="reports-container">
    <!-- Header -->
    <view class="reports-header">
      <text class="reports-title">每日复盘</text>
      <text class="reports-subtitle">Daily Reports · 市场脉搏回顾</text>
    </view>

    <!-- Reports List -->
    <view class="reports-list">
      <view
        v-for="item in reportsList"
        :key="item.id"
        class="report-card"
      >
        <!-- Left: Text -->
        <view class="card-text" @click="goDetail(item.id)">
          <text class="card-title">{{ item.title }}</text>
          <text class="card-summary">{{ item.summary }}</text>
          <view class="card-bottom">
            <text class="card-date">{{ formatDate(item.date) }}</text>
            <view class="card-actions">
              <view class="action-btn" @click.stop="onShare(item)">
                <text class="action-icon">↗</text>
              </view>
              <view class="action-btn action-more" @click.stop>
                <text class="action-icon">···</text>
              </view>
            </view>
          </view>
        </view>

        <!-- Right: Cover Image -->
        <view class="card-cover" @click="goDetail(item.id)">
          <image
            class="cover-img"
            :src="item.cover"
            mode="aspectFill"
            lazy-load
          />
        </view>
      </view>
    </view>

    <!-- Empty State -->
    <view v-if="reportsList.length === 0" class="empty-state">
      <text class="empty-icon">📋</text>
      <text class="empty-text">暂无复盘报告</text>
    </view>

    <!-- Footer -->
    <view class="site-footer">
      <text class="footer-icp" @click="onOpenIcp">蜀ICP备2026006985号</text>
      <text class="footer-copy">© 2026 Rick</text>
    </view>
  </view>
</template>

<script setup>
import { ref } from 'vue'

// Mock data
const reportsList = ref([
  {
    id: '20260211',
    title: '市场回暖信号明显，科技板块领涨',
    date: '2026-02-11',
    summary: 'A股三大指数集体收涨，科技板块表现强势。AI概念股持续走高，半导体板块资金净流入居前。',
    cover: 'https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=400&h=400&fit=crop&q=80',
    htmlContent: `
      <h2>市场概览</h2>
      <p>今日A股三大指数集体收涨，其中<strong>沪指涨1.23%</strong>报3256.78点，深成指涨1.56%，创业板指涨1.89%。两市成交额突破1.2万亿，较昨日放量超20%。</p>
      <h2>板块表现</h2>
      <p>科技板块领涨全市场，AI概念股延续强势表现：</p>
      <ul>
        <li><strong>AI算力</strong>：受DeepSeek催化，算力产业链全线走高</li>
        <li><strong>半导体</strong>：国产替代逻辑持续演绎，板块资金净流入25亿</li>
        <li><strong>消费电子</strong>：苹果供应链回暖带动相关个股反弹</li>
      </ul>
      <h2>资金面</h2>
      <p>北向资金全天净买入<strong>82.5亿元</strong>，主要加仓方向为科技与消费龙头。两融余额继续攀升，显示杠杆资金入场意愿增强。</p>
      <h2>后市展望</h2>
      <p>当前市场量价配合良好，短期有望延续反弹趋势。关注3300点整数关口的突破情况，以及两会政策预期的催化效应。建议重点关注AI产业链和新能源赛道的结构性机会。</p>
    `
  },
  {
    id: '20260210',
    title: '缩量震荡整理，资金观望情绪浓',
    date: '2026-02-10',
    summary: '两市缩量震荡，成交不足万亿。权重股护盘但力度有限，题材股分化明显。市场等待关键经济数据发布。',
    cover: 'https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?w=400&h=400&fit=crop&q=80',
    htmlContent: `
      <h2>市场概览</h2>
      <p>今日A股缩量调整，沪指微跌0.15%报3217.42点。两市成交额仅9200亿，为近10个交易日最低水平。</p>
      <h2>盘面特征</h2>
      <p>市场呈现以下特征：</p>
      <ul>
        <li>权重股小幅护盘，银行、保险板块微涨</li>
        <li>题材股大面积回调，前期强势的AI概念出现分化</li>
        <li>两市涨停家数不足30家，赚钱效应较差</li>
      </ul>
      <h2>关键信号</h2>
      <p>1月社融数据将于本周公布，市场普遍预期信贷开门红，但结构性问题仍受关注。此外，美联储议息纪要也将发布，海外流动性预期或有扰动。</p>
      <h2>操作建议</h2>
      <p>当前位置不宜追高，建议<strong>逢低布局业绩确定性强的优质标的</strong>。重点关注：半导体设备（国产替代加速）、医药创新（集采出清后的估值修复）、高股息品种（防御属性突出）。</p>
    `
  },
  {
    id: '20260209',
    title: 'DeepSeek概念再度爆发，算力龙头涨停潮',
    date: '2026-02-09',
    summary: 'DeepSeek相关利好持续发酵，算力产业链掀涨停潮。光模块、液冷散热、AI芯片等细分赛道资金疯狂涌入。',
    cover: 'https://images.unsplash.com/photo-1518186285589-2f7649de83e0?w=400&h=400&fit=crop&q=80',
    htmlContent: `
      <h2>市场概览</h2>
      <p>AI算力题材全面爆发，带动创业板指大涨2.34%。沪指涨0.87%，两市成交额达1.35万亿，创阶段性新高。</p>
      <h2>核心驱动</h2>
      <p>DeepSeek-V4模型发布引爆市场情绪：</p>
      <ul>
        <li><strong>光模块</strong>：800G需求预期上修，龙头个股集体涨停</li>
        <li><strong>液冷散热</strong>：数据中心功耗提升催生千亿级市场</li>
        <li><strong>AI芯片</strong>：国产算力芯片订单爆满，产业链景气度持续上行</li>
      </ul>
      <h2>市场热度分析</h2>
      <p>AI算力板块<strong>连板股数量达12只</strong>，板块5日平均涨幅超8%，市场热度已接近历史高位。短期需警惕获利盘回吐带来的波动风险。</p>
      <h2>后市研判</h2>
      <p>AI算力中长期逻辑坚实，但短期涨幅过大存在技术性调整需求。建议<strong>分批止盈高位票，关注二线补涨机会</strong>，同时布局AI应用端（教育、医疗、金融）的中期投资逻辑。</p>
    `
  }
])

const formatDate = (dateStr) => {
  const d = new Date(dateStr)
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
}

const goDetail = (id) => {
  uni.navigateTo({
    url: `/pages/reports/detail?id=${id}`
  })
}

const onShare = (item) => {
  // #ifdef H5
  if (navigator.share) {
    navigator.share({
      title: item.title,
      text: item.summary,
      url: window.location.origin + `/pages/reports/detail?id=${item.id}`
    }).catch(() => {})
  } else {
    uni.setClipboardData({
      data: window.location.origin + `/pages/reports/detail?id=${item.id}`,
      success: () => {
        uni.showToast({ title: '链接已复制', icon: 'none' })
      }
    })
  }
  // #endif
  // #ifdef MP-WEIXIN
  // 小程序环境下会触发页面的 onShareAppMessage
  // #endif
}

const onOpenIcp = () => {
  // #ifdef H5
  window.open('https://beian.miit.gov.cn/', '_blank')
  // #endif
}
</script>

<style scoped>
.reports-container {
  min-height: 100vh;
  background: #ffffff;
  padding: 0 32rpx;
}

/* ── Header ── */
.reports-header {
  padding: 36rpx 0 20rpx;
  border-bottom: 1rpx solid #f0f0f2;
  margin-bottom: 8rpx;
}
.reports-title {
  font-size: 44rpx;
  font-weight: 800;
  color: #1a1a2e;
  letter-spacing: 1rpx;
  font-family: 'SF Pro Display', 'PingFang SC', -apple-system, sans-serif;
  display: block;
}
.reports-subtitle {
  font-size: 24rpx;
  color: #8c8c9a;
  margin-top: 6rpx;
  letter-spacing: 1rpx;
  display: block;
}

/* ── Reports List ── */
.reports-list {
  display: flex;
  flex-direction: column;
}

/* ── Report Card ── */
.report-card {
  display: flex;
  align-items: flex-start;
  gap: 24rpx;
  padding: 32rpx 0;
  border-bottom: 1rpx solid #f0f0f2;
}

/* ── Left: Text Area ── */
.card-text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.card-title {
  font-size: 32rpx;
  font-weight: 700;
  color: #1a1a2e;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-family: 'PingFang SC', 'SF Pro Text', -apple-system, sans-serif;
}
.card-summary {
  font-size: 26rpx;
  color: #6b6b7b;
  line-height: 1.55;
  margin-top: 12rpx;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card-bottom {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 20rpx;
}
.card-date {
  font-size: 24rpx;
  color: #b0b0be;
  font-family: 'SF Pro Text', -apple-system, sans-serif;
}
.card-actions {
  display: flex;
  align-items: center;
  gap: 24rpx;
}
.action-btn {
  width: 52rpx;
  height: 52rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  cursor: pointer;
  transition: background-color 0.15s;
}
.action-icon {
  font-size: 28rpx;
  color: #b0b0be;
  font-weight: 500;
}
.action-more .action-icon {
  font-size: 32rpx;
  letter-spacing: -2rpx;
}

/* ── Right: Cover Image ── */
.card-cover {
  flex-shrink: 0;
  width: 180rpx;
  height: 180rpx;
  border-radius: 12rpx;
  overflow: hidden;
  cursor: pointer;
}
.cover-img {
  width: 100%;
  height: 100%;
}

/* ── Empty State ── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 160rpx 0;
  gap: 16rpx;
}
.empty-icon {
  font-size: 64rpx;
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
  .reports-container {
    max-width: 728px;
    margin: 0 auto;
    padding: 0 24px;
  }
  .reports-header {
    padding: 28px 0 16px;
    border-bottom-width: 1px;
    margin-bottom: 4px;
  }
  .reports-title {
    font-size: 26px;
    letter-spacing: 0.5px;
  }
  .reports-subtitle {
    font-size: 13px;
    margin-top: 4px;
  }

  /* Card */
  .report-card {
    gap: 20px;
    padding: 24px 0;
    border-bottom-width: 1px;
    transition: opacity 0.2s;
  }
  .report-card:hover {
    opacity: 0.85;
  }
  .card-title {
    font-size: 20px;
    line-height: 1.35;
    -webkit-line-clamp: 2;
  }
  .card-summary {
    font-size: 14px;
    margin-top: 8px;
    line-height: 1.6;
    -webkit-line-clamp: 2;
  }
  .card-bottom {
    margin-top: 14px;
  }
  .card-date {
    font-size: 13px;
  }
  .card-actions {
    gap: 16px;
  }
  .action-btn {
    width: 32px;
    height: 32px;
  }
  .action-btn:hover {
    background: #f5f5f7;
  }
  .action-icon {
    font-size: 15px;
  }
  .action-more .action-icon {
    font-size: 17px;
  }

  /* Cover */
  .card-cover {
    width: 112px;
    height: 112px;
    border-radius: 8px;
  }

  /* Footer */
  .site-footer {
    padding: 32px 0 48px;
    gap: 6px;
  }
  .footer-icp {
    font-size: 12px;
    cursor: pointer;
  }
  .footer-icp:hover {
    color: #8c8c9a;
  }
  .footer-copy {
    font-size: 12px;
  }
}

@media screen and (min-width: 1200px) {
  .reports-container {
    max-width: 800px;
  }
}
</style>
