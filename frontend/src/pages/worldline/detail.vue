<template>
  <view class="page-layout">
    <PcSidebar active="worldline" />
    <view class="container">

      <view v-if="loading" class="wd-loading">
        <text class="wd-loading-text">加载中…</text>
      </view>

      <EmptyState v-else-if="error" :text="error" />

      <template v-else-if="thread">
        <!-- 返回 -->
        <view class="wd-back" @click="goBack">
          <text class="wd-back-text">← 工作台</text>
        </view>

        <!-- 主卡 -->
        <view class="wd-head">
          <view class="wd-title-row">
            <text class="wd-title">{{ thread.title }}</text>
            <text class="wl-badge" :class="'wl-badge-' + thread.status">{{ thread.status_label }}</text>
          </view>
          <view class="wd-meta">
            <text class="wd-meta-num">{{ thread.real_chapter_count }}</text>
            <text class="wd-meta-unit">章节</text>
            <text v-if="thread.contested_asset" class="wd-meta-item">· 标的 {{ thread.contested_asset }}</text>
            <text v-if="thread.mechanism_key" class="wd-meta-item">· {{ thread.mechanism_key }}</text>
          </view>
          <view v-if="thread.core_entities && thread.core_entities.length" class="wd-chips">
            <text v-for="(en, i) in thread.core_entities.slice(0, 8)" :key="i" class="wl-chip">{{ en }}</text>
          </view>
        </view>

        <!-- ══════ 章节时间轴 ══════ -->
        <view class="wd-section">
          <text class="wd-section-title">章节时间轴</text>
          <!-- 排序说明：按章节号 chapter_no 倒序（最新章节在前），与治理端同源 -->
          <text class="wd-section-hint">按章节号倒序排列（最新章节在前）</text>

          <EmptyState v-if="!thread.chapters.length" text="暂无章节" />
          <view v-else class="wd-timeline">
            <view
              v-for="c in thread.chapters"
              :key="c.chapter_id"
              :id="'ch-' + c.chapter_id"
              class="wd-chapter"
              :class="{ 'wd-chapter-hit': c.chapter_id === highlightChapter }"
            >
              <view class="wd-ch-dot" />
              <view class="wd-ch-body">
                <view class="wd-ch-head">
                  <text class="wd-ch-no">#{{ c.display_no }}</text>
                  <text class="wd-ch-role">{{ c.role_label }}</text>
                  <text v-if="c.occurred_at" class="wd-ch-date">{{ fmtDate(c.occurred_at) }}</text>
                </view>
                <text class="wd-ch-title">{{ c.title }}</text>
                <text v-if="c.summary" class="wd-ch-summary">{{ c.summary }}</text>
                <text v-if="c.latest_change" class="wd-ch-change">变化：{{ c.latest_change }}</text>

                <!-- 章节 → 事件详情 -->
                <view class="wd-ch-foot">
                  <text class="wd-ch-link" @click="goEvent(c.event_id)">事件详情 →</text>
                  <text
                    v-if="digestsOfEvent(c.event_id).length"
                    class="wd-ch-link"
                    @click="goDigest(digestsOfEvent(c.event_id)[0])"
                  >收录简报 →</text>
                </view>
              </view>
            </view>
          </view>
        </view>

        <!-- ══════ 投资传导链 ══════ -->
        <view class="wd-section">
          <text class="wd-section-title">投资传导链</text>
          <!-- 区分「未生成」与「恰好没有」：两者对用户的意义完全不同 -->
          <view v-if="!thread.transmissions.length" class="wd-empty-tx">
            <text class="wd-empty-tx-text">
              {{ transmissionEnabled ? '本条世界线暂无传导链' : '传导链功能尚未生成数据（库内 0 条）。传导边需人工或 LLM 分析建立，不自动推断。' }}
            </text>
          </view>
          <view v-else class="wd-tx-list">
            <view v-for="t in thread.transmissions" :key="t.id" class="wd-tx">
              <view class="wd-tx-nodes">
                <text class="wd-tx-node">{{ t.from_title || '—' }}</text>
                <text class="wd-tx-arrow">→</text>
                <text class="wd-tx-node">{{ t.to_title || '—' }}</text>
              </view>
              <text class="wd-tx-mech">{{ t.mechanism }}</text>
              <view class="wd-tx-foot">
                <text class="wd-tx-ev" :class="'wd-tx-ev-' + t.evidence_status">{{ t.evidence_label }}</text>
                <text v-if="t.strength" class="wd-tx-strength">强度 {{ t.strength }}</text>
                <text v-if="t.arbitrated_by" class="wd-tx-arb">· 仲裁 {{ t.arbitrated_by }}</text>
              </view>
              <text v-if="t.evidence_note" class="wd-tx-note">{{ t.evidence_note }}</text>
            </view>
          </view>
        </view>

        <!-- ══════ 关联实体 ══════ -->
        <view v-if="thread.related_entities && thread.related_entities.length" class="wd-section">
          <text class="wd-section-title">关键实体</text>
          <view class="wd-ents">
            <view
              v-for="en in thread.related_entities"
              :key="en.id"
              class="wd-ent"
              @click="goEntity(en.id)"
            >
              <text class="wd-ent-name">{{ en.name }}</text>
              <text class="wd-ent-cnt">{{ en.mentions_in_thread }} 次</text>
            </view>
          </view>
        </view>

        <!-- ══════ 历史简报（跳回） ══════ -->
        <view class="wd-section">
          <text class="wd-section-title">收录本章的历史简报</text>
          <text class="wd-section-hint">简报保留生成时的判断快照，非当前状态</text>
          <EmptyState v-if="!thread.history_digests.length" text="暂无简报收录" />
          <view v-else class="wd-digests">
            <view
              v-for="d in thread.history_digests"
              :key="d.id"
              class="wd-digest"
              @click="goDigest(d)"
            >
              <text class="wd-digest-date">{{ fmtDate(d.digest_date) }}</text>
              <text class="wd-digest-label">{{ periodText(d.period_label) }}</text>
              <text class="wd-digest-cnt">{{ d.linked_events }} 个事件</text>
              <text class="wd-digest-arrow">→</text>
            </view>
          </view>
        </view>
      </template>

      <SiteFooter />
    </view>
  </view>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import PcSidebar from '@/components/common/PcSidebar.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import SiteFooter from '@/components/common/SiteFooter.vue'
