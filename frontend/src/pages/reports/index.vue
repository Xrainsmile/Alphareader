<template>
  <view class="page-layout">
    <PcSidebar active="reports" />
    <view class="container">
    <!-- Header -->
    <view class="reports-header">
      <view class="reports-title-row">
        <text class="reports-title">Reports</text>
        <!-- 移动端：侧门「!」入口（桌面端由左侧导航承载，此处隐藏）-->
        <GateButton class="gate-mobile-only" />
      </view>
      <text class="reports-subtitle">阶段简报 · 事件追踪</text>
      <!-- 移动端解锁后：Stocks / SEPA 入口（原生 tabBar 已默认隐藏）-->
      <view v-if="isOpen" class="gate-reveal-mobile">
        <view class="gate-reveal-chip" @click="goHidden('stocks')">Stocks</view>
        <view class="gate-reveal-chip" @click="goHidden('sepa')">SEPA</view>
      </view>
    </view>

    <!-- ═══════════════════════════════════════════
         新闻概览（时间轴）— 阶段简报
         ═══════════════════════════════════════════ -->
    <view class="digest-tab">
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
          :id="'digest-' + item.id"
          class="timeline-item"
        >
          <!-- Timeline connector -->
          <view class="timeline-rail">
            <view class="timeline-dot" :class="'dot-' + item.period_label"></view>
            <view v-if="idx < digestList.length - 1" class="timeline-line"></view>
          </view>

          <!-- Card -->
          <view class="digest-card">
            <!-- Header: 时段 + 时间范围 + 统计 -->
            <view class="dc-head">
              <text class="dc-title">{{ item.period_display }}</text>
              <text class="dc-range">{{ formatPeriodRange(item) }}</text>
              <!-- 导出本期为分享图（含扫码回看二维码，仅 H5） -->
              <text class="dc-export" @click.stop="exportDigest(item)">
                {{ exportingId === item.id ? '导出中…' : '导出图片' }}
              </text>
            </view>
            <view class="dc-stats">
              <text class="dc-stat">{{ item.event_count || 0 }} 个事件</text>
              <text class="dc-sep">·</text>
              <text class="dc-stat">{{ item.material_update_count || 0 }} 个重要变化</text>
              <text class="dc-sep">·</text>
              <text class="dc-stat">{{ (sc(item).must_know || []).length }} 个必须知道</text>
            </view>

            <!-- 时段概览 + 本期变化（阶段简报最有价值信息，优先呈现）-->
            <view v-if="sc(item).period_summary || sc(item).what_changed" class="dc-section dc-overview">
              <text v-if="sc(item).period_summary" class="dc-overview-text">{{ sc(item).period_summary }}</text>
              <view v-if="sc(item).what_changed" class="dc-change">
                <text class="dc-change-label">本期变化</text>
                <text class="dc-change-text">{{ sc(item).what_changed }}</text>
              </view>
            </view>

            <!-- 核心变化（跨事件共同信号，一眼看本时段最重要变化）-->
            <view v-if="sc(item).cross_event_signals && sc(item).cross_event_signals.length" class="dc-section dc-core">
              <text class="dc-section-title">核心变化</text>
              <view v-for="(s, si) in sc(item).cross_event_signals" :key="si" class="dc-core-item">
                <text class="dc-core-dot">•</text>
                <view class="dc-core-body">
                  <text class="dc-core-text">{{ s.title }}</text>
                  <text v-if="s.summary" class="dc-core-summary">{{ s.summary }}</text>
                </view>
              </view>
            </view>

            <!-- 必须知道（编号体现优先级，次级信息收进事件详情页）-->
            <view v-if="sc(item).must_know && sc(item).must_know.length" class="dc-section">
              <text class="dc-section-title">必须知道</text>
              <view
                v-for="(e, ei) in sc(item).must_know"
                :key="e.event_id"
                class="dc-mk"
              >
                <text class="dc-mk-rank">{{ String(ei + 1).padStart(2, '0') }}</text>
                <view class="dc-mk-body">
                  <view class="dc-mk-headline">
                    <text class="dc-mk-title">{{ e.title }}</text>
                    <text v-if="e.confidence" class="dc-conf" :class="'dc-conf-' + e.confidence">{{ confLabel(e.confidence) }}</text>
                  </view>
                  <text v-if="e.latest_change" class="dc-mk-change">{{ e.latest_change }}</text>
                  <text v-if="e.why_important" class="dc-mk-impact">影响：{{ e.why_important }}</text>
                  <text v-if="e.watch_next" class="dc-mk-watch">关注：{{ e.watch_next }}</text>
                  <view class="dc-mk-foot" @click.stop="goEventDetail(e.event_id)">
                    <text class="dc-mk-detail">查看详情 →</text>
                  </view>
                </view>
              </view>
            </view>

            <!-- 值得留意（紧凑列表）-->
            <view v-if="sc(item).worth_watching && sc(item).worth_watching.length" class="dc-section">
              <text class="dc-section-title">值得留意</text>
              <view v-for="e in sc(item).worth_watching" :key="e.event_id" class="dc-watch">
                <text class="dc-watch-bullet">—</text>
                <text class="dc-watch-text">{{ e.title }}</text>
              </view>
            </view>

            <!-- 持续关注（持续事件 + 此前关注暂无进展）-->
            <view v-if="ongoingList(item).length" class="dc-section">
              <text class="dc-section-title">持续关注</text>
              <view v-for="e in ongoingList(item)" :key="e.event_id" class="dc-watch">
                <text class="dc-watch-bullet">—</text>
                <text class="dc-watch-text">{{ e.title }}<text v-if="e.note" class="dc-watch-note"> · {{ e.note }}</text></text>
              </view>
            </view>

            <!-- 接下来关注 -->
            <view v-if="sc(item).upcoming && sc(item).upcoming.length" class="dc-section">
              <text class="dc-section-title">接下来关注</text>
              <view v-for="(u, ui) in sc(item).upcoming" :key="ui" class="dc-upcoming">
                <text v-if="u.time" class="dc-upcoming-time">{{ u.time }}</text>
                <text class="dc-upcoming-text">{{ u.item }}</text>
              </view>
            </view>

            <!-- 旧版 Markdown 兼容（schema_version != 2）-->
            <mp-html v-if="!(item.schema_version === 2 && item.structured_content)" :content="renderMd(item.content)" :tag-style="tagStyle" :lazy-load="true" />
          </view>
        </view>
      </view>

      <!-- Load more -->
      <view v-if="!digestLoading && digestList.length > 0 && digestDays < 30" class="load-more" @click="loadMoreDigests">
        <text class="load-more-text">加载更多</text>
      </view>
    </view>

    <!-- Footer -->
    <SiteFooter />
    </view><!-- /container -->
  </view><!-- /page-layout -->
