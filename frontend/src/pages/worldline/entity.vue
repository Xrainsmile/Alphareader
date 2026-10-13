<template>
  <view class="page-layout">
    <PcSidebar active="worldline" />
    <view class="container">

      <view v-if="loading" class="we-loading">
        <text class="we-loading-text">加载中…</text>
      </view>

      <EmptyState v-else-if="error" :text="error" />

      <template v-else-if="ent">
        <view class="we-back" @click="goBack">
          <text class="we-back-text">← 实体监控</text>
        </view>

        <!-- 主卡 -->
        <view class="we-head">
          <view class="we-title-row">
            <text class="we-title">{{ ent.name }}</text>
            <text v-if="ent.entity_type" class="we-type">{{ ent.entity_type }}</text>
          </view>
          <view class="we-meta">
            <text class="we-meta-num">{{ ent.mention_count }}</text>
            <text class="we-meta-unit">总提及</text>
            <text v-if="ent.first_seen_at" class="we-meta-item">· 首次 {{ fmtDate(ent.first_seen_at) }}</text>
            <text v-if="ent.last_seen_at" class="we-meta-item">· 最近 {{ fmtDate(ent.last_seen_at) }}</text>
          </view>
          <view v-if="ent.aliases && ent.aliases.length" class="we-aliases">
            <text class="we-aliases-label">别名</text>
            <text class="we-aliases-text">{{ ent.aliases.slice(0, 8).join(' / ') }}</text>
          </view>
        </view>

        <!-- 角色分布 -->
        <view v-if="ent.roles && ent.roles.length" class="we-section">
          <text class="we-section-title">实体角色</text>
          <view class="we-roles">
            <view v-for="r in ent.roles" :key="r.role" class="we-role">
              <text class="we-role-name">{{ r.role }}</text>
              <text class="we-role-cnt">{{ r.count }}</text>
            </view>
          </view>
        </view>

        <!-- 提及趋势 -->
        <view class="we-section">
          <text class="we-section-title">事件提及趋势</text>
          <!-- 稀疏点：只渲染有提及的日期，缺失即无提及（不补零） -->
          <text class="we-section-hint">按天聚合，仅显示有提及的日期</text>
          <EmptyState v-if="!ent.trend || !ent.trend.length" text="暂无提及记录" />
          <view v-else class="we-trend">
            <view v-for="(t, i) in ent.trend" :key="i" class="we-trend-col">
              <view class="we-trend-bar-wrap">
                <view
                  class="we-trend-bar"
                  :style="{ height: barHeight(t.count) + '%' }"
                />
              </view>
              <text class="we-trend-date">{{ t.date.slice(5) }}</text>
              <text class="we-trend-cnt">{{ t.count }}</text>
            </view>
          </view>
        </view>

        <!-- 关联世界线 -->
        <view class="we-section">
          <text class="we-section-title">关联世界线</text>
          <EmptyState v-if="!ent.threads || !ent.threads.length" text="该实体暂未关联世界线" />
          <view v-else class="we-threads">
            <view
              v-for="t in ent.threads"
              :key="t.id"
              class="we-thread"
              @click="goThread(t.id)"
            >
              <view class="we-thread-head">
                <text class="we-thread-title">{{ t.title }}</text>
                <text class="we-thread-status">{{ t.status_label }}</text>
              </view>
              <view class="we-thread-meta">
                <text class="we-thread-stat">{{ t.chapter_count }} 章</text>
                <text class="we-thread-sep">·</text>
                <text class="we-thread-stat">本实体参与 {{ t.events_in_thread }} 个章节</text>
              </view>
            </view>
          </view>
        </view>

        <!-- 最近事件 -->
        <view v-if="ent.recent_events && ent.recent_events.length" class="we-section">
          <text class="we-section-title">最近相关事件</text>
          <view class="we-events">
            <view
              v-for="e in ent.recent_events"
              :key="e.id"
              class="we-event"
              @click="goEvent(e.id)"
            >
              <text class="we-event-title">{{ e.title }}</text>
              <text v-if="e.last_updated_at" class="we-event-date">{{ fmtDate(e.last_updated_at) }}</text>
            </view>
          </view>
        </view>
      </template>

      <SiteFooter />
    </view>
  </view>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import PcSidebar from '@/components/common/PcSidebar.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import SiteFooter from '@/components/common/SiteFooter.vue'
import { fetchWorkbenchEntity } from '@/utils/api'
import { usePcNavFrame } from '@/utils/usePcNav.js'

usePcNavFrame()

const ent = ref(null)
const loading = ref(false)
const error = ref('')