import {
  fetchWorkbenchThread,
  fetchWorkbenchMeta,
  fetchDigestThreadLinks,
} from '@/utils/api'
import { usePcNavFrame } from '@/utils/usePcNav.js'

usePcNavFrame()

const thread = ref(null)
const loading = ref(false)
const error = ref('')
const threadId = ref('')
const highlightChapter = ref('')
const transmissionEnabled = ref(false)

// event_id → 收录它的简报列表（用于章节跳回简报）
const eventDigestMap = ref({})

function fmtDate(v) {
  if (!v) return ''
  return String(v).slice(0, 10)
}

function periodText(p) {
  const map = { morning: '晨间', afternoon: '午后', evening: '晚间', night: '夜间' }
  return map[p] || p || ''
}

function digestsOfEvent(eventId) {
  return eventDigestMap.value[eventId] || []
}

function goBack() {
  uni.navigateBack({ delta: 1 })
}

function goEvent(eventId) {
  if (!eventId) return
  uni.navigateTo({ url: `/pages/events/detail?id=${eventId}` })
}

function goEntity(id) {
  uni.navigateTo({ url: `/pages/worldline/entity?id=${id}` })
}

/** 跳回收录该章节的历史简报：带 digest id 深链定位 */
function goDigest(d) {
  if (!d || !d.id) return
  uni.navigateTo({ url: `/pages/reports/index?id=${d.id}` })
}

async function loadMeta() {
  try {
    const m = await fetchWorkbenchMeta()
    transmissionEnabled.value = !!(m && m.data_health && m.data_health.transmission_enabled)
  } catch (e) {
    console.warn('[worldline-detail] meta 失败:', e)
  }
}

/** 批量回填「事件 → 简报」映射，供章节行展示「收录简报」入口 */
async function loadEventDigests(digestList) {
  const map = {}
  for (const d of digestList) {
    try {
      const res = await fetchDigestThreadLinks(d.id)
      const links = (res && res.links) || {}
      for (const [eid, ls] of Object.entries(links)) {
        if (!map[eid]) map[eid] = []
        // 同一事件可能被多个世界线收录，此处限定当前线章节
        map[eid].push({ id: d.id, digest_date: d.digest_date, period_label: d.period_label })
      }
    } catch (e) {
      console.warn('[worldline-detail] 简报关联失败:', d.id, e)
    }
  }
  eventDigestMap.value = map
}