</template>

<script setup>
import { ref, reactive, onMounted, nextTick } from 'vue'
import mpHtml from 'mp-html/dist/uni-app/components/mp-html/mp-html.vue'
import { fetchDigests } from '@/utils/api'
import { renderMarkdown } from '@/utils/markdown'
import SiteFooter from '@/components/common/SiteFooter.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import PcSidebar from '@/components/common/PcSidebar.vue'
import GateButton from '@/components/common/GateButton.vue'
import { useGate } from '@/utils/useGate'
import { listTagStyle, listTagStyleMobile } from '@/utils/formatters'
import { exportDigestImage, canExportImage } from '@/utils/digestExport'

// ── 侧门（gate）：Stocks / SEPA 对外隐藏，解锁后显现 ──
const { isOpen } = useGate()

// 移动端解锁后跳转到被隐藏的 Stocks / SEPA（已从原生 tabBar 移除，改用 navigateTo）
function goHidden(kind) {
  const url = kind === 'stocks' ? '/pages/stocks/index' : '/pages/sepa/index'
  uni.navigateTo({ url })
}

// ── Digest State ──
const digestList = ref([])
const digestLoading = ref(false)
const digestDays = ref(7)
const expandedIds = reactive(new Set())
// 深链：从企微推送 / ?id=<digest_id> 进入时，定位到对应简报
const targetDigestId = ref(null)

