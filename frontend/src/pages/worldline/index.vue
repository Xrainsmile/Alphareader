<template>
  <view class="page-layout">
    <PcSidebar active="worldline" />
    <view class="container">

      <!-- Header -->
      <view class="wl-header">
        <view class="wl-head-info">
          <text class="wl-title">世界线工作台</text>
          <text class="wl-subtitle">连续追踪事件演化，识别异动与传导路径。</text>
        </view>
        <view v-if="meta" class="wl-health">
          <text class="wl-health-item">{{ meta.data_health.threads }} 条世界线</text>
          <text class="wl-health-sep">·</text>
          <text class="wl-health-item">{{ meta.data_health.chapters }} 个章节</text>
          <text class="wl-health-sep">·</text>
          <text class="wl-health-item">{{ meta.data_health.entities }} 个实体</text>
        </view>
      </view>

      <!-- 数据状态提示：传导链/观察点未启用时明确告知，而非静默空卡片 -->
      <view v-if="meta && !meta.data_health.transmission_enabled" class="wl-notice">
        <text class="wl-notice-text">投资传导链尚未生成（数据库 0 条）。传导链需由归线后的人工或 LLM 分析建立，当前仅展示结构占位。</text>
      </view>

      <!-- Tab 切换 -->
      <view class="wl-tabs">
        <view
          v-for="t in tabs"
          :key="t.key"
          class="wl-tab"
          :class="{ 'wl-tab-on': activeTab === t.key }"
          @click="switchTab(t.key)"
        >
          <text class="wl-tab-text">{{ t.label }}</text>
        </view>
      </view>

      <!-- ══════════ 世界线连续追踪 ══════════ -->
      <view v-if="activeTab === 'threads'" class="wl-panel">
        <view class="wl-filter">
          <input
            v-model="threadQuery"
            class="wl-input"
            placeholder="搜索世界线标题 / 标的 / 实体"
            placeholder-class="wl-input-ph"
            confirm-type="search"
            @confirm="loadThreads"
          />
          <view class="wl-sort">
            <view
              v-for="s in sortOptions"
              :key="s.value"
              class="wl-sort-item"
              :class="{ 'wl-sort-on': threadSort === s.value }"
              @click="pickSort(s.value)"
            >
              <text class="wl-sort-text">{{ s.label }}</text>
            </view>
          </view>
        </view>

        <view v-if="threadLoading" class="wl-loading">
          <text class="wl-loading-text">加载中…</text>
        </view>
        <EmptyState v-else-if="threadError" :text="threadError" />
        <EmptyState v-else-if="!threads.length" text="暂无世界线，等待事件归线后生成" />
        <view v-else class="wl-list">
          <view
            v-for="t in threads"
            :key="t.id"
            class="wl-card"
            @click="goThread(t.id)"
          >
            <view class="wl-card-head">
              <text class="wl-card-title">{{ t.title }}</text>
              <text class="wl-badge" :class="'wl-badge-' + t.status">{{ t.status_label }}</text>
            </view>

            <view class="wl-card-meta">
              <text class="wl-meta-num">{{ t.chapter_count }}</text>
              <text class="wl-meta-unit">章节</text>
              <text v-if="t.last_event_at" class="wl-meta-time">· {{ fmtDate(t.last_event_at) }}</text>
              <text v-if="t.transmission_count" class="wl-meta-tx">· {{ t.transmission_count }} 条传导链</text>
            </view>

            <view v-if="t.core_entities && t.core_entities.length" class="wl-chips">
              <text v-for="(en, i) in t.core_entities.slice(0, 5)" :key="i" class="wl-chip">{{ en }}</text>
            </view>

            <view v-if="t.latest_chapters && t.latest_chapters.length" class="wl-latest">
              <text class="wl-latest-label">最新章节</text>
              <text class="wl-latest-text">{{ t.latest_chapters[0].title }}</text>
            </view>
          </view>
        </view>

        <view v-if="threadTotal > threads.length" class="wl-more" @click="loadMoreThreads">
          <text class="wl-more-text">加载更多</text>
        </view>
      </view>

      <!-- ══════════ 世界线异动雷达 ══════════ -->
      <view v-else-if="activeTab === 'radar'" class="wl-panel">
        <view class="wl-filter">
          <view class="wl-window">
            <view
              v-for="w in windows"
              :key="w.days"
              class="wl-win-item"
              :class="{ 'wl-win-on': radarDays === w.days }"
              @click="pickWindow(w.days)"
            >
              <text class="wl-win-text">{{ w.label }}</text>
            </view>
          </view>
          <text class="wl-window-hint">按窗口内事件变化量 × 质量信号排序</text>
        </view>

        <view v-if="radarLoading" class="wl-loading">
          <text class="wl-loading-text">计算中…</text>
        </view>
        <EmptyState v-else-if="radarError" :text="radarError" />
        <EmptyState v-else-if="!radar.length" :text="radarWindowLabel + '内无多章世界线异动'" />
        <view v-else class="wl-radar">
          <view
            v-for="r in radar"
            :key="r.id"
            class="wl-radar-item"
            @click="goThread(r.id)"
          >
            <text class="wl-radar-rank">{{ r.rank }}</text>
            <view class="wl-radar-body">
              <text class="wl-radar-title">{{ r.title }}</text>
              <view class="wl-radar-meta">
                <text class="wl-radar-ev">窗口内 {{ r.window_events }} 个事件</text>
                <text class="wl-radar-sep">·</text>
                <text class="wl-radar-q">质量 {{ r.quality_score }}</text>
                <text class="wl-radar-sep">·</text>
                <text class="wl-radar-ch">{{ r.chapter_count }} 章</text>
              </view>
              <!-- 质量条：0~10 归一 -->
              <view class="wl-bar">
                <view class="wl-bar-fill" :style="{ width: (r.quality_score * 10) + '%' }" />
              </view>
            </view>
          </view>
        </view>
      </view>

      <!-- ══════════ 关键实体监控 ══════════ -->
      <view v-else-if="activeTab === 'entities'" class="wl-panel">
        <view class="wl-filter">
          <input
            v-model="entityQuery"
            class="wl-input"
            placeholder="搜索实体"
            placeholder-class="wl-input-ph"
            confirm-type="search"
            @confirm="loadEntities"
          />
        </view>

        <view v-if="entityLoading" class="wl-loading">
          <text class="wl-loading-text">加载中…</text>
        </view>
        <EmptyState v-else-if="entityError" :text="entityError" />
        <EmptyState v-else-if="!entities.length" text="暂无实体数据" />
        <view v-else class="wl-entities">
          <view
            v-for="en in entities"
            :key="en.id"
            class="wl-ent"
            @click="goEntity(en.id)"
          >
            <view class="wl-ent-head">
              <text class="wl-ent-name">{{ en.name }}</text>
              <text v-if="en.entity_type" class="wl-ent-type">{{ en.entity_type }}</text>
            </view>
            <view class="wl-ent-meta">
              <text class="wl-ent-stat">{{ en.event_count }} 事件</text>
              <text class="wl-ent-sep">·</text>
              <text class="wl-ent-stat">{{ en.thread_count }} 世界线</text>
              <text v-if="en.last_seen_at" class="wl-ent-time">· {{ fmtDate(en.last_seen_at) }}</text>
            </view>
            <!-- 关联世界线数条：直观反映实体跨线影响力 -->
            <view class="wl-bar wl-bar-sm">
              <view
                class="wl-bar-fill wl-bar-fill-alt"
                :style="{ width: Math.min(100, (en.thread_count / 20) * 100) + '%' }"
              />
            </view>
          </view>
        </view>

        <view v-if="entityTotal > entities.length" class="wl-more" @click="loadMoreEntities">
          <text class="wl-more-text">加载更多</text>
        </view>
      </view>

      <SiteFooter />
    </view>
  </view>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import PcSidebar from '@/components/common/PcSidebar.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import SiteFooter from '@/components/common/SiteFooter.vue'