const maxTrend = computed(() => {
  const t = ent.value && ent.value.trend
  if (!t || !t.length) return 1
  return Math.max(...t.map((x) => x.count), 1)
})

function barHeight(c) {
  return Math.max(8, Math.round((c / maxTrend.value) * 100))
}

function fmtDate(v) {
  if (!v) return ''
  return String(v).slice(0, 10)
}

function goBack() {
  uni.navigateBack({ delta: 1 })
}

function goThread(id) {
  uni.navigateTo({ url: `/pages/worldline/detail?id=${id}` })
}

function goEvent(id) {
  uni.navigateTo({ url: `/pages/events/detail?id=${id}` })
}

function readOption(key) {
  // uni-app H5 直接以 URL 打开时，onMounted 阶段 getCurrentPages() 可能尚未注入
  // 当前页的 $page.options，导致参数丢失。双路径兜底：页面栈优先，URL query 兜底。
  const pages = getCurrentPages()
  const cur = pages[pages.length - 1]
  const opts = (cur && (cur.$page?.options || cur.options)) || {}
  if (opts[key]) return opts[key]
  // #ifdef H5
  try {
    const hash = window.location.hash || ''
    const qs = hash.includes('?') ? hash.slice(hash.indexOf('?') + 1) : ''
    return new URLSearchParams(qs).get(key) || ''
  } catch (_) {
    return ''
  }
  // #endif
  // #ifndef H5
  return ''
  // #endif
}

async function load() {
  const id = readOption('id')
  if (!id) {
    error.value = '缺少实体 ID'
    return
  }
  loading.value = true
  error.value = ''
  try {
    ent.value = await fetchWorkbenchEntity(id)
  } catch (e) {
    error.value = '实体详情加载失败，请稍后重试'
    console.warn('[worldline-entity] 加载失败:', e)
  } finally {
    loading.value = false
  }
}

onMounted(load)
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

.we-loading { padding: 80rpx 0; text-align: center; }
.we-loading-text { font-size: 25rpx; color: var(--color-text-placeholder); }
.we-back { margin-bottom: 16rpx; }
.we-back-text { font-size: 24rpx; color: var(--color-brand); }

/* ── 主卡 ── */
.we-head {
  padding: 26rpx;
  border-radius: var(--radius-r-lg, 20rpx);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  margin-bottom: 28rpx;
}
.we-title-row {
  display: flex;
  align-items: center;
  gap: 14rpx;
  margin-bottom: 12rpx;
}
.we-title {
  font-size: 34rpx;
  font-weight: 700;
  color: var(--color-text-primary);
  line-height: 1.4;
}
.we-type {
  padding: 3rpx 14rpx;
  border-radius: var(--radius-r-sm, 8rpx);
  background: var(--color-bg-secondary);
  font-size: 20rpx;
  color: var(--color-text-hint);
}
.we-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8rpx;
}
.we-meta-num {
  font-size: 34rpx;
  font-weight: 700;
  color: var(--color-text-primary);
  font-family: var(--font-numeric);
}
.we-meta-unit, .we-meta-item {
  font-size: 22rpx;
  color: var(--color-text-hint);
  font-family: var(--font-numeric);
}
.we-aliases {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
  margin-top: 14rpx;
}
.we-aliases-label { font-size: 21rpx; color: var(--color-text-placeholder); }
.we-aliases-text { flex: 1; font-size: 21rpx; color: var(--color-text-secondary); line-height: 1.55; }

/* ── 区块 ── */
.we-section { margin-bottom: 34rpx; }
.we-section-title {
  font-size: 28rpx;
  font-weight: 600;
  color: var(--color-text-primary);
  line-height: 1.5;
  display: block;
  margin-bottom: 4rpx;
}
.we-section-hint {
  font-size: 21rpx;
  color: var(--color-text-hint);
  line-height: 1.5;
  display: block;
  margin-bottom: 14rpx;
}

/* ── 角色 ── */
.we-roles { display: flex; flex-wrap: wrap; gap: 12rpx; }
.we-role {
  display: flex;
  align-items: center;
  gap: 10rpx;
  padding: 10rpx 20rpx;
  border-radius: var(--radius-r-pill, 999rpx);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
}
.we-role-name { font-size: 23rpx; color: var(--color-text-primary); line-height: 1.4; }
.we-role-cnt {
  font-size: 21rpx;
  color: var(--color-text-hint);
  font-family: var(--font-numeric);
}