// Markdown tag styles (from shared formatters)
// 按屏宽选择字号体系：PC 15px 正文 / 移动端 13px，均对齐 news 页面
const tagStyle = (() => {
  try {
    return uni.getSystemInfoSync().windowWidth >= 768 ? listTagStyle : listTagStyleMobile
  } catch (_) {
    return listTagStyle
  }
})()

// ── Helpers ──

function renderMd(md) {
  if (!md) return ''
  return renderMarkdown(md)
}

// 安全读取结构化简报（避免 structured_content 为空时报错）
function sc(item) {
  return item && item.structured_content ? item.structured_content : {}
}
// 确定性标签：high/medium/low → 中文短标签（must_know 卡片展示）
function confLabel(c) {
  return { high: '高确定性', medium: '中等确定', low: '低确定性' }[c] || ''
}
// 持续关注 = 持续事件(ongoing_updates) + 此前关注暂无进展(quiet_topics)
function ongoingList(item) {
  const s = sc(item)
  return [...(s.ongoing_updates || []), ...(s.quiet_topics || [])]
}
// 时段范围：08-11 18:30—08:30
function formatPeriodRange(item) {
  const fmtTime = (iso) => {
    const d = new Date(iso)
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  const fmtDate = (iso) => {
    const d = new Date(iso)
    return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  }
  return `${fmtDate(item.period_start)} ${fmtTime(item.period_start)}—${fmtTime(item.period_end)}`
}

// 深链：从企微推送 ?id=<digest_id> 进入时，确保该简报在列表内、已展开，并滚动定位
async function applyDigestDeepLink() {
  if (targetDigestId.value == null) return
  const id = Number(targetDigestId.value)
  if (!digestList.value.some((d) => d.id === id) && digestDays.value < 30) {
    // 超出默认 7 天窗口，扩大范围重试
    digestDays.value = 30
    const data = await fetchDigests(digestDays.value)
    digestList.value = data || []
  }
  expandedIds.add(id)
  await nextTick()
  // H5 / 小程序均支持按 selector 滚动
  uni.pageScrollTo({ selector: `#digest-${id}`, duration: 300 })
}

/** 简报事件卡 → 事件详情页（PRD 12.3） */
function goEventDetail(eventId) {
  if (!eventId) return
  uni.navigateTo({ url: `/pages/events/detail?id=${eventId}` })
}

// ── 导出简报为图片（样式与网页一致 + 扫码回看二维码，仅 H5）──
const exportingId = ref(null)
async function exportDigest(item) {
  if (!canExportImage()) {
    uni.showToast({ title: '请使用浏览器打开', icon: 'none' })
    return
  }
  if (exportingId.value) return // 防连点
  exportingId.value = item.id
  try {
    await exportDigestImage(item)
  } catch (e) {
    console.warn('导出简报图片失败:', e)
    uni.showToast({ title: e.message || '导出失败', icon: 'none' })
  } finally {
    exportingId.value = null
  }
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
    // 深链定位：自动展开并滚动到对应简报
    await applyDigestDeepLink()
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

onMounted(() => {
  // 读取深链参数 ?id=<digest_id>（从企微推送链接进入时定位具体简报）
  const pages = getCurrentPages()
  const cur = pages[pages.length - 1]
  const opts = (cur && (cur.$page?.options || cur.options)) || {}
  if (opts.id) targetDigestId.value = opts.id

  // 进入即加载阶段简报时间轴
  loadDigests()
})
</script>

<style scoped>
/* ── Header ── */
.reports-header {
  padding: 36rpx 0 16rpx;
}
.reports-title-row {
  display: flex;
  align-items: center;
  gap: 16rpx;
}
.reports-title {
  font-size: 44rpx;
  font-weight: 800;
  color: var(--color-text-primary);
  letter-spacing: 1rpx;
  font-family: var(--font-display);
  display: block;
}
/* 侧门「!」在桌面端由左侧导航承载，页面头此处仅移动端显示 */
.gate-mobile-only {
  display: inline-flex;
}
.gate-reveal-mobile {
  display: flex;
  gap: 16rpx;
  margin-top: 14rpx;
}
.gate-reveal-chip {
  padding: 8rpx 28rpx;
  border-radius: 999rpx;
  background: var(--color-bg-brand-light, #eef4ff);
  color: var(--color-brand, #4285f4);
  font-size: 24rpx;
  font-weight: 600;
  cursor: pointer;
}
.reports-subtitle {
  font-size: 24rpx;
  color: var(--color-text-muted);
  margin-top: 6rpx;
  letter-spacing: 1rpx;
  display: block;
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
  background: var(--color-brand);
  flex-shrink: 0;
  z-index: 1;
}
.dot-morning { background: var(--color-time-morning); }
.dot-midday  { background: var(--color-time-midday); }
.dot-evening { background: var(--color-time-evening); }
.dot-night   { background: var(--color-time-night); }

.timeline-line {
  width: 3rpx;
  flex: 1;
  background: var(--color-border);
  margin-top: 4rpx;
}

/* Digest Card */
.digest-card {
  flex: 1;
  margin-left: 16rpx;
  background: var(--color-bg-hover);
  border-radius: 16rpx;
  padding: 24rpx;
  border: 1rpx solid var(--color-border-light);
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
  background: var(--color-bg-info-soft);
}
.badge-morning { background: var(--color-bg-time-morning); }
.badge-midday  { background: var(--color-bg-danger-light); }
.badge-evening { background: var(--color-bg-time-evening); }
.badge-night   { background: var(--color-bg-time-night); }

.badge-icon {
  flex: none;
}
.badge-text {
  font-size: 24rpx;
  font-weight: 600;
  color: var(--color-text-primary);
}

.digest-time {
  font-size: 22rpx;
  color: var(--color-text-muted);
  font-family: var(--font-sans);
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
  color: var(--color-brand);
  font-weight: 500;
}
.toggle-arrow {
  font-size: 20rpx;
  color: var(--color-brand);
}

.digest-footer {
  display: flex;
  align-items: center;
  padding-top: 12rpx;
  border-top: 1rpx solid var(--color-border-light);
  margin-top: 12rpx;
}
.footer-stat {
  font-size: 22rpx;
  color: var(--color-text-muted);
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
  color: var(--color-brand);
  font-weight: 500;
}

/* ── 阶段简报卡片（新版结构化简报）── */
.dc-head {
  display: flex;
  align-items: baseline;
  gap: 14rpx;
  flex-wrap: wrap;
}
.dc-title {
  font-size: 36rpx;
  font-weight: 800;
  color: var(--color-text-primary);
  letter-spacing: 0.5rpx;
}
.dc-range {
  font-size: 24rpx;
  color: var(--color-text-muted);
  font-family: var(--font-sans);
}
.dc-export {
  margin-left: auto;
  font-size: 22rpx;
  color: var(--color-brand);
  border: 1rpx solid var(--color-brand);
  border-radius: 999rpx;
  padding: 4rpx 18rpx;
  line-height: 1.6;
  cursor: pointer;
  user-select: none;
  -webkit-user-select: none;
}
.dc-export:active { opacity: 0.7; }
.dc-stats {
  display: flex;
  align-items: center;
  gap: 10rpx;
  margin-top: 8rpx;
  font-size: 22rpx;
}
.dc-stat { color: var(--color-text-secondary); }
.dc-sep { color: var(--color-border); }

.dc-section {
  margin-top: 24rpx;
}
.dc-section-title {
  font-size: 24rpx;
  font-weight: 700;
  color: var(--color-text-hint);
  letter-spacing: 1rpx;
  margin-bottom: 10rpx;
  display: block;
}

/* 时段概览 + 本期变化：阶段简报最有价值信息，置于卡片顶部 */
.dc-overview {
  background: var(--color-bg-brand-light, #eef4ff);
  border-radius: 12rpx;
  padding: 16rpx 20rpx;
}
.dc-overview-text {
  font-size: 26rpx;
  color: var(--color-text-primary);
  line-height: 1.6;
  display: block;
}
.dc-change {
  display: flex;
  align-items: flex-start;
  gap: 12rpx;
  margin-top: 12rpx;
  padding-top: 12rpx;
  border-top: 1rpx solid var(--color-border-light, #e2e8f0);
}
.dc-change-label {
  flex: none;
  font-size: 22rpx;
  font-weight: 700;
  color: #fff;
  background: var(--color-brand, #4285f4);
  border-radius: 8rpx;
  padding: 3rpx 12rpx;
  line-height: 1.5;
  margin-top: 2rpx;
}
.dc-change-text {
  font-size: 26rpx;
  color: var(--color-text-primary);
  line-height: 1.6;
  font-weight: 600;
}

/* 核心变化：唯一强调色，浅底突出 */
.dc-core {
  background: var(--color-bg-brand-light, #eef4ff);
  border-radius: 12rpx;
  padding: 16rpx 20rpx;
}
.dc-core-item {
  display: flex;
  align-items: flex-start;
  gap: 10rpx;
  margin-top: 8rpx;
}
.dc-core-dot { color: var(--color-brand, #4285f4); font-weight: 700; line-height: 1.6; flex: none; }
.dc-core-body { flex: 1; min-width: 0; }
.dc-core-text {
  font-size: 26rpx;
  color: var(--color-text-primary);
  line-height: 1.55;
  font-weight: 600;
  display: block;
}
.dc-core-summary {
  font-size: 23rpx;
  color: var(--color-text-secondary);
  line-height: 1.55;
  margin-top: 4rpx;
  display: block;
}

/* 必须知道：编号体现优先级 */
.dc-mk {
  display: flex;
  align-items: flex-start;
  gap: 14rpx;
  padding: 14rpx 0;
  border-bottom: 1rpx solid var(--color-border-light, #f0f0f4);
}
.dc-mk:last-child { border-bottom: none; }
.dc-mk-rank {
  flex: none;
  font-size: 26rpx;
  font-weight: 800;
  color: var(--color-brand, #4285f4);
  font-family: var(--font-sans);
  line-height: 1.5;
  min-width: 36rpx;
}
.dc-mk-body { flex: 1; min-width: 0; }
.dc-mk-headline {
  display: flex;
  align-items: flex-start;
  gap: 10rpx;
}
.dc-mk-title {
  font-size: 27rpx;
  font-weight: 600;
  color: var(--color-text-primary);
  line-height: 1.45;
  display: block;
  flex: 1;
  min-width: 0;
}
.dc-conf {
  flex: none;
  font-size: 20rpx;
  font-weight: 600;
  border-radius: 8rpx;
  padding: 2rpx 10rpx;
  line-height: 1.5;
  margin-top: 4rpx;
}
.dc-conf-high { color: #0a7d3e; background: #e6f6ed; }
.dc-conf-medium { color: #b07a00; background: #fdf2dc; }
.dc-conf-low { color: #b23b3b; background: #fbe8e8; }
.dc-mk-change {
  font-size: 24rpx;
  color: var(--color-text-secondary);
  line-height: 1.55;
  margin-top: 6rpx;
  display: block;
}
.dc-mk-impact {
  font-size: 24rpx;
  color: var(--color-text-primary);
  line-height: 1.55;
  margin-top: 6rpx;
  display: block;
}
.dc-mk-watch {
  font-size: 23rpx;
  color: var(--color-text-hint);
  line-height: 1.55;
  margin-top: 4rpx;
  display: block;
}
.dc-mk-foot { margin-top: 8rpx; }
.dc-mk-detail {
  font-size: 22rpx;
  color: var(--color-brand, #4285f4);
  font-weight: 500;
}

/* 值得留意 / 持续关注：紧凑列表 */
.dc-watch {
  display: flex;
  align-items: flex-start;
  gap: 10rpx;
  padding: 7rpx 0;
}
.dc-watch-bullet { color: var(--color-text-hint); line-height: 1.55; }
.dc-watch-text {
  font-size: 25rpx;
  color: var(--color-text-secondary);
  line-height: 1.5;
}
.dc-watch-note { color: var(--color-text-hint); font-size: 22rpx; }

/* 接下来关注 */
.dc-upcoming {
  display: flex;
  align-items: baseline;
  gap: 12rpx;
  padding: 7rpx 0;
}
.dc-upcoming-time {
  flex: none;
  font-size: 22rpx;
  font-weight: 600;
  color: var(--color-text-hint);
}
.dc-upcoming-text {
  font-size: 25rpx;
  color: var(--color-text-secondary);
  line-height: 1.5;
}

/* ═══════════════════════════════════════════════════════════
   PC / Tablet 适配 (≥768px)
   ═══════════════════════════════════════════════════════════ */
@media screen and (min-width: 768px) {
  .dc-title { font-size: 22px; }
  .dc-range { font-size: 14px; }
  .dc-stats { font-size: 13px; }
  .dc-section-title { font-size: 14px; }
  .dc-core-text { font-size: 15px; }
  .dc-core-summary { font-size: 13px; }
  .dc-overview-text { font-size: 15px; }
  .dc-change-label { font-size: 13px; padding: 2px 8px; }
  .dc-change-text { font-size: 15px; }
  .dc-mk-rank { font-size: 15px; min-width: 22px; }
  .dc-mk-title { font-size: 15px; }
  .dc-mk-change { font-size: 14px; }
  .dc-mk-impact { font-size: 14px; }
  .dc-mk-watch { font-size: 13px; }
  .dc-conf { font-size: 12px; }
  .dc-mk-detail { font-size: 13px; }
  .dc-watch-text { font-size: 14px; }
  .dc-upcoming-text { font-size: 14px; }
  .reports-header {
    padding: 28px 0 12px;
  }
  .reports-title {
    font-size: 26px;
    letter-spacing: 0.5px;
  }
  /* 桌面端：页面头不重复显示侧门入口与解锁入口（由左侧导航承载）*/
  .gate-mobile-only { display: none; }
  .gate-reveal-mobile { display: none; }
  .reports-subtitle {
    font-size: 13px;
    margin-top: 4px;
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
    max-width: 760px;
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
    font-size: 13px;
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
    font-size: 13px;
  }

  .load-more {
    padding: 16px 0;
  }
  .load-more-text {
    font-size: 14px;
  }

  /* Reports */
}

@media screen and (min-width: 1200px) {
  /* ── Reports 字号放大（再次上调 ~20%）── */
  .digest-card { padding: 32px 36px; margin: 28px 32px; max-width: none; }
  .dc-title { font-size: 27px; }
  .dc-range { font-size: 17px; }
  .dc-stats { font-size: 16px; }
  .dc-section-title { font-size: 19px; }
  .dc-core-text { font-size: 19px; line-height: 1.7; }
  .dc-core-summary { font-size: 16px; }
  .dc-overview-text { font-size: 19px; line-height: 1.7; }
  .dc-change-label { font-size: 15px; }
  .dc-change-text { font-size: 19px; line-height: 1.7; }
  .dc-mk-rank { font-size: 19px; min-width: 28px; }
  .dc-mk-title { font-size: 19px; line-height: 1.6; }
  .dc-mk-change { font-size: 18px; line-height: 1.65; }
  .dc-mk-impact { font-size: 18px; line-height: 1.65; }
  .dc-mk-watch { font-size: 16px; }
  .dc-conf { font-size: 14px; }
  .dc-mk-detail { font-size: 16px; }
  .dc-watch-text { font-size: 18px; }
  .dc-upcoming-text { font-size: 18px; }
  .reports-title { font-size: 32px; }
}
/* ── IconSvg 适配（替代 emoji）── */
.badge-icon { flex: none; }
.right-news-rank { flex: none; color: var(--color-brand); }
.sb-ico,
.sb-ico-sm { flex: none; margin-right: 3px; }
.sb-changed-text,
.sb-event-change,
.sb-event-watch { display: inline-flex; align-items: center; }

</style>