import {
  fetchWorkbenchMeta,
  fetchWorkbenchThreads,
  fetchWorkbenchRadar,
  fetchWorkbenchEntities,
} from '@/utils/api'
import { usePcNavFrame } from '@/utils/usePcNav.js'

usePcNavFrame()

const tabs = [
  { key: 'threads', label: '连续追踪' },
  { key: 'radar', label: '异动雷达' },
  { key: 'entities', label: '实体监控' },
]
const activeTab = ref('threads')
const meta = ref(null)

const windows = [
  { days: 7, label: '7 天' },
  { days: 30, label: '30 天' },
  { days: 90, label: '90 天' },
]

// ── 连续追踪 ──
const threads = ref([])
const threadTotal = ref(0)
const threadLoading = ref(false)
const threadError = ref('')
const threadQuery = ref('')
const threadSort = ref('recent')
const threadOffset = ref(0)
const PAGE = 30

const sortOptions = [
  { value: 'recent', label: '最近更新' },
  { value: 'chapters', label: '章节最多' },
  { value: 'heat', label: '异动热度' },
]

// ── 异动雷达 ──
const radar = ref([])
const radarLoading = ref(false)
const radarError = ref('')
const radarDays = ref(30)
const radarWindowLabel = ref('30 天')

// ── 实体监控 ──
const entities = ref([])
const entityTotal = ref(0)
const entityLoading = ref(false)
const entityError = ref('')
const entityQuery = ref('')
const entityOffset = ref(0)

