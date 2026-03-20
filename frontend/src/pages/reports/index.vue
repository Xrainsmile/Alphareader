<template>
  <view class="reports-container">
    <!-- Header -->
    <view class="reports-header">
      <text class="reports-title">Reports</text>
      <text class="reports-subtitle">每日研报 · 新闻概览 · 每日复盘</text>
    </view>

    <!-- Tab Bar -->
    <view class="tab-bar">
      <view
        class="tab-item"
        :class="{ active: activeTab === 'digest' }"
        @click="switchTab('digest')"
      >
        <text class="tab-text">新闻概览</text>
      </view>
      <view
        class="tab-item"
        :class="{ active: activeTab === 'briefing' }"
        @click="switchTab('briefing')"
      >
        <text class="tab-text">每日研报</text>
      </view>
      <view
        class="tab-item"
        :class="{ active: activeTab === 'reports' }"
        @click="switchTab('reports')"
      >
        <text class="tab-text">复盘</text>
      </view>
      <view class="tab-indicator" :style="{ left: tabIndicatorLeft, width: '33.33%' }"></view>
    </view>

    <!-- ═══════════════════════════════════════════
         Tab 1: 新闻概览（时间轴）
         ═══════════════════════════════════════════ -->
    <view v-if="activeTab === 'digest'" class="digest-tab">
      <!-- Loading -->
      <EmptyState
        v-if="digestLoading"
        text="加载中..."
        mobile-padding="120rpx 0"
        desktop-padding="60px 0"
      />

      <!-- Empty -->
      <EmptyState
        v-if="!digestLoading && digestList.length === 0"
        text="暂无新闻概览"
        mobile-padding="120rpx 0"
        desktop-padding="60px 0"
      />

      <!-- Timeline -->
      <view v-if="!digestLoading && digestList.length > 0" class="timeline">
        <view
          v-for="(item, idx) in digestList"
          :key="item.id"
          class="timeline-item"
        >
          <!-- Timeline connector -->
          <view class="timeline-rail">
            <view class="timeline-dot" :class="'dot-' + item.period_label"></view>
            <view v-if="idx < digestList.length - 1" class="timeline-line"></view>
          </view>

          <!-- Card -->
          <view class="digest-card" @click="expandToggle(item.id)">
            <!-- Card Header -->
            <view class="digest-card-header">
              <view class="digest-badge" :class="'badge-' + item.period_label">
                <text class="badge-icon">{{ item.period_icon }}</text>
                <text class="badge-text">{{ item.period_display }}</text>
              </view>
              <text class="digest-time">{{ formatDigestDate(item) }}</text>
            </view>

            <!-- Card Content (Markdown rendered) -->
            <view class="digest-content" :class="{ collapsed: !expandedIds.has(item.id) }">
              <mp-html :content="renderMd(item.content)" :tag-style="tagStyle" :lazy-load="true" />
            </view>

            <!-- Expand/Collapse toggle -->
            <view class="digest-toggle" v-if="item.content && item.content.length > 100">
              <text class="toggle-text">{{ expandedIds.has(item.id) ? '收起' : '展开全文' }}</text>
              <text class="toggle-arrow">{{ expandedIds.has(item.id) ? '▲' : '▼' }}</text>
            </view>

            <!-- Card Footer -->
            <view class="digest-footer">
              <text class="footer-stat">📊 收录 {{ item.news_count }} 条新闻</text>
            </view>
          </view>
        </view>
      </view>

      <!-- Load more -->
      <view v-if="!digestLoading && digestList.length > 0 && digestDays < 30" class="load-more" @click="loadMoreDigests">
        <text class="load-more-text">加载更多</text>
      </view>
    </view>

    <!-- ═══════════════════════════════════════════
         Tab 2: 每日研报（AI 市场分析）
         ═══════════════════════════════════════════ -->
    <view v-if="activeTab === 'briefing'" class="briefing-tab">
      <!-- Loading -->
      <EmptyState
        v-if="briefingLoading"
        text="加载中..."
        mobile-padding="120rpx 0"
        desktop-padding="60px 0"
      />

      <!-- Empty -->
      <EmptyState
        v-if="!briefingLoading && briefingList.length === 0"
        text="暂无研报数据"
        mobile-padding="120rpx 0"
        desktop-padding="60px 0"
      />

      <!-- Briefing List -->
      <view v-if="!briefingLoading && briefingList.length > 0" class="briefing-list">
        <view
          v-for="item in briefingList"
          :key="item.id"
          class="briefing-card"
          @click="goBriefingDetail(item.id)"
        >
          <!-- Card Header -->
          <view class="briefing-card-header">
            <view class="briefing-date-group">
              <text class="briefing-date-day">{{ formatBriefingDay(item.briefing_date) }}</text>
              <text class="briefing-date-weekday">{{ formatBriefingWeekday(item.briefing_date) }}</text>
            </view>
            <view class="briefing-status" :class="'status-' + item.status">
              <text class="status-dot">●</text>
              <text class="status-text">{{ statusLabel(item.status) }}</text>
            </view>
          </view>

          <!-- Preview Content (first ~100 chars) -->
          <text class="briefing-preview">{{ getPreview(item.content) }}</text>

          <!-- Card Footer: meta stats -->
          <view class="briefing-card-footer">
            <view class="meta-tags">
              <text class="meta-tag" v-if="item.meta && item.meta.vcp_count">VCP {{ item.meta.vcp_count }}</text>
              <text class="meta-tag" v-if="item.meta && item.meta.trend_count">趋势 {{ item.meta.trend_count }}</text>
              <text class="meta-tag" v-if="item.meta && item.meta.value_count">价投 {{ item.meta.value_count }}</text>
            </view>
            <text class="briefing-gen-time" v-if="item.generation_sec">⏱ {{ item.generation_sec.toFixed(1) }}s</text>
          </view>
        </view>
      </view>

      <!-- Load more -->
      <view v-if="!briefingLoading && briefingList.length > 0 && briefingDays < 30" class="load-more" @click="loadMoreBriefings">
        <text class="load-more-text">加载更多</text>
      </view>
    </view>

    <!-- ═══════════════════════════════════════════
         Tab 3: 复盘（原有 Reports 列表）
         ═══════════════════════════════════════════ -->
    <view v-if="activeTab === 'reports'" class="reports-tab">
      <!-- Reports List -->
      <view class="reports-list">
        <view
          v-for="item in reportsList"
          :key="item.id"
          class="report-card"
          @click="goDetail(item.id)"
        >
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
          <view class="card-cover" v-if="item.cover">
            <image class="cover-img" :src="item.cover" mode="aspectFill" lazy-load />
          </view>
        </view>
      </view>

      <!-- Empty State -->
      <EmptyState
        v-if="!reportsLoading && reportsList.length === 0"
        text="暂无复盘报告"
        mobile-padding="120rpx 0"
        desktop-padding="60px 0"
      />

      <!-- Loading State -->
      <EmptyState
        v-if="reportsLoading"
        text="加载中..."
        mobile-padding="120rpx 0"
        desktop-padding="60px 0"
      />
    </view>

    <!-- Footer -->
    <SiteFooter />
  </view>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import mpHtml from 'mp-html/dist/uni-app/components/mp-html/mp-html.vue'