async function loadDetail() {
  if (!threadId.value) {
    error.value = '缺少世界线 ID'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const data = await fetchWorkbenchThread(threadId.value)
    thread.value = data
    // 深链定位：URL 带 chapter=<chapter_id> 时滚动到对应章节
    if (highlightChapter.value) {
      await nextTick()
      setTimeout(() => {
        uni.pageScrollTo({ selector: `#ch-${highlightChapter.value}`, duration: 300 })
      }, 100)
    }
    if (data && data.history_digests && data.history_digests.length) {
      loadEventDigests(data.history_digests)
    }
  } catch (e) {
    error.value = '世界线详情加载失败，请稍后重试'
    console.warn('[worldline-detail] 加载失败:', e)
  } finally {
    loading.value = false
  }
}

function readOption(key) {
  // uni-app H5 直接以 URL 打开时，onMounted 阶段 getCurrentPages() 可能尚未注入
  // 当前页的 $page.options（表现为参数丢失、页面一直报错）。
  // 双路径兜底：页面栈优先，URL query 兜底。
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

onMounted(() => {
  threadId.value = readOption('id')
  highlightChapter.value = readOption('chapter')
  loadMeta()
  loadDetail()
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

.wd-loading { padding: 80rpx 0; text-align: center; }
.wd-loading-text { font-size: 25rpx; color: var(--color-text-placeholder); }

.wd-back { margin-bottom: 16rpx; }
.wd-back-text { font-size: 24rpx; color: var(--color-brand); }

/* ── 主卡 ── */
.wd-head {
  padding: 26rpx;
  border-radius: var(--radius-r-lg, 20rpx);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  margin-bottom: 28rpx;
}
.wd-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16rpx;
  margin-bottom: 12rpx;
}
.wd-title {
  flex: 1;
  font-size: 34rpx;
  font-weight: 700;
  color: var(--color-text-primary);
  line-height: 1.45;
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

.wd-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8rpx;
}
.wd-meta-num {
  font-size: 34rpx;
  font-weight: 700;
  color: var(--color-text-primary);
  font-family: var(--font-numeric);
}
.wd-meta-unit, .wd-meta-item {
  font-size: 22rpx;
  color: var(--color-text-hint);
  font-family: var(--font-numeric);
}
.wd-chips { display: flex; flex-wrap: wrap; gap: 8rpx; margin-top: 14rpx; }
.wl-chip {
  padding: 4rpx 14rpx;
  border-radius: var(--radius-r-sm, 8rpx);
  background: var(--color-bg-secondary);
  font-size: 21rpx;
  color: var(--color-text-secondary);
  line-height: 1.5;
}

/* ── 区块 ── */
.wd-section { margin-bottom: 34rpx; }
.wd-section-title {
  font-size: 28rpx;
  font-weight: 600;
  color: var(--color-text-primary);
  line-height: 1.5;
  display: block;
  margin-bottom: 4rpx;
}
.wd-section-hint {
  font-size: 21rpx;
  color: var(--color-text-hint);
  line-height: 1.5;
  display: block;
  margin-bottom: 14rpx;
}

/* ── 时间轴 ── */
.wd-timeline {
  display: flex;
  flex-direction: column;
  padding-left: 8rpx;
}
.wd-chapter {
  display: flex;
  gap: 18rpx;
  padding-bottom: 24rpx;
  position: relative;
}
/* 轴线：除最后一项外都画竖线 */
.wd-chapter::before {
  content: '';
  position: absolute;
  left: 7rpx;
  top: 22rpx;
  bottom: 0;
  width: 2rpx;
  background: var(--color-border);
}
.wd-chapter:last-child::before { display: none; }
.wd-ch-dot {
  flex-shrink: 0;
  width: 16rpx;
  height: 16rpx;
  margin-top: 8rpx;
  border-radius: 50%;
  background: var(--color-brand);
  z-index: var(--z-base, 1);
}
.wd-ch-body {
  flex: 1;
  min-width: 0;
  padding: 18rpx 20rpx;
  border-radius: var(--radius-r-md, 16rpx);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
}
.wd-chapter-hit .wd-ch-body {
  border-color: var(--color-brand);
  background: var(--color-bg-hover);
}
.wd-ch-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10rpx;
  margin-bottom: 8rpx;
}
.wd-ch-no {
  font-size: 22rpx;
  font-weight: 600;
  color: var(--color-brand);
  font-family: var(--font-numeric);
}
.wd-ch-role {
  padding: 2rpx 12rpx;
  border-radius: var(--radius-r-sm, 8rpx);
  background: var(--color-bg-secondary);
  font-size: 20rpx;
  color: var(--color-text-secondary);
}
.wd-ch-date {
  font-size: 21rpx;
  color: var(--color-text-placeholder);
  font-family: var(--font-numeric);
}
.wd-ch-title {
  font-size: 27rpx;
  font-weight: 500;
  color: var(--color-text-primary);
  line-height: 1.55;
  display: block;
}
.wd-ch-summary {
  font-size: 23rpx;
  color: var(--color-text-secondary);
  line-height: 1.6;
  display: block;
  margin-top: 6rpx;
}
.wd-ch-change {
  font-size: 22rpx;
  color: var(--color-text-hint);
  line-height: 1.6;
  display: block;
  margin-top: 6rpx;
}
.wd-ch-foot { display: flex; gap: 22rpx; margin-top: 12rpx; }
.wd-ch-link { font-size: 22rpx; color: var(--color-brand); }

/* ── 传导链 ── */
.wd-tx-list { display: flex; flex-direction: column; gap: 16rpx; }
.wd-tx {
  padding: 22rpx;
  border-radius: var(--radius-r-lg, 20rpx);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
}
.wd-tx-nodes {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10rpx;
  margin-bottom: 10rpx;
}
.wd-tx-node {
  font-size: 25rpx;
  font-weight: 500;
  color: var(--color-text-primary);
  line-height: 1.5;
}
.wd-tx-arrow { font-size: 24rpx; color: var(--color-text-hint); }
.wd-tx-mech {
  font-size: 23rpx;
  color: var(--color-text-secondary);
  line-height: 1.6;
  display: block;
  margin-bottom: 10rpx;
}
.wd-tx-foot { display: flex; flex-wrap: wrap; align-items: center; gap: 10rpx; }
.wd-tx-ev {
  padding: 3rpx 14rpx;
  border-radius: var(--radius-r-pill, 999rpx);
  font-size: 20rpx;
  background: var(--color-bg-secondary);
  color: var(--color-text-secondary);
}
.wd-tx-ev-hypothesis { background: var(--color-bg-secondary); color: var(--color-text-hint); }
.wd-tx-ev-supported { background: var(--color-brand); color: #fff; }
.wd-tx-ev-contradicted { background: var(--color-bg-hover); color: var(--color-text-placeholder); }
.wd-tx-strength, .wd-tx-arb {
  font-size: 21rpx;
  color: var(--color-text-hint);
  font-family: var(--font-numeric);
}
.wd-tx-note {
  font-size: 21rpx;
  color: var(--color-text-hint);
  line-height: 1.6;
  display: block;
  margin-top: 8rpx;
}
.wd-empty-tx {
  padding: 24rpx;
  border-radius: var(--radius-r-md, 16rpx);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
}
.wd-empty-tx-text {
  font-size: 22rpx;
  color: var(--color-text-secondary);
  line-height: 1.65;
}

/* ── 实体 ── */
.wd-ents { display: flex; flex-wrap: wrap; gap: 12rpx; }
.wd-ent {
  display: flex;
  align-items: center;
  gap: 10rpx;
  padding: 10rpx 20rpx;
  border-radius: var(--radius-r-pill, 999rpx);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
}
.wd-ent:active { background: var(--color-bg-hover); }
.wd-ent-name { font-size: 24rpx; color: var(--color-text-primary); line-height: 1.4; }
.wd-ent-cnt {
  font-size: 20rpx;
  color: var(--color-text-hint);
  font-family: var(--font-numeric);
}

/* ── 简报 ── */
.wd-digests { display: flex; flex-direction: column; gap: 12rpx; }
.wd-digest {
  display: flex;
  align-items: center;
  gap: 14rpx;
  padding: 20rpx 22rpx;
  border-radius: var(--radius-r-md, 16rpx);
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
}
.wd-digest:active { background: var(--color-bg-hover); }
.wd-digest-date {
  font-size: 24rpx;
  color: var(--color-text-primary);
  font-family: var(--font-numeric);
}
.wd-digest-label { font-size: 21rpx; color: var(--color-text-secondary); }
.wd-digest-cnt {
  font-size: 21rpx;
  color: var(--color-text-hint);
  font-family: var(--font-numeric);
}
.wd-digest-arrow { margin-left: auto; font-size: 22rpx; color: var(--color-brand); }

/* ═══════════ PC (≥768px) ═══════════ */
@media screen and (min-width: 768px) {
  .container { padding: 32px 40px 60px; }
  .wd-loading { padding: 60px 0; }
  .wd-loading-text { font-size: 14px; }
  .wd-back-text { font-size: 14px; }

  .wd-head { padding: 22px; border-radius: var(--radius-p-lg, 12px); margin-bottom: 24px; }
  .wd-title { font-size: 20px; }
  .wl-badge { font-size: 11px; padding: 2px 8px; border-radius: var(--radius-p-pill, 999px); }
  .wd-meta-num { font-size: 22px; }
  .wd-meta-unit, .wd-meta-item { font-size: 12px; }
  .wl-chip { font-size: 12px; padding: 2px 8px; border-radius: var(--radius-p-sm, 4px); }

  .wd-section { margin-bottom: 32px; }
  .wd-section-title { font-size: 16px; }
  .wd-section-hint { font-size: 12px; margin-bottom: 12px; }

  .wd-timeline { padding-left: 4px; }
  .wd-chapter { gap: 14px; padding-bottom: 20px; }
  .wd-chapter::before { left: 5px; top: 20px; width: 1px; }
  .wd-ch-dot { width: 11px; height: 11px; margin-top: 6px; }
  .wd-ch-body { padding: 14px 16px; border-radius: var(--radius-p-md, 10px); }
  .wd-ch-no { font-size: 12px; }
  .wd-ch-role { font-size: 11px; padding: 1px 7px; border-radius: var(--radius-p-sm, 4px); }
  .wd-ch-date { font-size: 12px; }
  .wd-ch-title { font-size: 15px; }
  .wd-ch-summary { font-size: 13px; }
  .wd-ch-change { font-size: 12px; }
  .wd-ch-foot { gap: 16px; margin-top: 10px; }
  .wd-ch-link { font-size: 13px; }

  .wd-tx-list { gap: 12px; }
  .wd-tx { padding: 16px; border-radius: var(--radius-p-lg, 12px); }
  .wd-tx-node { font-size: 14px; }
  .wd-tx-arrow { font-size: 13px; }
  .wd-tx-mech { font-size: 13px; }
  .wd-tx-ev { font-size: 11px; padding: 1px 8px; border-radius: var(--radius-p-pill, 999px); }
  .wd-tx-strength, .wd-tx-arb { font-size: 12px; }
  .wd-tx-note { font-size: 12px; }
  .wd-empty-tx { padding: 16px; border-radius: var(--radius-p-md, 10px); }
  .wd-empty-tx-text { font-size: 13px; }

  .wd-ents { gap: 8px; }
  .wd-ent { padding: 6px 14px; border-radius: var(--radius-p-pill, 999px); }
  .wd-ent:hover { background: var(--color-bg-hover); border-color: var(--color-border-strong, var(--color-border)); }
  .wd-ent-name { font-size: 13px; }
  .wd-ent-cnt { font-size: 11px; }

  .wd-digests { gap: 8px; }
  .wd-digest { gap: 12px; padding: 12px 16px; border-radius: var(--radius-p-md, 10px); }
  .wd-digest:hover { background: var(--color-bg-hover); }
  .wd-digest-date { font-size: 14px; }
  .wd-digest-label, .wd-digest-cnt { font-size: 12px; }
  .wd-digest-arrow { font-size: 13px; }
}

@media screen and (min-width: 1200px) {
  .container { padding: 36px 56px 72px; }
  .wd-title { font-size: 22px; }
}
</style>