function fmtDate(v) {
  if (!v) return ''
  const s = String(v)
  // ISO / 带时区字符串统一取日期部分，避免跨端解析差异
  return s.slice(0, 10)
}

function goThread(id) {
  if (!id) return
  uni.navigateTo({ url: `/pages/worldline/detail?id=${id}` })
}

function goEntity(id) {
  if (!id) return
  uni.navigateTo({ url: `/pages/worldline/entity?id=${id}` })
}

// ── 加载 ──

async function loadMeta() {
  try {
    meta.value = await fetchWorkbenchMeta()
  } catch (e) {
    // 元信息失败不阻断：各 Tab 自带错误处理
    console.warn('[worldline] meta 加载失败:', e)
  }
}

async function loadThreads(reset = true) {
  if (reset) {
    threadOffset.value = 0
    threads.value = []
  }
  threadLoading.value = true
  threadError.value = ''
  try {
    const params = {
      min_chapters: 2,
      sort: threadSort.value,
      limit: PAGE,
      offset: threadOffset.value,
    }
    if (threadQuery.value) params.q = threadQuery.value
    const res = await fetchWorkbenchThreads(params)
    const items = (res && res.items) || []
    threads.value = reset ? items : [...threads.value, ...items]
    threadTotal.value = (res && res.total) || 0
  } catch (e) {
    threadError.value = '世界线加载失败，请稍后重试'
    console.warn('[worldline] threads 加载失败:', e)
  } finally {
    threadLoading.value = false
  }
}

function loadMoreThreads() {
  threadOffset.value += PAGE
  loadThreads(false)
}

function pickSort(v) {
  if (threadSort.value === v) return
  threadSort.value = v
  loadThreads(true)
}

async function loadRadar() {
  radarLoading.value = true
  radarError.value = ''
  try {
    const res = await fetchWorkbenchRadar({ window_days: radarDays.value, limit: 20 })
    radar.value = (res && res.items) || []
    radarWindowLabel.value = (res && res.window_label) || `${radarDays.value} 天`
  } catch (e) {
    radarError.value = '雷达计算失败，请稍后重试'
    console.warn('[worldline] radar 加载失败:', e)
  } finally {
    radarLoading.value = false
  }
}

function pickWindow(d) {
  if (radarDays.value === d) return
  radarDays.value = d
  loadRadar()
}

async function loadEntities(reset = true) {
  if (reset) {
    entityOffset.value = 0
    entities.value = []
  }
  entityLoading.value = true
  entityError.value = ''
  try {
    const params = { limit: PAGE, offset: entityOffset.value }
    if (entityQuery.value) params.q = entityQuery.value
    const res = await fetchWorkbenchEntities(params)
    const items = (res && res.items) || []
    entities.value = reset ? items : [...entities.value, ...items]
    entityTotal.value = (res && res.total) || 0
  } catch (e) {
    entityError.value = '实体加载失败，请稍后重试'
    console.warn('[worldline] entities 加载失败:', e)
  } finally {
    entityLoading.value = false
  }
}

