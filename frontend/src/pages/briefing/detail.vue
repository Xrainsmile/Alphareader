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

      <!-- Meta Stats -->
      <view class="meta-stats" v-if="briefing.meta">
        <view class="stat-item" v-if="briefing.meta.vcp_count">
          <text class="stat-value">{{ briefing.meta.vcp_count }}</text>
          <text class="stat-label">VCP</text>
        </view>
        <view class="stat-item" v-if="briefing.meta.trend_count">
          <text class="stat-value">{{ briefing.meta.trend_count }}</text>
          <text class="stat-label">趋势</text>
        </view>
        <view class="stat-item" v-if="briefing.meta.value_count">
          <text class="stat-value">{{ briefing.meta.value_count }}</text>
          <text class="stat-label">价投</text>
        </view>
        <view class="stat-item" v-if="briefing.meta.digest_count">
          <text class="stat-value">{{ briefing.meta.digest_count }}</text>
          <text class="stat-label">新闻概览</text>
        </view>
        <view class="stat-item" v-if="briefing.meta.quote_count">
          <text class="stat-value">{{ briefing.meta.quote_count }}</text>
          <text class="stat-label">行情</text>
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

const briefing = ref(null)

const htmlContent = computed(() => {
  if (!briefing.value || !briefing.value.content) return ''
  return renderMarkdown(briefing.value.content)
})

// 通过 tag-style 属性注入内联样式（能穿透 rich-text 组件）
const tagStyle = {
  h1: 'font-size:22px;font-weight:800;color:#1a1a2e;margin:36px 0 16px;padding:4px 0;line-height:1.5;',
  h2: 'font-size:18px;font-weight:700;color:#1a1a2e;margin:28px 0 14px;padding:4px 0 4px 12px;border-left:3px solid #4285f4;line-height:1.5;',
  h3: 'font-size:16px;font-weight:600;color:#2a2a3e;margin:24px 0 12px;padding:4px 0;line-height:1.5;',
  h4: 'font-size:15px;font-weight:600;color:#3a3a4a;margin:20px 0 10px;padding:2px 0;line-height:1.5;',
  p: 'font-size:15px;color:#3a3a4a;line-height:1.8;margin:14px 0;padding:2px 0;',
  strong: 'color:#1a1a2e;font-weight:600;',
  ul: 'padding-left:20px;margin:14px 0;',
  ol: 'padding-left:20px;margin:14px 0;',
  li: 'font-size:15px;color:#3a3a4a;line-height:1.8;margin:6px 0;padding:2px 0;',
  table: 'width:100%;border-collapse:collapse;margin:16px 0;font-size:14px;',
  th: 'padding:10px 8px;background:#f7f8fa;border:1px solid #e8e8ed;font-weight:600;color:#1a1a2e;text-align:left;',
  td: 'padding:10px 8px;border:1px solid #e8e8ed;color:#3a3a4a;',
  blockquote: 'margin:20px 0;padding:14px 18px;background:#f7f8fa;border-left:3px solid #4285f4;border-radius:0 8px 8px 0;color:#5a5a6e;font-size:14px;line-height:1.8;',
  hr: 'border:none;border-top:1px solid #eee;margin:28px 0;',
  code: 'background:#f5f5f5;padding:2px 6px;border-radius:4px;font-size:13px;color:#e74c3c;',
}

function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const days = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 ${days[d.getDay()]}`
}

function statusLabel(status) {
  if (status === 'ok') return '已生成'
  if (status === 'failed') return '生成失败'
  if (status === 'empty') return '无数据'
  return status
}

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
  background: #ffffff;
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
  color: #1a1a2e;
  line-height: 1.4;
  font-family: 'PingFang SC', 'SF Pro Display', -apple-system, sans-serif;
}
.status-badge {
  padding: 4rpx 16rpx;
  border-radius: 8rpx;
}
.status-ok {
  background: #e8f5e9;
}
.status-failed {
  background: #FFEBEE;
}
.status-empty {
  background: #f5f5f5;
}
.status-ok .status-text {
  color: #2e7d32;
  font-size: 22rpx;
  font-weight: 500;
}
.status-failed .status-text {
  color: #c62828;
  font-size: 22rpx;
  font-weight: 500;
}
.status-empty .status-text {
  color: #8c8c9a;
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

/* ── Meta Stats ── */
.meta-stats {
  display: flex;
  gap: 24rpx;
  margin-top: 24rpx;
  padding: 20rpx 24rpx;
  background: #f7f8fa;
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
  color: #1a1a2e;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.stat-label {
  font-size: 20rpx;
  color: #8c8c9a;
  margin-top: 4rpx;
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
  color: #8c8c9a;
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
  color: #b0b0be;
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
  color: #b0b0be;
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