import { fetchReportsList, fetchDigests, fetchBriefings } from '@/utils/api'
import { parseFrontMatter, renderMarkdown } from '@/utils/markdown'
import { rawReports } from '@/data/reports'
import SiteFooter from '@/components/common/SiteFooter.vue'
import EmptyState from '@/components/common/EmptyState.vue'

// ── Tab State ──
const activeTab = ref('briefing')

// ── Tab indicator position (3 tabs) ──
const tabIndicatorLeft = computed(() => {
  if (activeTab.value === 'digest') return '0%'
  if (activeTab.value === 'briefing') return '33.33%'
  return '66.66%'
})

function switchTab(tab) {
  activeTab.value = tab
  // 首次切换时懒加载
  if (tab === 'digest' && digestList.value.length === 0 && !digestLoading.value) {
    loadDigests()
  }
  if (tab === 'briefing' && briefingList.value.length === 0 && !briefingLoading.value) {
    loadBriefings()
  }
  if (tab === 'reports' && reportsList.value.length === 0 && !reportsLoading.value) {
    loadReports()
  }
}

// ── Digest State ──
const digestList = ref([])
const digestLoading = ref(true)
const digestDays = ref(7)
const expandedIds = reactive(new Set())

// ── Reports State ──
const reportsList = ref([])
const reportsLoading = ref(true)

