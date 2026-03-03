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
        @click="goDetail(item.id)"
      >
        <!-- Text Area (left) -->
        <view class="card-text">
          <text class="card-title">{{ item.title }}</text>
          <text class="card-summary">{{ item.summary }}</text>
          <view class="card-bottom">
            <text class="card-date">{{ formatDate(item.date) }}</text>
            <view class="card-actions">
              <view class="action-btn" @click.stop="onShare(item)">
                <text class="action-icon">↗</text>
              </view>
            </view>
          </view>
        </view>

        <!-- Cover Image (right, small) -->
        <view class="card-cover" v-if="item.cover">
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
    <EmptyState
      v-if="!loading && reportsList.length === 0"
      text="暂无复盘报告"
      mobile-padding="160rpx 0"
      desktop-padding="80px 0"
    />

    <!-- Loading State -->
    <EmptyState
      v-if="loading"
      text="加载中..."
      mobile-padding="160rpx 0"
      desktop-padding="80px 0"
    />

    <!-- Footer -->
    <SiteFooter />
  </view>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { fetchReportsList } from '@/utils/api'
import { parseFrontMatter } from '@/utils/markdown'
import { rawReports } from '@/data/reports'
import SiteFooter from '@/components/common/SiteFooter.vue'
import EmptyState from '@/components/common/EmptyState.vue'

const reportsList = ref([])
const loading = ref(true)

// 从 Mock 数据生成 fallback 列表
function getLocalReports() {
  return rawReports.map((raw, idx) => {
    const { meta } = parseFrontMatter(raw)
    return {
      id: idx,
      sync_id: `local-${idx}`,
      title: meta.title || '无标题',
      date: meta.date || '',
      cover: meta.cover || '',
      summary: meta.summary || '',
      _isLocal: true
    }
  })
}

onMounted(async () => {
  try {
    const data = await fetchReportsList()
    if (data && data.length > 0) {
      reportsList.value = data
    } else {
      // API 返回空 → 用本地 Mock
      reportsList.value = getLocalReports()
    }
  } catch (e) {
    console.warn('API 不可用，使用本地数据:', e.message)
    reportsList.value = getLocalReports()
  } finally {
    loading.value = false
  }
})

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
}

const goDetail = (id) => {
  const item = reportsList.value.find(r => r.id === id)
  if (item && item._isLocal) {
    // 本地 Mock 模式：传 idx
    uni.navigateTo({ url: `/pages/reports/detail?idx=${id}` })
  } else {
    // API 模式：传 report id
    uni.navigateTo({ url: `/pages/reports/detail?id=${id}` })
  }
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

/* ── Report Card (横向布局：左文字 右封面) ── */
.report-card {
  display: flex;
  flex-direction: row;
  align-items: center;
  padding: 28rpx 0;
  border-bottom: 1rpx solid #f0f0f2;
  cursor: pointer;
  gap: 24rpx;
}

/* ── Text Area (占满剩余空间) ── */
.card-text {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

/* ── Cover Image (右侧小图) ── */
.card-cover {
  width: 112rpx;
  height: 112rpx;
  border-radius: 12rpx;
  overflow: hidden;
  flex-shrink: 0;
}
.cover-img {
  width: 100%;
  height: 100%;
}
.card-title {
  font-size: 34rpx;
  font-weight: 700;
  color: #1a1a2e;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-family: 'PingFang SC', 'SF Pro Text', -apple-system, sans-serif;
}
.card-summary {
  font-size: 26rpx;
  color: #6b6b7b;
  line-height: 1.6;
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
  margin-top: 16rpx;
}
.card-date {
  font-size: 24rpx;
  color: #b0b0be;
  font-family: 'SF Pro Text', -apple-system, sans-serif;
}
.card-actions {
  display: flex;
  align-items: center;
}
.action-btn {
  width: 52rpx;
  height: 52rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  transition: background-color 0.15s;
}
.action-icon {
  font-size: 28rpx;
  color: #b0b0be;
  font-weight: 500;
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

  /* Card - PC 端保持横向布局 */
  .reports-list {
    display: flex;
    flex-direction: column;
    margin-top: 8px;
  }
  .report-card {
    padding: 20px 0;
    border-bottom: 1px solid #f0f0f2;
    gap: 20px;
    transition: background-color 0.15s;
  }
  .report-card:hover {
    background-color: #fafafa;
  }
  .card-cover {
    width: 70px;
    height: 70px;
    border-radius: 8px;
  }
  .card-text {
    padding: 16px;
  }
  .card-title {
    font-size: 17px;
    line-height: 1.4;
    -webkit-line-clamp: 2;
  }
  .card-summary {
    font-size: 13px;
    margin-top: 8px;
    line-height: 1.5;
    -webkit-line-clamp: 2;
  }
  .card-bottom {
    margin-top: 12px;
  }
  .card-date {
    font-size: 12px;
  }
  .action-btn {
    width: 28px;
    height: 28px;
  }
  .action-btn:hover {
    background: #eee;
  }
  .action-icon {
    font-size: 14px;
  }

}

@media screen and (min-width: 1200px) {
  .reports-container {
    max-width: 800px;
  }
}
</style>
