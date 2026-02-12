<template>
  <view class="detail-container">
    <!-- Article Header -->
    <view class="article-header">
      <text class="article-title">{{ report.title }}</text>
      <view class="article-meta">
        <text class="article-date">{{ report.date }}</text>
        <text class="article-badge">每日复盘</text>
      </view>
    </view>

    <!-- Divider -->
    <view class="article-divider"></view>

    <!-- Article Content (mp-html) -->
    <view class="article-body">
      <mp-html :content="styledContent" :lazy-load="true" @imgtap="onImageTap" />
    </view>

    <!-- Footer -->
    <view class="article-footer">
      <view class="footer-divider"></view>
      <text class="footer-text">— END —</text>
    </view>

    <view class="safe-bottom"></view>
  </view>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import mpHtml from 'mp-html/dist/uni-app/components/mp-html/mp-html.vue'

// Mock data (same as list page, in production would fetch from API)
const mockReports = [
  {
    id: '20260211',
    title: '2月11日 · 市场回暖信号明显，科技板块领涨',
    date: '2026-02-11',
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
    title: '2月10日 · 缩量震荡整理，资金观望情绪浓',
    date: '2026-02-10',
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
    title: '2月9日 · DeepSeek概念再度爆发，算力龙头涨停潮',
    date: '2026-02-09',
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
]

const report = ref({ title: '', date: '', htmlContent: '' })

// Inject article typography styles into HTML content
const styledContent = computed(() => {
  if (!report.value.htmlContent) return ''
  const css = `
    <style>
      h2 {
        font-size: 18px;
        font-weight: 700;
        color: #1a1a2e;
        margin: 28px 0 12px;
        padding-left: 12px;
        border-left: 3px solid #4285f4;
        line-height: 1.4;
      }
      p {
        font-size: 15px;
        color: #3a3a4a;
        line-height: 1.8;
        margin: 10px 0;
      }
      strong {
        color: #1a1a2e;
        font-weight: 600;
      }
      ul {
        padding-left: 20px;
        margin: 10px 0;
      }
      li {
        font-size: 15px;
        color: #3a3a4a;
        line-height: 1.8;
        margin: 6px 0;
      }
      img {
        max-width: 100%;
        border-radius: 8px;
        margin: 12px 0;
      }
      blockquote {
        margin: 16px 0;
        padding: 12px 16px;
        background: #f5f5f7;
        border-left: 3px solid #4285f4;
        border-radius: 0 8px 8px 0;
        color: #5a5a6e;
        font-size: 14px;
        line-height: 1.7;
      }
    </style>
  `
  return css + report.value.htmlContent
})

const onImageTap = (e) => {
  uni.previewImage({
    urls: [e.src],
    current: e.src
  })
}

onMounted(() => {
  const pages = getCurrentPages()
  const currentPage = pages[pages.length - 1]
  const options = currentPage.$page?.options || currentPage.options || {}
  const id = options.id || ''

  const found = mockReports.find(r => r.id === id)
  if (found) {
    report.value = found
    uni.setNavigationBarTitle({ title: found.date })
  }
})
</script>

<style scoped>
.detail-container {
  min-height: 100vh;
  background: #ffffff;
  padding: 0 32rpx;
}

/* ── Article Header ── */
.article-header {
  padding: 32rpx 0 24rpx;
}
.article-title {
  font-size: 40rpx;
  font-weight: 800;
  color: #1a1a2e;
  line-height: 1.4;
  display: block;
  font-family: 'PingFang SC', 'SF Pro Display', -apple-system, sans-serif;
}
.article-meta {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin-top: 16rpx;
}
.article-date {
  font-size: 24rpx;
  color: #8c8c9a;
}
.article-badge {
  font-size: 22rpx;
  color: #4285f4;
  background: #e8f0fe;
  padding: 4rpx 16rpx;
  border-radius: 8rpx;
  font-weight: 500;
}

/* ── Divider ── */
.article-divider {
  height: 1rpx;
  background: #f0f0f2;
  margin-bottom: 8rpx;
}

/* ── Article Body ── */
.article-body {
  padding: 8rpx 0 32rpx;
}

/* ── Article Footer ── */
.article-footer {
  padding: 32rpx 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16rpx;
}
.footer-divider {
  width: 80rpx;
  height: 2rpx;
  background: #e0e0e6;
}
.footer-text {
  font-size: 24rpx;
  color: #b0b0be;
  letter-spacing: 2rpx;
}

/* ── Safe Bottom ── */
.safe-bottom {
  height: 60rpx;
}

/* ═══════════════════════════════════════════════════════════
   PC / Tablet 适配 (≥768px)
   ═══════════════════════════════════════════════════════════ */
@media screen and (min-width: 768px) {
  .detail-container {
    max-width: 720px;
    margin: 0 auto;
    padding: 0 32px;
  }
  .article-header {
    padding: 28px 0 20px;
  }
  .article-title {
    font-size: 26px;
    line-height: 1.45;
  }
  .article-meta {
    gap: 12px;
    margin-top: 12px;
  }
  .article-date {
    font-size: 13px;
  }
  .article-badge {
    font-size: 12px;
    padding: 2px 10px;
    border-radius: 4px;
  }
  .article-divider {
    height: 1px;
    margin-bottom: 4px;
  }
  .article-body {
    padding: 4px 0 24px;
  }
  .article-footer {
    padding: 24px 0;
    gap: 12px;
  }
  .footer-divider {
    width: 48px;
    height: 1px;
  }
  .footer-text {
    font-size: 13px;
    letter-spacing: 1px;
  }
  .safe-bottom {
    height: 32px;
  }
}
</style>
