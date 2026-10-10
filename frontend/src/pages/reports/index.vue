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

      <!-- 时间筛选：按日期 + 时段过滤简报 -->
      <view class="rpt-filter">
        <view class="rf-row">
          <view class="rf-label">
            <IconSvg name="calendar" :size="15" class="rf-label-ico" />
            <text class="rf-label-text">日期</text>
          </view>
          <scroll-view class="rf-scroll" scroll-x :show-scrollbar="false">
            <view class="rf-chips">
              <view
                class="rf-chip"
                :class="{ 'rf-chip-on': filterDate === '' }"
                @click="pickDate('')"
              >
                <text class="rf-chip-text">全部</text>
              </view>
              <view
                v-for="d in dateOptions"
                :key="d.value"
                class="rf-chip"
                :class="{ 'rf-chip-on': filterDate === d.value }"
                @click="pickDate(d.value)"
              >
                <text class="rf-chip-text">{{ d.label }}</text>
              </view>
            </view>
          </scroll-view>
          <picker mode="date" :value="pickerValue" :end="todayStr" @change="onDateChange">
            <view class="rf-date" :class="{ 'rf-date-on': filterDate }">
              <IconSvg name="calendar" :size="13" class="rf-date-ico" />
              <text class="rf-date-text">{{ filterDate || '自定义' }}</text>
            </view>
          </picker>
        </view>

        <view class="rf-row rf-row-period">
          <view class="rf-label">
            <IconSvg name="clock" :size="15" class="rf-label-ico" />
            <text class="rf-label-text">时段</text>
          </view>
          <scroll-view class="rf-scroll" scroll-x :show-scrollbar="false">
            <view class="rf-chips">
              <view
                v-for="p in PERIOD_OPTIONS"
                :key="p.value"
                class="rf-chip"
                :class="{ 'rf-chip-on': filterPeriod === p.value }"
                @click="pickPeriod(p.value)"
              >
                <text class="rf-chip-text">{{ p.label }}</text>
              </view>
            </view>
          </scroll-view>
        </view>

        <view v-if="filterDate || filterPeriod" class="rf-reset" @click="resetFilter">
          <IconSvg name="close" :size="12" class="rf-reset-ico" />
          <text class="rf-reset-text">清除筛选</text>
        </view>
      </view>

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
        :text="filterDate || filterPeriod !== 'all' ? '该条件下暂无简报' : '暂无新闻概览'"
        mobile-padding="120rpx 0"
        desktop-padding="60px 0"
      />

      <!-- Timeline -->
      <view v-if="!digestLoading && digestList.length > 0" class="timeline">
        <view v-for="(g, gi) in groupedDigests" :key="g.key" class="tl-group">
          <!-- 日期分组标题：26.10.10 周六 -->
          <view class="tl-date">
            <view class="tl-date-bar"></view>
            <text class="tl-date-main">{{ g.dateMain }}</text>
            <text class="tl-date-week">{{ g.weekday }}</text>
            <text class="tl-date-count">{{ g.items.length }} 份简报</text>
          </view>

          <view
            v-for="(item, idx) in g.items"
            :key="item.id"
            :id="'digest-' + item.id"
            class="timeline-item"
          >
            <!-- Timeline connector -->
            <view class="timeline-rail">
              <view class="timeline-dot" :class="'dot-' + item.period_label"></view>
              <view v-if="showRailLine(gi, idx)" class="timeline-line"></view>
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
                  <text v-if="e.sources && e.sources.length" class="dc-mk-src">信源：{{ e.sources.join(' / ') }}</text>
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
                <text class="dc-watch-text">{{ e.title }}<text v-if="e.sources && e.sources.length" class="dc-watch-src"> · {{ e.sources.join(' / ') }}</text></text>
              </view>
            </view>

            <!-- 持续关注（持续事件 + 此前关注暂无进展）-->
            <view v-if="ongoingList(item).length" class="dc-section">
              <text class="dc-section-title">持续关注</text>
              <view v-for="e in ongoingList(item)" :key="e.event_id" class="dc-watch">
                <text class="dc-watch-bullet">—</text>
                <text class="dc-watch-text">{{ e.title }}<text v-if="e.sources && e.sources.length" class="dc-watch-src"> · {{ e.sources.join(' / ') }}</text><text v-if="e.note" class="dc-watch-note"> · {{ e.note }}</text></text>
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
          </view><!-- /digest-card -->
        </view><!-- /timeline-item -->
        </view><!-- /tl-group -->
      </view><!-- /timeline -->
      <view v-if="!digestLoading && digestList.length > 0 && digestDays < 30 && !filterDate" class="load-more" @click="loadMoreDigests">
        <text class="load-more-text">加载更多</text>
      </view>
    </view>

    <!-- Footer -->
    <SiteFooter />
    </view><!-- /container -->
  </view><!-- /page-layout -->