/* ── 趋势图 ── */
.we-trend {
  display: flex;
  align-items: flex-end;
  gap: 6rpx;
  padding: 22rpx 18rpx;
  border-radius: var(--radius-r-md, 16rpx);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  overflow-x: auto;
}
.we-trend-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5rpx;
  min-width: 44rpx;
  flex-shrink: 0;
}
.we-trend-bar-wrap {
  width: 22rpx;
  height: 120rpx;
  display: flex;
  align-items: flex-end;
}
.we-trend-bar {
  width: 100%;
  border-radius: var(--radius-r-sm, 8rpx) var(--radius-r-sm, 8rpx) 0 0;
  background: var(--color-brand);
}
.we-trend-date {
  font-size: 17rpx;
  color: var(--color-text-placeholder);
  font-family: var(--font-numeric);
}
.we-trend-cnt {
  font-size: 17rpx;
  color: var(--color-text-hint);
  font-family: var(--font-numeric);
}

/* ── 世界线 ── */
.we-threads { display: flex; flex-direction: column; gap: 14rpx; }
.we-thread {
  padding: 22rpx;
  border-radius: var(--radius-r-lg, 20rpx);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
}
.we-thread:active { background: var(--color-bg-hover); }
.we-thread-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14rpx;
  margin-bottom: 8rpx;
}
.we-thread-title {
  flex: 1;
  font-size: 27rpx;
  font-weight: 500;
  color: var(--color-text-primary);
  line-height: 1.5;
}
.we-thread-status {
  flex-shrink: 0;
  font-size: 20rpx;
  color: var(--color-text-hint);
}
.we-thread-meta { display: flex; flex-wrap: wrap; gap: 8rpx; }
.we-thread-stat, .we-thread-sep {
  font-size: 21rpx;
  color: var(--color-text-secondary);
  font-family: var(--font-numeric);
}
.we-thread-sep { color: var(--color-text-placeholder); }

/* ── 事件 ── */
.we-events { display: flex; flex-direction: column; gap: 12rpx; }
.we-event {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 14rpx;
  padding: 18rpx 20rpx;
  border-radius: var(--radius-r-md, 16rpx);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
}
.we-event:active { background: var(--color-bg-hover); }
.we-event-title {
  flex: 1;
  font-size: 24rpx;
  color: var(--color-text-primary);
  line-height: 1.55;
}
.we-event-date {
  flex-shrink: 0;
  font-size: 20rpx;
  color: var(--color-text-placeholder);
  font-family: var(--font-numeric);
}

/* ═══════════ PC (≥768px) ═══════════ */
@media screen and (min-width: 768px) {
  .container { padding: 32px 40px 60px; }
  .we-loading { padding: 60px 0; }
  .we-loading-text { font-size: 14px; }
  .we-back-text { font-size: 14px; }

  .we-head { padding: 22px; border-radius: var(--radius-p-lg, 12px); margin-bottom: 24px; }
  .we-title { font-size: 22px; }
  .we-type { font-size: 11px; padding: 1px 8px; border-radius: var(--radius-p-sm, 4px); }
  .we-meta-num { font-size: 22px; }
  .we-meta-unit, .we-meta-item { font-size: 12px; }
  .we-aliases-label, .we-aliases-text { font-size: 12px; }

  .we-section { margin-bottom: 32px; }
  .we-section-title { font-size: 16px; }
  .we-section-hint { font-size: 12px; margin-bottom: 12px; }

  .we-roles { gap: 8px; }
  .we-role { padding: 6px 14px; border-radius: var(--radius-p-pill, 999px); }
  .we-role-name { font-size: 13px; }
  .we-role-cnt { font-size: 12px; }

  .we-trend { gap: 5px; padding: 18px 16px; border-radius: var(--radius-p-md, 10px); }
  .we-trend-col { min-width: 34px; gap: 3px; }
  .we-trend-bar-wrap { width: 16px; height: 100px; }
  .we-trend-bar { border-radius: var(--radius-p-sm, 4px) var(--radius-p-sm, 4px) 0 0; }
  .we-trend-date, .we-trend-cnt { font-size: 10px; }

  .we-threads { gap: 10px; }
  .we-thread { padding: 16px; border-radius: var(--radius-p-lg, 12px); }
  .we-thread:hover { background: var(--color-bg-hover); border-color: var(--color-border-strong, var(--color-border)); }
  .we-thread-title { font-size: 15px; }
  .we-thread-status { font-size: 11px; }
  .we-thread-stat, .we-thread-sep { font-size: 12px; }

  .we-events { gap: 8px; }
  .we-event { padding: 12px 16px; border-radius: var(--radius-p-md, 10px); }
  .we-event:hover { background: var(--color-bg-hover); }
  .we-event-title { font-size: 14px; }
  .we-event-date { font-size: 11px; }
}

@media screen and (min-width: 1200px) {
  .container { padding: 36px 56px 72px; }
}
</style>