function loadMoreEntities() {
  entityOffset.value += PAGE
  loadEntities(false)
}

function switchTab(key) {
  if (activeTab.value === key) return
  activeTab.value = key
  if (key === 'radar' && !radar.value.length) loadRadar()
  if (key === 'entities' && !entities.value.length) loadEntities(true)
}

onMounted(() => {
  loadMeta()
  loadThreads(true)
})
</script>

<style scoped>
.page-layout {
  display: flex;
  min-height: 100vh;
  background: var(--color-bg);
}
.container {
  flex: 1;
  min-width: 0;
  padding: 30rpx 28rpx 60rpx;
}

/* ── Header ── */
.wl-header {
  display: flex;
  flex-direction: column;
  gap: 8rpx;
  margin-bottom: 20rpx;
}
.wl-title {
  font-size: 40rpx;
  font-weight: 700;
  color: var(--color-text-primary);
  line-height: 1.3;
}
.wl-subtitle {
  font-size: 25rpx;
  color: var(--color-text-secondary);
  line-height: 1.5;
}
.wl-health {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8rpx;
  margin-top: 6rpx;
}
.wl-health-item {
  font-size: 22rpx;
  color: var(--color-text-hint);
  font-family: var(--font-numeric);
}
.wl-health-sep { font-size: 22rpx; color: var(--color-text-placeholder); }

/* ── 数据状态提示 ── */
.wl-notice {
  margin-bottom: 18rpx;
  padding: 16rpx 20rpx;
  border-radius: var(--radius-r-md, 16rpx);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
}
.wl-notice-text {
  font-size: 22rpx;
  color: var(--color-text-secondary);
  line-height: 1.6;
}