// ── Briefing State ──
const briefingList = ref([])
const briefingLoading = ref(true)
const briefingDays = ref(7)

// Markdown tag styles (for mp-html in digest cards)
const tagStyle = {
  h1: 'font-size:17px;font-weight:700;color:#1a1a2e;margin:12px 0 8px;line-height:1.5;',
  h2: 'font-size:15px;font-weight:600;color:#1a1a2e;margin:10px 0 6px;padding:2px 0 2px 10px;border-left:3px solid #4285f4;line-height:1.5;',
  h3: 'font-size:14px;font-weight:600;color:#2a2a3e;margin:8px 0 4px;line-height:1.5;',
  p: 'font-size:14px;color:#3a3a4a;line-height:1.7;margin:6px 0;',
  strong: 'color:#1a1a2e;font-weight:600;',
  ul: 'padding-left:18px;margin:6px 0;',
  ol: 'padding-left:18px;margin:6px 0;',
  li: 'font-size:14px;color:#3a3a4a;line-height:1.7;margin:4px 0;',
}

// ── Helpers ──

function renderMd(md) {
  if (!md) return ''
  return renderMarkdown(md)
}

function expandToggle(id) {
  if (expandedIds.has(id)) {
    expandedIds.delete(id)
  } else {
    expandedIds.add(id)
  }
}

function formatDigestDate(item) {
  const d = new Date(item.period_start)
  const month = d.getMonth() + 1
  const day = d.getDate()
  // 从 period_end 提取结束时间
  const endD = new Date(item.period_end)
  const startH = String(d.getHours()).padStart(2, '0')
  const startM = String(d.getMinutes()).padStart(2, '0')
  const endH = String(endD.getHours()).padStart(2, '0')
  const endM = String(endD.getMinutes()).padStart(2, '0')
  const endStr = endH === '00' && endM === '00' ? '24:00' : `${endH}:${endM}`
  return `${month}月${day}日 ${startH}:${startM}~${endStr}`
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
}

// ── Data Loading ──

async function loadDigests() {
  digestLoading.value = true
  try {
    const data = await fetchDigests(digestDays.value)
    digestList.value = data || []
    // 自动展开第一条
    if (digestList.value.length > 0 && expandedIds.size === 0) {
      expandedIds.add(digestList.value[0].id)
    }
  } catch (e) {
    console.warn('加载新闻概览失败:', e.message)
    digestList.value = []
  } finally {
    digestLoading.value = false
  }
}

async function loadMoreDigests() {
  digestDays.value = Math.min(digestDays.value + 7, 30)
  await loadDigests()
}

// ── Briefing Helpers ──

function formatBriefingDay(dateStr) {
  const d = new Date(dateStr)
  return `${d.getMonth() + 1}月${d.getDate()}日`
}

function formatBriefingWeekday(dateStr) {
  const d = new Date(dateStr)
  const days = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  return days[d.getDay()]
}

function statusLabel(status) {
  if (status === 'ok') return '已生成'
  if (status === 'failed') return '生成失败'
  if (status === 'empty') return '无数据'
  return status
}

