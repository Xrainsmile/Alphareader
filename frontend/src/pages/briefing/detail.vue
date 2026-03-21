<template>
  <view class="detail-container">
    <!-- Article Header -->
    <view class="article-header" v-if="briefing">
      <view class="header-top">
        <text class="article-title">每日研报</text>
        <view class="status-badge" :class="'status-' + briefing.status">
          <text class="status-text">{{ statusLabel(briefing.status) }}</text>
        </view>
      </view>
      <view class="article-meta">
        <text class="article-date">{{ formatDate(briefing.briefing_date) }}</text>
        <text class="article-badge">AI 分析</text>
      </view>

      <!-- Market Sentiment -->
      <view class="sentiment-bar" v-if="briefing.meta && briefing.meta.market_sentiment">
        <text class="sentiment-emoji">{{ sentimentEmoji(briefing.meta.market_sentiment) }}</text>
        <text class="sentiment-text">市场情绪：{{ briefing.meta.market_sentiment }}</text>
      </view>

      <!-- Tier Stats -->
      <view class="meta-stats" v-if="briefing.meta">
        <view class="stat-item tier-s" v-if="briefing.meta.tier_s != null">
          <text class="stat-value">{{ briefing.meta.tier_s }}</text>
          <text class="stat-label">🎯 重点狙击</text>
        </view>
        <view class="stat-item tier-a" v-if="briefing.meta.tier_a != null">
          <text class="stat-value">{{ briefing.meta.tier_a }}</text>
          <text class="stat-label">📋 常规盯防</text>
        </view>
        <view class="stat-item tier-x" v-if="briefing.meta.tier_x != null">
          <text class="stat-value">{{ briefing.meta.tier_x }}</text>
          <text class="stat-label">⚠️ 风险剔除</text>
        </view>
        <view class="stat-item" v-if="briefing.meta.pool_count">
          <text class="stat-value">{{ briefing.meta.pool_count }}</text>
          <text class="stat-label">📊 股票池</text>
        </view>
      </view>
    </view>

    <!-- Divider -->
    <view class="article-divider" v-if="briefing"></view>

    <!-- Article Content (mp-html) -->
    <view class="article-body" v-if="briefing && briefing.content">
      <mp-html :content="htmlContent" :tag-style="tagStyle" :lazy-load="true" />
    </view>

    <!-- Failed State -->
    <view class="failed-state" v-if="briefing && briefing.status === 'failed'">
      <text class="failed-icon">⚠️</text>
      <text class="failed-text">本日研报生成失败，请稍后重试</text>
    </view>

    <!-- Loading -->
    <view class="loading-state" v-if="!briefing">
      <text class="loading-text">加载中...</text>
    </view>

    <!-- Footer -->
    <view class="article-footer" v-if="briefing">
      <view class="footer-info" v-if="briefing.generation_sec">
        <text class="footer-detail">生成耗时 {{ briefing.generation_sec.toFixed(1) }} 秒</text>
        <text class="footer-detail" v-if="briefing.prompt_tokens_est"> · 约 {{ briefing.prompt_tokens_est }} tokens</text>
      </view>
      <view class="footer-divider"></view>
      <text class="footer-text">— END —</text>
    </view>

    <view class="safe-bottom"></view>
  </view>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import mpHtml from 'mp-html/dist/uni-app/components/mp-html/mp-html.vue'
import { renderMarkdown } from '@/utils/markdown'
import { fetchBriefingDetail } from '@/utils/api'
import { detailTagStyle, formatDateWithWeekday, reportStatusLabel, sentimentEmoji } from '@/utils/formatters'

const briefing = ref(null)

const htmlContent = computed(() => {
  if (!briefing.value || !briefing.value.content) return ''
  return renderMarkdown(briefing.value.content)
})

// 通过 tag-style 属性注入内联样式（从 formatters 导入详情版）
const tagStyle = detailTagStyle

// formatDate/statusLabel/sentimentEmoji imported from formatters.js
const formatDate = formatDateWithWeekday
const statusLabel = reportStatusLabel

onMounted(async () => {
  const pages = getCurrentPages()
  const currentPage = pages[pages.length - 1]
  const options = currentPage.$page?.options || currentPage.options || {}

  if (options.id) {
    try {
      const data = await fetchBriefingDetail(options.id)
      briefing.value = data
      // 设置导航栏标题
      const dateStr = data.briefing_date ? formatDate(data.briefing_date) : '每日研报'
      uni.setNavigationBarTitle({ title: dateStr })
    } catch (e) {
      console.warn('获取研报详情失败:', e.message)
      uni.showToast({ title: '加载失败', icon: 'none' })
    }
  }
})
</script>

<style scoped>
.detail-container {
  min-height: 100vh;
  background: var(--color-bg-card);
  padding: 0 32rpx;
}