/* ── Tabs ── */
.wl-tabs {
  display: flex;
  gap: 10rpx;
  margin-bottom: 22rpx;
  border-bottom: 1px solid var(--color-border);
  padding-bottom: 14rpx;
}
.wl-tab {
  padding: 10rpx 24rpx;
  border-radius: var(--radius-r-pill, 999rpx);
  background: var(--color-bg-secondary);
}
.wl-tab-on { background: var(--color-brand); }
.wl-tab-text {
  font-size: 25rpx;
  color: var(--color-text-secondary);
  line-height: 1.4;
}
.wl-tab-on .wl-tab-text { color: #fff; font-weight: 500; }

/* ── 筛选 ── */
.wl-filter {
  display: flex;
  flex-direction: column;
  gap: 14rpx;
  margin-bottom: 22rpx;
}
.wl-input {
  width: 100%;
  height: 68rpx;
  padding: 0 22rpx;
  border-radius: var(--radius-r-pill, 999rpx);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  font-size: 26rpx;
  color: var(--color-text-primary);
  box-sizing: border-box;
}
.wl-input-ph { color: var(--color-text-placeholder); font-size: 25rpx; }

.wl-sort, .wl-window {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
}
.wl-sort-item, .wl-win-item {
  padding: 8rpx 20rpx;
  border-radius: var(--radius-r-pill, 999rpx);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
}
.wl-sort-on, .wl-win-on {
  background: var(--color-brand);
  border-color: var(--color-brand);
}
.wl-sort-text, .wl-win-text {
  font-size: 23rpx;
  color: var(--color-text-secondary);
  line-height: 1.4;
}
.wl-sort-on .wl-sort-text, .wl-win-on .wl-win-text { color: #fff; }
.wl-window-hint {
  font-size: 21rpx;
  color: var(--color-text-hint);
  line-height: 1.5;
}

/* ── 状态 ── */
.wl-loading { padding: 60rpx 0; text-align: center; }
.wl-loading-text { font-size: 25rpx; color: var(--color-text-placeholder); }

/* ── 世界线卡片 ── */
.wl-list { display: flex; flex-direction: column; gap: 18rpx; }
.wl-card {
  padding: 24rpx;
  border-radius: var(--radius-r-lg, 20rpx);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
}
.wl-card:active { background: var(--color-bg-hover); }
.wl-card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16rpx;
  margin-bottom: 10rpx;
}
.wl-card-title {
  flex: 1;
  font-size: 29rpx;
  font-weight: 600;
  color: var(--color-text-primary);
  line-height: 1.5;
}
.wl-badge {
  flex-shrink: 0;
  padding: 4rpx 14rpx;
  border-radius: var(--radius-r-pill, 999rpx);
  font-size: 20rpx;
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
}
.wl-badge-embryo { background: var(--color-bg-secondary); color: var(--color-text-hint); }
.wl-badge-active { background: var(--color-brand); color: #fff; }
.wl-badge-resolved { background: var(--color-bg-hover); color: var(--color-text-hint); }

.wl-card-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8rpx;
}
.wl-meta-num {
  font-size: 34rpx;
  font-weight: 700;
  color: var(--color-text-primary);
  font-family: var(--font-numeric);
  line-height: 1.2;
}
.wl-meta-unit, .wl-meta-time, .wl-meta-tx {
  font-size: 22rpx;
  color: var(--color-text-hint);
  font-family: var(--font-numeric);
}

.wl-chips { display: flex; flex-wrap: wrap; gap: 8rpx; margin-top: 12rpx; }
.wl-chip {
  padding: 4rpx 14rpx;
  border-radius: var(--radius-r-sm, 8rpx);
  background: var(--color-bg-secondary);
  font-size: 21rpx;
  color: var(--color-text-secondary);
  line-height: 1.5;
}

.wl-latest {
  display: flex;
  align-items: baseline;
  gap: 10rpx;
  margin-top: 14rpx;
  padding-top: 14rpx;
  border-top: 1px solid var(--color-border);
}
.wl-latest-label {
  flex-shrink: 0;
  font-size: 20rpx;
  color: var(--color-text-placeholder);
}
.wl-latest-text {
  flex: 1;
  font-size: 23rpx;
  color: var(--color-text-secondary);
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── 雷达 ── */
.wl-radar { display: flex; flex-direction: column; gap: 16rpx; }
.wl-radar-item {
  display: flex;
  gap: 18rpx;
  padding: 22rpx;
  border-radius: var(--radius-r-lg, 20rpx);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
}
.wl-radar-item:active { background: var(--color-bg-hover); }
.wl-radar-rank {
  flex-shrink: 0;
  width: 44rpx;
  font-size: 30rpx;
  font-weight: 700;
  color: var(--color-brand);
  font-family: var(--font-numeric);
  line-height: 1.4;
  text-align: center;
}
.wl-radar-body { flex: 1; min-width: 0; }
.wl-radar-title {
  font-size: 28rpx;
  font-weight: 600;
  color: var(--color-text-primary);
  line-height: 1.5;
  margin-bottom: 8rpx;
}
.wl-radar-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8rpx;
  margin-bottom: 10rpx;
}
.wl-radar-ev, .wl-radar-q, .wl-radar-ch {
  font-size: 22rpx;
  color: var(--color-text-secondary);
  font-family: var(--font-numeric);
}
.wl-radar-sep { font-size: 22rpx; color: var(--color-text-placeholder); }

.wl-bar {
  width: 100%;
  height: 8rpx;
  border-radius: var(--radius-r-pill, 999rpx);
  background: var(--color-bg-secondary);
  overflow: hidden;
}
.wl-bar-sm { height: 6rpx; margin-top: 10rpx; }
.wl-bar-fill {
  height: 100%;
  border-radius: var(--radius-r-pill, 999rpx);
  background: var(--color-brand);
}
.wl-bar-fill-alt { background: var(--color-text-hint); }

/* ── 实体 ── */
.wl-entities { display: flex; flex-direction: column; gap: 16rpx; }
.wl-ent {
  padding: 22rpx;
  border-radius: var(--radius-r-lg, 20rpx);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
}
.wl-ent:active { background: var(--color-bg-hover); }
.wl-ent-head {
  display: flex;
  align-items: center;
  gap: 12rpx;
  margin-bottom: 8rpx;
}
.wl-ent-name {
  font-size: 28rpx;
  font-weight: 600;
  color: var(--color-text-primary);
  line-height: 1.4;
}
.wl-ent-type {
  padding: 2rpx 12rpx;
  border-radius: var(--radius-r-sm, 8rpx);
  background: var(--color-bg-secondary);
  font-size: 20rpx;
  color: var(--color-text-hint);
}
.wl-ent-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8rpx;
}
.wl-ent-stat, .wl-ent-time {
  font-size: 22rpx;
  color: var(--color-text-secondary);
  font-family: var(--font-numeric);
}
.wl-ent-sep { font-size: 22rpx; color: var(--color-text-placeholder); }

