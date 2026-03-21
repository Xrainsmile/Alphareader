<template>
  <view class="detail-container">
    <!-- Article Header -->
    <view class="article-header" v-if="meta.title">
      <text class="article-title">{{ meta.title }}</text>
      <view class="article-meta">
        <text class="article-date">{{ formatDate(meta.date) }}</text>
        <text class="article-badge">每日复盘</text>
      </view>
    </view>

    <!-- Divider -->
    <view class="article-divider" v-if="meta.title"></view>

    <!-- Article Content (mp-html) -->
    <view class="article-body" v-if="htmlContent">
      <mp-html :content="htmlContent" :tag-style="tagStyle" :lazy-load="true" @imgtap="onImageTap" />
    </view>

    <!-- Loading -->
    <view class="loading-state" v-if="!meta.title">
      <text class="loading-text">加载中...</text>
    </view>

    <!-- Footer -->
    <view class="article-footer" v-if="meta.title">
      <view class="footer-divider"></view>
      <text class="footer-text">— END —</text>
    </view>

    <view class="safe-bottom"></view>
  </view>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import mpHtml from 'mp-html/dist/uni-app/components/mp-html/mp-html.vue'
import { parseFrontMatter, renderMarkdown } from '@/utils/markdown'
import { rawReports } from '@/data/reports'
import { fetchReportDetail } from '@/utils/api'
import { detailTagStyle, formatDate } from '@/utils/formatters'

const meta = ref({})
const htmlContent = ref('')

// 通过 tag-style 属性注入内联样式（从 formatters 导入详情版）
const tagStyle = detailTagStyle

// formatDate imported from formatters.js

const onImageTap = (e) => {
  uni.previewImage({
    urls: [e.src],
    current: e.src
  })
}

onMounted(async () => {
  const pages = getCurrentPages()
  const currentPage = pages[pages.length - 1]
  const options = currentPage.$page?.options || currentPage.options || {}

  // 优先使用 API id 参数
  if (options.id) {
    try {
      const report = await fetchReportDetail(options.id)
      meta.value = {
        title: report.title,
        date: report.date,
        cover: report.cover,
        summary: report.summary
      }
      htmlContent.value = renderMarkdown(report.content)
      uni.setNavigationBarTitle({ title: report.title || '复盘详情' })
      return
    } catch (e) {
      console.warn('API 获取详情失败，尝试本地数据:', e.message)
    }
  }

  // Fallback：本地 Mock 数据（通过 idx 参数）
  const idx = parseInt(options.idx ?? options.id, 10)
  if (!isNaN(idx) && idx >= 0 && idx < rawReports.length) {
    const raw = rawReports[idx]
    const { meta: parsedMeta, content } = parseFrontMatter(raw)
    const html = renderMarkdown(content)

    meta.value = parsedMeta
    htmlContent.value = html
    uni.setNavigationBarTitle({ title: parsedMeta.title || '复盘详情' })
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
.article-title {
  font-size: 40rpx;
  font-weight: 800;
  color: var(--color-text-primary);
  line-height: 1.4;
  display: block;
  font-family: var(--font-display);
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