</template>

<script setup>
import { ref, reactive, computed, onMounted, nextTick } from 'vue'
import mpHtml from 'mp-html/dist/uni-app/components/mp-html/mp-html.vue'
import { fetchDigests } from '@/utils/api'
import { renderMarkdown } from '@/utils/markdown'
import SiteFooter from '@/components/common/SiteFooter.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import PcSidebar from '@/components/common/PcSidebar.vue'
import GateButton from '@/components/common/GateButton.vue'
import IconSvg from '@/components/common/IconSvg.vue'
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

// ── 时间筛选：日期 + 时段 ──
const filterDate = ref('')      // '' = 全部；否则 'YYYY-MM-DD'
const filterPeriod = ref('all') // all / morning / midday / evening / night
const PERIOD_OPTIONS = [
  { value: 'all', label: '全部' },
  { value: 'morning', label: '早间' },
  { value: 'midday', label: '午间' },
  { value: 'evening', label: '晚间' },
  { value: 'night', label: '夜间' },
]

// 日期工具：本地时区，避免 toISOString 的 UTC 偏移
function toDateStr(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const todayStr = toDateStr(new Date())
const pickerValue = computed(() => filterDate.value || todayStr)

// 快捷日期：今天 / 昨天 / 前天 / 更早（最近 7 天，倒序）
const dateOptions = computed(() => {
  const WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  const out = []
  for (let i = 0; i < 4; i++) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    out.push({
      value: toDateStr(d),
      label: i === 0 ? '今天' : i === 1 ? '昨天' : i === 2 ? '前天' : `${d.getMonth() + 1}.${d.getDate()}`,
    })
  }
  return out
})

// 前端过滤后的列表（时段在前端过滤，日期走后端 date 参数）
const visibleDigests = computed(() =>
  filterPeriod.value === 'all'
    ? digestList.value
    : digestList.value.filter((d) => d.period_label === filterPeriod.value)
)

// 按日期分组：26.10.10 周六 · N 份简报
const groupedDigests = computed(() => {
  const WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  const groups = []
  const map = new Map()
  for (const item of visibleDigests.value) {
    const raw = item.digest_date || (item.period_start || '').slice(0, 10)
    if (!raw) continue
    const d = new Date(`${raw}T00:00:00`)
    if (!map.has(raw)) {
      const g = {
        key: raw,
        dateMain: `${String(d.getFullYear()).slice(2)}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`,
        weekday: WEEK[d.getDay()] || '',
        items: [],
      }
      map.set(raw, g)
      groups.push(g)
    }
    map.get(raw).items.push(item)
  }
  return groups
})

// 时间轴竖线：仅在本组还有下一条、或后面还有分组时延续
function showRailLine(gi, idx) {
  const g = groupedDigests.value[gi]
  if (!g) return false
  if (idx < g.items.length - 1) return true
  return gi < groupedDigests.value.length - 1
}

function pickDate(v) {
  if (filterDate.value === v) return
  filterDate.value = v
  loadDigests()
}
function onDateChange(e) {
  filterDate.value = e.detail.value || ''
  loadDigests()
}
function pickPeriod(v) {
  filterPeriod.value = v
}
function resetFilter() {
  filterDate.value = ''
  filterPeriod.value = 'all'
  loadDigests()
}

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
    const data = await fetchDigests(digestDays.value, filterDate.value)
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
    // 选了具体日期时放宽 days（后端按 date 精确过滤，days 仅作兜底）
    const days = filterDate.value ? 30 : digestDays.value
    const data = await fetchDigests(days, filterDate.value)
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