/* ── 加载更多 ── */
.wl-more { padding: 30rpx 0; text-align: center; }
.wl-more-text { font-size: 25rpx; color: var(--color-brand); }

/* ═══════════ PC 适配 (≥768px) ═══════════ */
@media screen and (min-width: 768px) {
  .container { padding: 32px 40px 60px; }
  .wl-header { flex-direction: row; align-items: flex-end; justify-content: space-between; }
  .wl-title { font-size: 26px; }
  .wl-subtitle { font-size: 14px; }
  .wl-health-item, .wl-health-sep { font-size: 12px; }
  .wl-notice { padding: 12px 16px; border-radius: var(--radius-p-md, 10px); margin-bottom: 16px; }
  .wl-notice-text { font-size: 13px; }

  .wl-tabs { gap: 8px; margin-bottom: 20px; padding-bottom: 12px; }
  .wl-tab { padding: 6px 18px; border-radius: var(--radius-p-pill, 999px); }
  .wl-tab-text { font-size: 14px; }

  .wl-filter { flex-direction: row; align-items: center; gap: 12px; margin-bottom: 20px; }
  .wl-input { width: 280px; height: 38px; padding: 0 14px; font-size: 14px; border-radius: var(--radius-p-pill, 999px); }
  .wl-input-ph { font-size: 13px; }
  .wl-sort, .wl-window { gap: 8px; }
  .wl-sort-item, .wl-win-item { padding: 5px 14px; border-radius: var(--radius-p-pill, 999px); }
  .wl-sort-text, .wl-win-text { font-size: 13px; }
  .wl-window-hint { font-size: 12px; }

  .wl-list, .wl-radar, .wl-entities { gap: 12px; }
  .wl-card, .wl-radar-item, .wl-ent {
    padding: 18px;
    border-radius: var(--radius-p-lg, 12px);
  }
  .wl-card-title { font-size: 16px; }
  .wl-badge { font-size: 11px; padding: 2px 8px; border-radius: var(--radius-p-pill, 999px); }
  .wl-meta-num { font-size: 22px; }
  .wl-meta-unit, .wl-meta-time, .wl-meta-tx { font-size: 12px; }
  .wl-chip { font-size: 12px; padding: 2px 8px; border-radius: var(--radius-p-sm, 4px); }
  .wl-latest { margin-top: 10px; padding-top: 10px; }
  .wl-latest-label { font-size: 11px; }
  .wl-latest-text { font-size: 13px; }

  .wl-radar-rank { width: 28px; font-size: 18px; }
  .wl-radar-title { font-size: 15px; }
  .wl-radar-ev, .wl-radar-q, .wl-radar-ch, .wl-radar-sep { font-size: 12px; }

  .wl-ent-name { font-size: 15px; }
  .wl-ent-type { font-size: 11px; padding: 1px 7px; border-radius: var(--radius-p-sm, 4px); }
  .wl-ent-stat, .wl-ent-time, .wl-ent-sep { font-size: 12px; }

  .wl-bar { height: 5px; border-radius: var(--radius-p-pill, 999px); }
  .wl-bar-sm { height: 4px; margin-top: 8px; }
  .wl-bar-fill { border-radius: var(--radius-p-pill, 999px); }

  .wl-loading { padding: 40px 0; }
  .wl-loading-text { font-size: 14px; }
  .wl-more { padding: 24px 0; }
  .wl-more-text { font-size: 14px; }

  /* 卡片 hover：桌面端可发现性 */
  .wl-card:hover, .wl-radar-item:hover, .wl-ent:hover {
    background: var(--color-bg-hover);
    border-color: var(--color-border-strong, var(--color-border));
  }
}

/* ═══════════ 宽屏 (≥1200px) ═══════════ */
@media screen and (min-width: 1200px) {
  .container { padding: 36px 56px 72px; }
  .wl-title { font-size: 28px; }
  .wl-input { width: 340px; }
}
</style>