function getPreview(content) {
  if (!content) return '暂无内容'
  // 去除 Markdown 标记，取前 120 个字符
  const plain = content
    .replace(/#{1,6}\s/g, '')
    .replace(/\*{1,2}([^*]+)\*{1,2}/g, '$1')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[-*]\s/g, '')
    .replace(/\n+/g, ' ')
    .trim()
  return plain.length > 120 ? plain.slice(0, 120) + '...' : plain
}

function goBriefingDetail(id) {
  uni.navigateTo({ url: `/pages/briefing/detail?id=${id}` })
}

// ── Briefing Data Loading ──

async function loadBriefings() {
  briefingLoading.value = true
  try {
    const data = await fetchBriefings(briefingDays.value)
    briefingList.value = data || []
  } catch (e) {
    console.warn('加载研报失败:', e.message)
    briefingList.value = []
  } finally {
    briefingLoading.value = false
  }
}

async function loadMoreBriefings() {
  briefingDays.value = Math.min(briefingDays.value + 7, 30)
  await loadBriefings()
}

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

async function loadReports() {
  reportsLoading.value = true
  try {
    const data = await fetchReportsList()
    if (data && data.length > 0) {
      reportsList.value = data
    } else {
      reportsList.value = getLocalReports()
    }
  } catch (e) {
    console.warn('API 不可用，使用本地数据:', e.message)
    reportsList.value = getLocalReports()
  } finally {
    reportsLoading.value = false
  }
}