/* ── 时间筛选（日期 + 时段）── */
.rpt-filter {
  margin-top: 12rpx;
  padding: 0;
  background: transparent;
  border: none;
  border-radius: 0;
  max-width: none;
}
.rf-row {
  display: flex;
  align-items: flex-start;
  gap: 12rpx;
}
.rf-row-period {
  margin-top: 8rpx;
}
.rf-label {
  flex: none;
  display: flex;
  align-items: center;
  gap: 4rpx;
  width: 60rpx;
  height: 44rpx;
  color: var(--color-text-muted, #8c8c9a);
}
.rf-label-ico {
  flex: none;
  opacity: 0.7;
}
.rf-label-text {
  font-size: 22rpx;
  font-weight: 500;
  color: var(--color-text-muted, #8c8c9a);
  letter-spacing: 0;
}
.rf-scroll {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
}
.rf-chips {
  display: inline-flex;
  gap: 8rpx;
  padding: 2rpx 0;
}
.rf-chip {
  flex: none;
  padding: 6rpx 16rpx;
  border-radius: 20rpx;
  background: var(--color-bg-secondary, #f5f7fa);
  border: none;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
.rf-chip:active {
  background: var(--color-bg-active, #f5f6f8);
}
.rf-chip-on {
  background: var(--color-bg-info-soft, #e8f0fe);
}
.rf-chip-text {
  font-size: 22rpx;
  color: var(--color-text-tertiary, #5a5a6e);
  font-weight: 500;
  line-height: 1.4;
  white-space: nowrap;
}
.rf-chip-on .rf-chip-text {
  color: var(--color-brand, #4285f4);
  font-weight: 600;
}
.rf-chip-on .rf-chip-text {
  color: var(--color-brand, #4285f4);
  font-weight: 600;
}
.rf-date {
  flex: none;
  display: flex;
  align-items: center;
  gap: 6rpx;
  padding: 6rpx 14rpx;
  border-radius: 20rpx;
  background: var(--color-bg-secondary, #f5f7fa);
  border: none;
  cursor: pointer;
}
.rf-date-on {
  background: var(--color-bg-info-soft, #e8f0fe);
}
.rf-date-ico {
  flex: none;
  color: var(--color-text-muted, #8c8c9a);
}
.rf-date-on {
  background: var(--color-brand-light, rgba(66, 133, 244, 0.08));
  border-color: var(--color-brand, #4285f4);
}
.rf-date-on .rf-date-ico,
.rf-date-on .rf-date-text {
  color: var(--color-brand, #4285f4);
}
.rf-date-text {
  font-size: 22rpx;
  color: var(--color-text-tertiary, #5a5a6e);
  font-weight: 500;
  white-space: nowrap;
}
.rf-date-on .rf-date-text {
  color: var(--color-brand, #4285f4);
  font-weight: 600;
}
.rf-reset {
  display: inline-flex;
  align-items: center;
  gap: 4rpx;
  align-self: flex-start;
  margin-top: 8rpx;
  padding: 4rpx 0;
  background: transparent;
  cursor: pointer;
}
.rf-reset-ico {
  flex: none;
  color: var(--color-text-muted, #8c8c9a);
}
.rf-reset-text {
  font-size: 22rpx;
  color: var(--color-text-muted, #8c8c9a);
  font-weight: 500;
}

/* ── 日期分组标题：26.10.10 周六 · 2 份简报 ── */
.tl-group {
  margin-bottom: 8rpx;
}
.tl-date {
  display: flex;
  align-items: center;
  gap: 8rpx;
  padding: 16rpx 0 8rpx 0;
}
.tl-date-bar {
  width: 4rpx;
  height: 22rpx;
  border-radius: 2rpx;
  background: var(--color-brand, #4285f4);
  flex: none;
}
.tl-date-main {
  font-size: 24rpx;
  font-weight: 600;
  color: var(--color-text-secondary, #3a3a4a);
  letter-spacing: 0;
}
.tl-date-week {
  flex: none;
  padding: 2rpx 10rpx;
  border-radius: 20rpx;
  background: var(--color-bg-info-soft, #e8f0fe);
  font-size: 20rpx;
  font-weight: 500;
  color: var(--color-text-tertiary, #5a5a6e);
}
.tl-date-count {
  margin-left: auto;
  font-size: 22rpx;
  color: var(--color-text-muted, #8c8c9a);
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
.dc-mk-src {
  font-size: 22rpx;
  color: var(--color-text-hint);
  line-height: 1.55;
  margin-top: 6rpx;
  display: block;
}
.dc-watch-src { color: var(--color-text-hint); font-size: 22rpx; }
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
  .dc-mk-src { font-size: 12px; }
  .dc-watch-src { font-size: 13px; }
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

  /* 时间筛选 */
  .rpt-filter {
    margin-top: 14px;
    padding: 0;
    border-radius: 0;
    border-width: 0;
    max-width: 760px;
  }
  .rf-row { gap: 8px; align-items: flex-start; }
  .rf-row-period { margin-top: 6px; }
  .rf-label { width: 48px; height: 26px; gap: 3px; }
  .rf-label-text { font-size: 13px; }
  .rf-chips { gap: 6px; }
  .rf-chip {
    padding: 3px 10px;
    border-radius: 12px;
  }
  .rf-chip-text { font-size: 13px; }
  .rf-date { padding: 3px 10px; border-radius: 12px; gap: 4px; }
  .rf-date-text { font-size: 13px; }
  .rf-reset { margin-top: 8px; padding: 2px 0; gap: 3px; }
  .rf-reset-text { font-size: 13px; }

  /* 日期分组标题 */
  .tl-group { margin-bottom: 4px; }
  .tl-date { gap: 8px; padding: 18px 0 8px 0; }
  .tl-date-bar { width: 3px; height: 15px; border-radius: 2px; }
  .tl-date-main { font-size: 15px; font-weight: 600; }
  .tl-date-week { font-size: 13px; padding: 2px 8px; border-radius: 12px; }
  .tl-date-count { font-size: 13px; }

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
  /* ── Reports 桌面档：原为100%缩放下的放大版，现固化80%缩放的紧凑观感 ── */
  .digest-card { padding: 26px 29px; margin: 22px 26px; max-width: none; }
  .dc-title { font-size: 22px; }
  .dc-range { font-size: 14px; }
  .dc-stats { font-size: 13px; }
  .dc-section-title { font-size: 15px; }
  .dc-core-text { font-size: 15px; line-height: 1.7; }
  .dc-core-summary { font-size: 13px; }
  .dc-overview-text { font-size: 15px; line-height: 1.7; }
  .dc-change-label { font-size: 12px; }
  .dc-change-text { font-size: 15px; line-height: 1.7; }
  .dc-mk-rank { font-size: 15px; min-width: 22px; }
  .dc-mk-title { font-size: 15px; line-height: 1.6; }
  .dc-mk-change { font-size: 14px; line-height: 1.65; }
  .dc-mk-impact { font-size: 14px; line-height: 1.65; }
  .dc-mk-watch { font-size: 13px; }
  .dc-mk-src { font-size: 12px; }
  .dc-watch-src { font-size: 13px; }
  .dc-conf { font-size: 11px; }
  .dc-mk-detail { font-size: 13px; }
  .dc-watch-text { font-size: 14px; }
  .dc-upcoming-text { font-size: 14px; }
  .reports-title { font-size: 26px; }

  /* 时间筛选 —— 对齐现网 .filter-tag：无边框、紧凑文字 */
  .rpt-filter { padding: 0; max-width: none; }
  .rf-row { gap: 6px; align-items: flex-start; }
  .rf-row-period { margin-top: 5px; }
  .rf-label { width: 44px; height: 22px; gap: 3px; }
  .rf-label-text { font-size: 11px; }
  .rf-chips { gap: 5px; }
  .rf-chip {
    padding: 2px 8px;
    border-radius: 10px;
  }
  .rf-chip-text { font-size: 11px; }
  .rf-date { padding: 2px 8px; border-radius: 10px; gap: 3px; }
  .rf-date-text { font-size: 11px; }
  .rf-reset { margin-top: 6px; padding: 2px 0; gap: 3px; }
  .rf-reset-text { font-size: 11px; }

  /* 日期分组标题 —— 轻量分组标记，不抢卡片标题层级 */
  .tl-date { gap: 5px; padding: 12px 0 5px 0; }
  .tl-date-bar { width: 3px; height: 12px; border-radius: 2px; }
  .tl-date-main { font-size: 12px; font-weight: 600; }
  .tl-date-week { font-size: 11px; padding: 2px 7px; border-radius: 10px; }
  .tl-date-count { font-size: 11px; }
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