/* ── Article Header ── */
.article-header {
  padding: 32rpx 0 24rpx;
}
.header-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.article-title {
  font-size: 40rpx;
  font-weight: 800;
  color: var(--color-text-primary);
  line-height: 1.4;
  font-family: var(--font-display);
}
.status-badge {
  padding: 4rpx 16rpx;
  border-radius: 8rpx;
}
.status-ok {
  background: var(--color-bg-success-soft);
}
.status-failed {
  background: var(--color-bg-danger-light);
}
.status-empty {
  background: var(--color-bg-neutral-soft);
}
.status-ok .status-text {
  color: var(--color-success-text);
  font-size: 22rpx;
  font-weight: 500;
}
.status-failed .status-text {
  color: var(--color-danger-dark);
  font-size: 22rpx;
  font-weight: 500;
}
.status-empty .status-text {
  color: var(--color-text-muted);
  font-size: 22rpx;
  font-weight: 500;
}

.article-meta {
  display: flex;
  align-items: center;
  gap: 16rpx;
  margin-top: 16rpx;
}
.article-date {
  font-size: 24rpx;
  color: var(--color-text-muted);
}
.article-badge {
  font-size: 22rpx;
  color: var(--color-brand);
  background: var(--color-bg-info-soft);
  padding: 4rpx 16rpx;
  border-radius: 8rpx;
  font-weight: 500;
}

/* ── Sentiment Bar ── */
.sentiment-bar {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-top: 20rpx;
  padding: 16rpx 24rpx;
  background: var(--gradient-briefing-bg);
  border-radius: 12rpx;
}
.sentiment-emoji {
  font-size: 32rpx;
}
.sentiment-text {
  font-size: 26rpx;
  font-weight: 600;
  color: var(--color-text-primary);
}

/* ── Meta Stats ── */
.meta-stats {
  display: flex;
  gap: 24rpx;
  margin-top: 24rpx;
  padding: 20rpx 24rpx;
  background: var(--color-bg-section);
  border-radius: 12rpx;
}
.stat-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
}
.stat-value {
  font-size: 36rpx;
  font-weight: 700;
  color: var(--color-text-primary);
  font-family: var(--font-numeric);
}
.stat-label {
  font-size: 20rpx;
  color: var(--color-text-muted);
  margin-top: 4rpx;
}
.tier-s .stat-value {
  color: var(--color-warning);
}
.tier-a .stat-value {
  color: var(--color-text-primary);
}
.tier-x .stat-value {
  color: var(--color-danger-dark);
}

/* ── Divider ── */
.article-divider {
  height: 1rpx;
  background: var(--color-border-light);
  margin-bottom: 8rpx;
}

/* ── Article Body ── */
.article-body {
  padding: 8rpx 0 32rpx;
}

/* ── Failed State ── */
.failed-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 120rpx 0;
  gap: 16rpx;
}
.failed-icon {
  font-size: 60rpx;
}
.failed-text {
  font-size: 28rpx;
  color: var(--color-text-muted);
}

/* ── Loading ── */
.loading-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 200rpx 0;
}
.loading-text {
  font-size: 28rpx;
  color: var(--color-text-placeholder);
}

/* ── Article Footer ── */
.article-footer {
  padding: 32rpx 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16rpx;
}
.footer-info {
  display: flex;
  align-items: center;
}
.footer-detail {
  font-size: 22rpx;
  color: var(--color-text-placeholder);
}
.footer-divider {
  width: 80rpx;
  height: 2rpx;
  background: var(--color-border-divider);
}
.footer-text {
  font-size: 24rpx;
  color: var(--color-text-placeholder);
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
  .status-badge {
    padding: 2px 10px;
    border-radius: 4px;
  }
  .status-ok .status-text,
  .status-failed .status-text,
  .status-empty .status-text {
    font-size: 12px;
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

  /* Sentiment Bar */
  .sentiment-bar {
    gap: 8px;
    margin-top: 14px;
    padding: 10px 16px;
    border-radius: 8px;
  }
  .sentiment-emoji {
    font-size: 18px;
  }
  .sentiment-text {
    font-size: 14px;
  }

  /* Meta Stats */
  .meta-stats {
    gap: 16px;
    margin-top: 16px;
    padding: 14px 20px;
    border-radius: 8px;
  }
  .stat-value {
    font-size: 20px;
  }
  .stat-label {
    font-size: 11px;
    margin-top: 2px;
  }

  .article-divider {
    height: 1px;
    margin-bottom: 4px;
  }
  .article-body {
    padding: 4px 0 24px;
  }

  /* Failed */
  .failed-state {
    padding: 80px 0;
    gap: 12px;
  }
  .failed-icon {
    font-size: 36px;
  }
  .failed-text {
    font-size: 15px;
  }

  /* Footer */
  .article-footer {
    padding: 24px 0;
    gap: 12px;
  }
  .footer-detail {
    font-size: 12px;
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
