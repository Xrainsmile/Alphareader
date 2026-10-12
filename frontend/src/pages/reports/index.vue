<template>
  <view class="page-layout">
    <PcSidebar active="reports" @open-settings="showSettings = true" @open-score="showScore = true" />
    <view class="container">
    <!-- Header -->
    <view class="reports-header">
      <view class="reports-head-info">
        <view class="reports-title-row">
          <text class="reports-title">每日简报</text>
          <!-- 移动端：侧门「!」入口（桌面端由左侧导航承载，此处隐藏）-->
          <GateButton class="gate-mobile-only" />
        </view>
        <text class="reports-subtitle">读懂发生了什么，也看清下一步关注什么。</text>
      </view>

      <!-- 时间筛选：分段控件（快捷日期）+ 日历按钮，桌面端居 header 右侧 -->
      <view class="rpt-filter">
        <view class="rf-reset" :class="{ 'rf-reset-on': !!filterDate }" @click="filterDate && resetFilter()">
          <text class="rf-reset-text">清除</text>
        </view>

        <view class="rf-seg">
          <view
            class="rf-seg-item"
            :class="{ 'rf-seg-on': filterDate === '' }"
            @click="pickDate('')"
          >
            <text class="rf-seg-text">全部</text>
          </view>
          <view
            v-for="d in dateOptions"
            :key="d.value"
            class="rf-seg-item"
            :class="{ 'rf-seg-on': filterDate === d.value }"
            @click="pickDate(d.value)"
          >
            <text class="rf-seg-text">{{ d.label }}</text>
          </view>
        </view>

        <picker mode="date" :value="pickerValue" :end="todayStr" @change="onDateChange">
          <view class="rf-cal" :class="{ 'rf-cal-on': filterDate && !isQuickDate }">
            <IconSvg name="calendar" :size="13" class="rf-cal-ico" />
            <text class="rf-cal-text">{{ calLabel }}</text>
            <text class="rf-cal-arrow">▾</text>
          </view>
        </picker>
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
  :text="filterDate ? '该日期暂无简报' : '暂无新闻概览'"
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
            <text class="tl-date-count">{{ g.items.length }} briefings</text>
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
                {{ exportingId === item.id ? 'Exporting…' : 'Export Image' }}
              </text>
            </view>
            <view class="dc-stats">
              <text class="dc-stat">{{ item.event_count || 0 }} events</text>
              <text class="dc-sep">·</text>
              <text class="dc-stat">{{ item.material_update_count || 0 }} updates</text>
              <text class="dc-sep">·</text>
              <text class="dc-stat">{{ (sc(item).must_know || []).length }} must-know</text>
            </view>

            <!-- 首屏结论：只保留三条变化，长解释折叠
                 设计原则：period_summary / what_changed 为长句解释，默认收起，
                 Key Changes 为可扫读要点，常驻首屏。 -->
            <view v-if="sc(item).cross_event_signals && sc(item).cross_event_signals.length" id="sec-changes" class="dc-section dc-core">
              <view
                class="dc-core-head"
                @click.stop="toggleBrief(item.id)"
              >
                <text class="dc-section-title dc-core-title">本期核心变化</text>
                <text v-if="hasBriefDetail(item)" class="dc-brief-toggle">{{ briefOpen(item.id) ? '收起' : '为什么' }}</text>
              </view>
              <view v-for="(s, si) in topSignals(item)" :key="si" class="dc-core-item">
                <text class="dc-core-dot">•</text>
                <view class="dc-core-body">
                  <text class="dc-core-text">{{ s.title }}</text>
                  <text v-if="s.summary && briefOpen(item.id)" class="dc-core-summary">{{ s.summary }}</text>
                </view>
              </view>
            </view>

            <!-- 无 Key Changes 时的折叠入口兜底，避免长解释无法展开 -->
            <view
              v-else-if="hasBriefDetail(item)"
              class="dc-brief-fallback"
              @click.stop="toggleBrief(item.id)"
            >
              <text class="dc-brief-toggle">{{ briefOpen(item.id) ? 'Hide Brief' : 'Read Brief' }}</text>
            </view>

            <!-- 详细解释（默认折叠）-->
            <view v-if="hasBriefDetail(item)" v-show="briefOpen(item.id)" class="dc-section dc-overview dc-overview-fold">
              <text v-if="sc(item).what_changed" class="dc-change dc-change-standalone">
                <text class="dc-change-inline-label">本期变化 · </text>{{ sc(item).what_changed }}
              </text>
              <text v-if="sc(item).period_summary" class="dc-overview-text dc-overview-detail">{{ sc(item).period_summary }}</text>
            </view>

            <!-- 必须知道（编号体现优先级，次级信息收进事件详情页）-->
            <view id="sec-mustknow" v-if="sc(item).must_know && sc(item).must_know.length" class="dc-section">
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
                  <text v-if="e.why_important" class="dc-mk-impact">Impact: {{ e.why_important }}</text>
                  <text v-if="e.watch_next" class="dc-mk-watch">Watch: {{ e.watch_next }}</text>
                  <text v-if="e.sources && e.sources.length" class="dc-mk-src">Sources: {{ e.sources.join(' / ') }}</text>
                  <view class="dc-mk-foot" @click.stop="goEventDetail(e.event_id)">
                    <text class="dc-mk-detail">Details →</text>
                  </view>
                </view>
              </view>
            </view>

            <!-- 值得留意（紧凑列表）-->
            <view v-if="sc(item).worth_watching && sc(item).worth_watching.length" class="dc-section">
              <text class="dc-section-title">持续关注</text>
              <view v-for="e in sc(item).worth_watching" :key="e.event_id" class="dc-watch">
                <text class="dc-watch-bullet">—</text>
                <text class="dc-watch-text">{{ e.title }}<text v-if="e.sources && e.sources.length" class="dc-watch-src"> · {{ e.sources.join(' / ') }}</text></text>
              </view>
            </view>

            <!-- 持续关注（持续事件 + 此前关注暂无进展）-->
            <view v-if="ongoingList(item).length" class="dc-section">
              <text class="dc-section-title">进行中</text>
              <view v-for="e in ongoingList(item)" :key="e.event_id" class="dc-watch">
                <text class="dc-watch-bullet">—</text>
                <text class="dc-watch-text">{{ e.title }}<text v-if="e.sources && e.sources.length" class="dc-watch-src"> · {{ e.sources.join(' / ') }}</text><text v-if="e.note" class="dc-watch-note"> · {{ e.note }}</text></text>
              </view>
            </view>

            <!-- 接下来关注 -->
            <view id="sec-next" v-if="sc(item).upcoming && sc(item).upcoming.length" class="dc-section">
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

    <!-- 右侧栏：简报阅读导航（章节跳转 + 说明），仅 PC 显示 -->
    <view class="pc-rail">
      <view class="rail-block">
        <text class="rail-title">本期阅读导航</text>
        <view
          v-for="sec in railSections"
          :key="sec.id"
          class="toc-item"
          @click="scrollToSection(sec.id)"
        >
          <text class="toc-num">{{ sec.num }}</text>
          <text class="toc-label">{{ sec.label }}</text>
        </view>
        <text class="rail-dim">约 3 分钟读完重点</text>
      </view>

      <view class="rail-block">
        <text class="rail-title">事实与判断，分别呈现</text>
        <text class="rail-note">评分表示阅读优先级；确定性表示事实依据的充分程度。</text>
        <text class="rail-link" @click="showScore = true">了解评分与信源</text>
      </view>
    </view>

    <SettingsDialog :visible="showSettings" @close="showSettings = false" />
    <ScoreInfoDialog :visible="showScore" @close="showScore = false" />
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
import SettingsDialog from '@/components/common/SettingsDialog.vue'
import ScoreInfoDialog from '@/components/common/ScoreInfoDialog.vue'
import GateButton from '@/components/common/GateButton.vue'
import IconSvg from '@/components/common/IconSvg.vue'
import { useGate } from '@/utils/useGate'
import { listTagStyle, listTagStyleMobile } from '@/utils/formatters'
import { exportDigestImage, canExportImage } from '@/utils/digestExport'
import { usePcNavFrame } from '@/utils/usePcNav.js'

