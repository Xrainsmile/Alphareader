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

const meta = ref({})
const htmlContent = ref('')

// 通过 tag-style 属性注入内联样式（能穿透 rich-text 组件）
const tagStyle = {
  h1: 'font-size:22px;font-weight:800;color:#1a1a2e;margin:36px 0 16px;padding:4px 0;line-height:1.5;',
  h2: 'font-size:18px;font-weight:700;color:#1a1a2e;margin:28px 0 14px;padding:4px 0 4px 12px;border-left:3px solid #4285f4;line-height:1.5;',
  h3: 'font-size:16px;font-weight:600;color:#2a2a3e;margin:24px 0 12px;padding:4px 0;line-height:1.5;',
  h4: 'font-size:15px;font-weight:600;color:#3a3a4a;margin:20px 0 10px;padding:2px 0;line-height:1.5;',
  p: 'font-size:15px;color:#3a3a4a;line-height:1.5;margin:16px 0;padding:2px 0;',
  strong: 'color:#1a1a2e;font-weight:600;',
  ul: 'padding-left:20px;margin:16px 0;',
  ol: 'padding-left:20px;margin:16px 0;',
  li: 'font-size:15px;color:#3a3a4a;line-height:1.5;margin:8px 0;padding:2px 0;',
  img: 'max-width:100%;border-radius:8px;margin:16px 0;',
  blockquote: 'margin:20px 0;padding:14px 18px;background:#f7f8fa;border-left:3px solid #4285f4;border-radius:0 8px 8px 0;color:#5a5a6e;font-size:14px;line-height:1.8;',
  hr: 'border:none;border-top:1px solid #eee;margin:28px 0;'
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
}

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