const goDetail = (id) => {
  const item = reportsList.value.find(r => r.id === id)
  if (item && item._isLocal) {
    uni.navigateTo({ url: `/pages/reports/detail?idx=${id}` })
  } else {
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

onMounted(() => {
  loadBriefings()
})
</script>

<style scoped>
.reports-container {
  min-height: 100vh;
  background: #ffffff;
  padding: 0 32rpx;
}

/* ── Header ── */
.reports-header {
  padding: 36rpx 0 16rpx;
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

/* ── Tab Bar ── */
.tab-bar {
  display: flex;
  position: relative;
  border-bottom: 1rpx solid #f0f0f2;
  margin-bottom: 8rpx;
}
.tab-item {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24rpx 0;
  cursor: pointer;
}
.tab-text {
  font-size: 30rpx;
  color: #8c8c9a;
  font-weight: 500;
  transition: color 0.2s;
}
.tab-item.active .tab-text {
  color: #1a1a2e;
  font-weight: 700;
}
.tab-indicator {
  position: absolute;
  bottom: 0;
  width: 33.33%;
  height: 4rpx;
  background: #4285f4;
  border-radius: 2rpx;
  transition: left 0.25s ease;
}

/* ═══════════════════════════════════
   Digest Tab — Timeline
   ═══════════════════════════════════ */
.digest-tab {
  padding-bottom: 20rpx;
}

.timeline {
  position: relative;
}

.timeline-item {
  display: flex;
  flex-direction: row;
  position: relative;
  padding-bottom: 8rpx;
}

/* Timeline rail (dot + line) */
.timeline-rail {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: 40rpx;
  flex-shrink: 0;
  padding-top: 30rpx;
}

.timeline-dot {
  width: 20rpx;
  height: 20rpx;
  border-radius: 50%;
  background: #4285f4;
  flex-shrink: 0;
  z-index: 1;
}
.dot-morning { background: #FF9800; }
.dot-midday  { background: #F44336; }
.dot-evening { background: #9C27B0; }
.dot-night   { background: #3F51B5; }

.timeline-line {
  width: 3rpx;
  flex: 1;
  background: #e8e8ec;
  margin-top: 4rpx;
}

/* Digest Card */
.digest-card {
  flex: 1;
  margin-left: 16rpx;
  background: #fafbfc;
  border-radius: 16rpx;
  padding: 24rpx;
  border: 1rpx solid #f0f0f2;
  margin-bottom: 20rpx;
  cursor: pointer;
  transition: box-shadow 0.15s;
}

.digest-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16rpx;
}

.digest-badge {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 6rpx 16rpx;
  border-radius: 20rpx;
  background: #e8f0fe;
}
.badge-morning { background: #FFF3E0; }
.badge-midday  { background: #FFEBEE; }
.badge-evening { background: #F3E5F5; }
.badge-night   { background: #E8EAF6; }

.badge-icon {
  font-size: 28rpx;
}
.badge-text {
  font-size: 24rpx;
  font-weight: 600;
  color: #1a1a2e;
}

.digest-time {
  font-size: 22rpx;
  color: #8c8c9a;
  font-family: 'SF Pro Text', -apple-system, sans-serif;
}

/* Content area with collapse */
.digest-content {
  overflow: hidden;
  transition: max-height 0.3s ease;
}
.digest-content.collapsed {
  max-height: 240rpx;
  overflow: hidden;
  -webkit-mask-image: linear-gradient(to bottom, #000 60%, transparent 100%);
  mask-image: linear-gradient(to bottom, #000 60%, transparent 100%);
}

.digest-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8rpx;
  padding: 12rpx 0 4rpx;
}
.toggle-text {
  font-size: 24rpx;
  color: #4285f4;
  font-weight: 500;
}
.toggle-arrow {
  font-size: 20rpx;
  color: #4285f4;
}

.digest-footer {
  display: flex;
  align-items: center;
  padding-top: 12rpx;
  border-top: 1rpx solid #f0f0f2;
  margin-top: 12rpx;
}
.footer-stat {
  font-size: 22rpx;
  color: #8c8c9a;
}

/* Load more */
.load-more {
  display: flex;
  justify-content: center;
  padding: 24rpx 0;
  cursor: pointer;
}
.load-more-text {
  font-size: 26rpx;
  color: #4285f4;
  font-weight: 500;
}

/* ═══════════════════════════════════
   Briefing Tab — 每日研报卡片列表
   ═══════════════════════════════════ */
.briefing-tab {
  padding-bottom: 20rpx;
}

.briefing-list {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.briefing-card {
  background: #fafbfc;
  border-radius: 16rpx;
  padding: 28rpx;
  border: 1rpx solid #f0f0f2;
  cursor: pointer;
  transition: box-shadow 0.15s, transform 0.15s;
}

.briefing-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16rpx;
}

.briefing-date-group {
  display: flex;
  align-items: baseline;
  gap: 12rpx;
}

.briefing-date-day {
  font-size: 32rpx;
  font-weight: 700;
  color: #1a1a2e;
  font-family: 'SF Pro Display', 'PingFang SC', -apple-system, sans-serif;
}

.briefing-date-weekday {
  font-size: 24rpx;
  color: #8c8c9a;
  font-weight: 500;
}

.briefing-status {
  display: flex;
  align-items: center;
  gap: 6rpx;
  padding: 4rpx 16rpx;
  border-radius: 20rpx;
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
.status-dot {
  font-size: 14rpx;
}
.status-ok .status-dot {
  color: #34c759;
}
.status-failed .status-dot {
  color: #ff3b30;
}
.status-empty .status-dot {
  color: #b0b0be;
}
.status-text {
  font-size: 22rpx;
  font-weight: 500;
}
.status-ok .status-text {
  color: #2e7d32;
}
.status-failed .status-text {
  color: #c62828;
}
.status-empty .status-text {
  color: #8c8c9a;
}

.briefing-preview {
  font-size: 26rpx;
  color: #5a5a6e;
  line-height: 1.65;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.briefing-card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 16rpx;
  padding-top: 16rpx;
  border-top: 1rpx solid #f0f0f2;
}

.meta-tags {
  display: flex;
  gap: 12rpx;
  flex-wrap: wrap;
}

.meta-tag {
  font-size: 22rpx;
  color: #4285f4;
  background: #e8f0fe;
  padding: 4rpx 14rpx;
  border-radius: 8rpx;
  font-weight: 500;
}

.briefing-gen-time {
  font-size: 22rpx;
  color: #b0b0be;
  font-family: 'SF Pro Text', -apple-system, sans-serif;
}

/* ═══════════════════════════════════
   Reports Tab
   ═══════════════════════════════════ */
.reports-tab {
  padding-bottom: 20rpx;
}

.reports-list {
  display: flex;
  flex-direction: column;
}

.report-card {
  display: flex;
  flex-direction: row;
  align-items: center;
  padding: 28rpx 0;
  border-bottom: 1rpx solid #f0f0f2;
  cursor: pointer;
  gap: 24rpx;
}

.card-text {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
}

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
    padding: 28px 0 12px;
  }
  .reports-title {
    font-size: 26px;
    letter-spacing: 0.5px;
  }
  .reports-subtitle {
    font-size: 13px;
    margin-top: 4px;
  }

  /* Tab Bar */
  .tab-bar {
    border-bottom-width: 1px;
    margin-bottom: 4px;
  }
  .tab-item {
    padding: 16px 0;
  }
  .tab-text {
    font-size: 15px;
  }
  .tab-indicator {
    height: 2px;
  }

  /* Timeline */
  .timeline-rail {
    width: 24px;
    padding-top: 18px;
  }
  .timeline-dot {
    width: 12px;
    height: 12px;
  }
  .timeline-line {
    width: 2px;
  }

  .digest-card {
    margin-left: 12px;
    padding: 20px;
    border-radius: 12px;
    border-width: 1px;
    margin-bottom: 12px;
  }
  .digest-card:hover {
    box-shadow: 0 2px 12px rgba(0,0,0,0.06);
  }

  .digest-card-header {
    margin-bottom: 12px;
  }
  .digest-badge {
    gap: 6px;
    padding: 4px 12px;
    border-radius: 12px;
  }
  .badge-icon {
    font-size: 14px;
  }
  .badge-text {
    font-size: 13px;
  }
  .digest-time {
    font-size: 12px;
  }

  .digest-content.collapsed {
    max-height: 140px;
  }
  .digest-toggle {
    gap: 4px;
    padding: 8px 0 2px;
  }
  .toggle-text {
    font-size: 13px;
  }
  .toggle-arrow {
    font-size: 11px;
  }
  .digest-footer {
    padding-top: 8px;
    margin-top: 8px;
    border-top-width: 1px;
  }
  .footer-stat {
    font-size: 12px;
  }

  .load-more {
    padding: 16px 0;
  }
  .load-more-text {
    font-size: 14px;
  }

  /* Briefing */
  .briefing-list {
    gap: 12px;
  }
  .briefing-card {
    padding: 20px 24px;
    border-radius: 12px;
    border-width: 1px;
  }
  .briefing-card:hover {
    box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    transform: translateY(-1px);
  }
  .briefing-card-header {
    margin-bottom: 12px;
  }
  .briefing-date-group {
    gap: 8px;
  }
  .briefing-date-day {
    font-size: 17px;
  }
  .briefing-date-weekday {
    font-size: 13px;
  }
  .briefing-status {
    gap: 4px;
    padding: 2px 10px;
    border-radius: 12px;
  }
  .status-dot {
    font-size: 8px;
  }
  .status-text {
    font-size: 12px;
  }
  .briefing-preview {
    font-size: 14px;
    line-height: 1.7;
  }
  .briefing-card-footer {
    margin-top: 12px;
    padding-top: 12px;
    border-top-width: 1px;
  }
  .meta-tags {
    gap: 8px;
  }
  .meta-tag {
    font-size: 12px;
    padding: 2px 8px;
    border-radius: 4px;
  }
  .briefing-gen-time {
    font-size: 12px;
  }

  /* Reports */
  .reports-list {
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
    padding: 0 16px;
  }
  .card-title {
    font-size: 17px;
    line-height: 1.4;
  }
  .card-summary {
    font-size: 13px;
    margin-top: 8px;
    line-height: 1.5;
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