// 导航框架：桌面端隐藏原生 tabBar（已有 PcSidebar），避免重复导航
usePcNavFrame()

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

// ── 时间筛选：日期 ──
const filterDate = ref('')      // '' = 全部；否则 'YYYY-MM-DD'

// 日期工具：本地时区，避免 toISOString 的 UTC 偏移
function toDateStr(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
const todayStr = toDateStr(new Date())
const pickerValue = computed(() => filterDate.value || todayStr)

// Calendar button label: 'Pick Date' when unfiltered; matched quick date; else 2026.10.10
const isQuickDate = computed(() => dateOptions.value.some((d) => d.value === filterDate.value))
const calLabel = computed(() => {
  if (!filterDate.value) return 'Pick Date'
  if (isQuickDate.value) return filterDate.value.split('-').slice(1).join('.')
  const [y, m, dd] = filterDate.value.split('-')
  return `${y}.${m}.${dd}`
})

// Quick dates: Today / Yesterday
const dateOptions = computed(() => {
  const out = []
  for (let i = 0; i < 2; i++) {
    const d = new Date()
    d.setDate(d.getDate() - i)
    out.push({ value: toDateStr(d), label: i === 0 ? 'Today' : 'Yesterday' })
  }
  return out
})

// 按日期分组：26.10.10 Sat · N briefings（日期过滤走后端 date 参数）
const groupedDigests = computed(() => {
  const WEEK = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  const groups = []
  const map = new Map()
  for (const item of digestList.value) {
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
function resetFilter() {
  filterDate.value = ''
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

const showSettings = ref(false)
const showScore = ref(false)

/** 右栏阅读导航：与正文三个章节一一对应 */
const railSections = [
  { id: 'sec-changes', num: '01', label: '本期核心变化' },
  { id: 'sec-mustknow', num: '02', label: '必须知道' },
  { id: 'sec-next', num: '03', label: '接下来关注' },
]

function scrollToSection(id) {
  // 用 scrollIntoView 语义：uni 下退化为按当前滚动偏移叠加元素位置
  uni.createSelectorQuery()
    .select('#' + id)
    .boundingClientRect((rect) => {
      if (!rect) return
      uni.pageScrollTo({ scrollTop: rect.top, duration: 260 })
    })
    .exec()
}

/** 简报详情（长解释）展开状态：默认收起，首屏只留 Key Changes 三条变化 */
const briefOpenIds = reactive(new Set())
function briefOpen(id) {
  return briefOpenIds.has(id)
}
function toggleBrief(id) {
  briefOpenIds.has(id) ? briefOpenIds.delete(id) : briefOpenIds.add(id)
}
/** 首屏最多三条变化，其余收进折叠区 */
function topSignals(item) {
  return (sc(item).cross_event_signals || []).slice(0, 3)
}
/** 是否存在可折叠的长解释（无内容时不显示 Why 按钮） */
function hasBriefDetail(item) {
  const s = sc(item)
  return Boolean(s.period_summary || s.what_changed)
}
// 确定性标签：high/medium/low → 中文短标签（must_know 卡片展示）
function confLabel(c) {
  return { high: 'High Confidence', medium: 'Medium Confidence', low: 'Low Confidence' }[c] || ''
}
// 持续关注 = 持续事件(ongoing_updates) + 此前关注暂无进展(quiet_topics)
function ongoingList(item) {
  const s = sc(item)
  return [...(s.ongoing_updates || []), ...(s.quiet_topics || [])]
}
// 时段范围：优先用后端已算好的 period_range_label（跨日已处理）；
// 无则本地兜底生成「MM-DD HH:mm—MM-DD HH:mm（时区）」，跨日必写完整，
// 避免「10-10 17:30—03:30」这类让人误以为时间倒流的表达。
function formatPeriodRange(item) {
  // 后端已提供中文区间标签（含跨日），直接采用
  if (item.period_range_label) return item.period_range_label

  const fmt = (iso, withDate) => {
    const d = new Date(iso)
    const md = `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
    return withDate ? `${md} ${hm}` : hm
  }
  if (!item.period_start || !item.period_end) return ''

  const s = new Date(item.period_start)
  const e = new Date(item.period_end)
  // 跨日判定：起止不在同一天 → 两端都带日期
  const crossDay = s.toDateString() !== e.toDateString()

  const range = crossDay
    ? `${fmt(item.period_start, true)}—${fmt(item.period_end, true)}`
    : `${fmt(item.period_start, true)}—${fmt(item.period_end, false)}`

  return `${range} ${tzLabel()}`
}

// 时区标签：明确告知用户时间基准，避免跨时区误读
function tzLabel() {
  // #ifdef H5
  const off = -new Date().getTimezoneOffset() / 60
  const sign = off >= 0 ? '+' : '-'
  const abs = Math.abs(off)
  const hh = Number.isInteger(abs) ? String(abs) : abs.toFixed(1)
  return `(UTC${sign}${hh})`
  // #endif
  // #ifndef H5
  return ''
  // #endif
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
    uni.showToast({ title: 'Open in a browser to export', icon: 'none' })
    return
  }
  if (exportingId.value) return // 防连点
  exportingId.value = item.id
  try {
    await exportDigestImage(item)
  } catch (e) {
    console.warn('导出简报图片失败:', e)
    uni.showToast({ title: e.message || 'Export failed', icon: 'none' })
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
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16rpx;
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
  border-radius: var(--radius-r-full);
  background: var(--color-bg-brand-light, var(--color-bg-brand-softer));
  color: var(--color-brand, var(--color-brand));
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

/* ── 时间筛选：分段控件 + 日历按钮（对齐参考稿 header 右侧设计）── */
.reports-head-info {
  min-width: 0;
}
.rpt-filter {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12rpx;
}
/* 分段控件：白底容器 + 品牌蓝实底选中项 */
.rf-seg {
  display: inline-flex;
  align-items: center;
  background: var(--color-bg-primary, #fff);
  border: 1rpx solid var(--color-border-light, var(--color-bg-neutral-tint));
  border-radius: var(--radius-r-3xl);
  padding: 4rpx;
  box-shadow: 0 1rpx 4rpx rgba(15, 23, 42, 0.04);
}
.rf-seg-item {
  padding: 8rpx 24rpx;
  border-radius: var(--radius-r-2xl);
  cursor: pointer;
  transition: background 0.15s ease;
}
.rf-seg-item:active {
  background: var(--color-bg-secondary, #f4f6f9);
}
.rf-seg-on {
  background: var(--color-brand, var(--color-info-hover));
  box-shadow: 0 1px 2px rgba(37, 99, 235, 0.18);
}
.rf-seg-on:active {
  background: var(--color-brand, var(--color-info-hover));
}
.rf-seg-text {
  font-size: 24rpx;
  font-weight: 500;
  color: var(--color-text-tertiary, #64748b);
  line-height: 1.4;
  white-space: nowrap;
}
.rf-seg-on .rf-seg-text {
  color: #fff;
  font-weight: 600;
}
/* 日历按钮：白底胶囊，图标+日期+下拉箭头 */
.rf-cal {
  display: inline-flex;
  align-items: center;
  gap: 8rpx;
  padding: 12rpx 20rpx;
  background: var(--color-bg-primary, #fff);
  border: 1rpx solid var(--color-border-light, var(--color-bg-neutral-tint));
  border-radius: var(--radius-r-3xl);
  box-shadow: 0 1rpx 4rpx rgba(15, 23, 42, 0.04);
  cursor: pointer;
}
.rf-cal:active {
  border-color: var(--color-brand, var(--color-info-hover));
}
.rf-cal-ico {
  flex: none;
  color: var(--color-brand, var(--color-info-hover));
}
.rf-cal-text {
  font-size: 24rpx;
  font-weight: 500;
  color: var(--color-text-secondary, #475569);
  line-height: 1.4;
  white-space: nowrap;
}
.rf-cal-arrow {
  flex: none;
  font-size: 18rpx;
  color: var(--color-text-muted, #94a3b8);
  line-height: 1;
}
.rf-cal-on {
  border-color: rgba(37, 99, 235, 0.4);
}
.rf-cal-on .rf-cal-text {
  color: var(--color-brand, var(--color-info-hover));
  font-weight: 600;
}
.rf-reset {
  display: inline-flex;
  align-items: center;
  padding: 8rpx 4rpx;
  background: transparent;
  cursor: pointer;
  visibility: hidden;
}
.rf-reset-on {
  visibility: visible;
}
.rf-reset-text {
  font-size: 24rpx;
  color: var(--color-text-muted, #8a97ab);
  font-weight: 500;
}
.rf-reset-text:active {
  color: var(--color-brand, var(--color-info-hover));
}

/* ── 日期分组标题：26.10.10 Sat · 2 briefings ── */
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
  border-radius: var(--radius-r-xs);
  background: var(--color-brand, var(--color-brand));
  flex: none;
}
.tl-date-main {
  font-size: 24rpx;
  font-weight: 600;
  color: var(--color-text-secondary, var(--color-text-secondary));
  letter-spacing: 0;
}
.tl-date-week {
  flex: none;
  padding: 8rpx 14rpx;
  border-radius: var(--radius-r-2xl);
  background: var(--color-bg-info-soft, #e8f0fe);
  font-size: 20rpx;
  font-weight: 500;
  color: var(--color-text-tertiary, var(--color-text-tertiary));
}
.tl-date-count {
  margin-left: auto;
  font-size: 22rpx;
  color: var(--color-text-muted, var(--color-text-muted));
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
  z-index: var(--z-base);
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
  border-radius: var(--radius-r-md);
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
  border-radius: var(--radius-r-2xl);
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
  border-radius: var(--radius-r-full);
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
  font-size: 22rpx;
  font-weight: 600;
  color: var(--color-text-placeholder);
  letter-spacing: 2rpx;
  margin-bottom: 12rpx;
  display: block;
}

/* 时段概览 + 本期变化
   层级原则：最强强调只给「本期变化」（左侧色条 + 品牌色标签），
   概览正文回归普通正文样式，不再用大块浅蓝底与多个小标题争夺注意力。 */
.dc-overview {
  background: transparent;
  padding: 0;
}
.dc-overview-text {
  font-size: 27rpx;
  color: var(--color-text-body);
  line-height: 1.75;
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
  background: var(--color-brand, var(--color-brand));
  border-radius: var(--radius-r-md);
  padding: 8rpx 14rpx;
  line-height: 1.5;
  margin-top: 2rpx;
}
.dc-change-text {
  font-size: 26rpx;
  color: var(--color-text-primary);
  line-height: 1.6;
  font-weight: 600;
}

/* 首屏要点：可点击标题行 + Why 折叠入口 */
.dc-core-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16rpx;
}
.dc-core-title {
  margin-bottom: 0;
}
.dc-brief-toggle {
  flex: none;
  font-size: 21rpx;
  font-weight: 600;
  color: var(--color-brand);
  background: var(--color-brand-light);
  border-radius: var(--radius-r-md);
  padding: 6rpx 16rpx;
  line-height: 1.5;
}

/* 核心变化：唯一强调色，浅底突出 */
.dc-core {
  background: var(--color-bg-brand-light, var(--color-bg-brand-softer));
  border-radius: var(--radius-r-md);
  padding: 16rpx 20rpx;
}
.dc-core-item {
  display: flex;
  align-items: flex-start;
  gap: 10rpx;
  margin-top: 8rpx;
}
.dc-core-dot { color: var(--color-brand, var(--color-brand)); font-weight: 700; line-height: 1.6; flex: none; }
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

.dc-brief-fallback {
  margin-top: 16rpx;
  display: flex;
}
.dc-overview-fold {
  margin-top: 16rpx;
  padding: 16rpx 20rpx;
  border-left: 3rpx solid var(--color-border-light, #e2e8f0);
  background: var(--color-bg-softer, #fafbfc);
}
.dc-change-standalone {
  display: block;
  border-top: none;
  padding-top: 0;
  margin-top: 0;
  color: var(--color-text-secondary);
  font-weight: 500;
  font-size: 25rpx;
  line-height: 1.65;
}
.dc-change-inline-label {
  color: var(--color-brand);
  font-weight: 700;
}
.dc-overview-detail {
  margin-top: 12rpx;
  font-size: 24rpx;
  color: var(--color-text-secondary);
  line-height: 1.7;
}

/* 必须知道：编号体现优先级 */
.dc-mk {
  display: flex;
  align-items: flex-start;
  gap: 14rpx;
  padding: 14rpx 0;
  border-bottom: 1rpx solid var(--color-border-light, var(--color-bg-active-press));
}
.dc-mk:last-child { border-bottom: none; }
.dc-mk-rank {
  flex: none;
  font-size: 26rpx;
  font-weight: 800;
  color: var(--color-brand, var(--color-brand));
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
  border-radius: var(--radius-r-md);
  padding: 8rpx 14rpx;
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
  color: var(--color-brand, var(--color-brand));
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
  .dc-section-title { font-size: 13px; font-weight: 600; color: var(--color-text-placeholder); }
  .dc-core-text { font-size: 15px; line-height: 1.75; }
  .dc-core-summary { font-size: 13px; }
  .dc-overview-text { font-size: 15px; }
  .dc-change-label { font-size: 12px; padding: 2px 8px; }
  .dc-change-text { font-size: 15px; }
  .dc-mk-rank { font-size: 15px; min-width: 22px; }
  .dc-mk-title { font-size: 15px; }
  .dc-mk-change { font-size: 14px; }
  .dc-mk-impact { font-size: 14px; }
  .dc-mk-watch { font-size: 13px; }
  .dc-mk-src { font-size: 12px; }
  .dc-watch-src { font-size: 13px; }
  .dc-conf { font-size: 11px; }
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

  /* 时间筛选：分段控件 */
  .rpt-filter { gap: var(--space-2); }
  .rf-seg {
    border-radius: var(--radius-p-2xl);
    padding: 3px;
  }
  .rf-seg-item {
    padding: 4px 14px;
    border-radius: var(--radius-p-xl);
  }
  .rf-seg-text { font-size: 13px; }
  .rf-cal {
    padding: 6px 12px;
    border-radius: var(--radius-p-2xl);
    gap: 6px;
  }
  .rf-cal-text { font-size: 13px; }
  .rf-cal-arrow { font-size: 10px; }
  .rf-reset-text { font-size: 13px; }

  /* 日期分组标题 */
  .tl-group { margin-bottom: 4px; }
  .tl-date { gap: var(--space-2); padding: 18px 0 8px 0; }
  .tl-date-bar { width: 3px; height: 15px; border-radius: var(--radius-p-sm); }
  .tl-date-main { font-size: 15px; font-weight: 600; }
  .tl-date-week { font-size: 13px; padding: 2px 8px; border-radius: var(--radius-p-2xl); }
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
    padding: var(--space-5);
    border-radius: var(--radius-p-2xl);
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
    border-radius: var(--radius-p-2xl);
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
    gap: var(--space-1);
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
  .dc-section-title { font-size: 13px; font-weight: 600; color: var(--color-text-placeholder); }
  .dc-core-text { font-size: 15px; line-height: 1.75; }
  .dc-core-summary { font-size: 13px; }
  .dc-overview-text { font-size: 15px; line-height: 1.75; }
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

  /* 时间筛选 —— 80%紧凑档分段控件 */
  .rpt-filter { gap: 10px; }
  .rf-seg { border-radius: var(--radius-p-2xl); padding: 3px; }
  .rf-seg-item { padding: 4px 13px; border-radius: var(--radius-p-xl); }
  .rf-seg-text { font-size: 13px; }
  .rf-cal { padding: 6px 13px; border-radius: var(--radius-p-2xl); gap: 6px; }
  .rf-cal-text { font-size: 13px; }
  .rf-cal-arrow { font-size: 10px; }
  .rf-reset-text { font-size: 12px; }

  /* 日期分组标题 —— 轻量分组标记，不抢卡片标题层级 */
  .tl-date { gap: 5px; padding: 12px 0 5px 0; }
  .tl-date-bar { width: 3px; height: 12px; border-radius: var(--radius-p-sm); }
  .tl-date-main { font-size: 12px; font-weight: 600; }
  .tl-date-week { font-size: 11px; padding: 2px 7px; border-radius: var(--radius-p-xl); }
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


/* ── 右栏（简报阅读导航）：仅 PC 显示 ── */
.pc-rail { display: none; }
@media screen and (min-width: 768px) {
  .pc-rail {
    display: flex;
    flex-direction: column;
    gap: 14px;
    width: 200px;
    min-width: 200px;
    flex-shrink: 0;
    position: sticky;
    top: 0;
    align-self: flex-start;
    max-height: 100vh;
    overflow-y: auto;
    padding: 28px 22px 40px 0;
  }
  .rail-block {
    background: var(--color-bg-card);
    border: 1px solid var(--color-border);
    border-radius: 12px;
    padding: 15px 16px;
  }
  .rail-title {
    display: block;
    font-size: 11px;
    color: var(--color-text-muted);
    letter-spacing: 1px;
    margin-bottom: 12px;
  }
  .toc-item {
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding: 7px 0;
    cursor: pointer;
  }
  .toc-num {
    font-size: 11px;
    color: var(--color-text-muted);
    font-variant-numeric: tabular-nums;
    flex: none;
    min-width: 20px;
  }
  .toc-label { font-size: 13px; color: var(--color-text-secondary); }
  .toc-item:hover .toc-label { color: var(--color-brand); }
  .rail-dim {
    display: block;
    font-size: 11px;
    color: var(--color-text-muted);
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid var(--color-border);
  }
  .rail-note {
    display: block;
    font-size: 11px;
    color: var(--color-text-muted);
    line-height: 1.75;
  }
  .rail-link {
    display: block;
    font-size: 12px;
    color: var(--color-brand);
    font-weight: 600;
    margin-top: 10px;
    cursor: pointer;
  }
}

</style>
