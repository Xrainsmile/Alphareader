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
      <text class="reports-subtitle">每日研报 · 新闻概览 · 每日复盘</text>
      <!-- 移动端解锁后：Stocks / SEPA 入口（原生 tabBar 已默认隐藏）-->
      <view v-if="isOpen" class="gate-reveal-mobile">
        <view class="gate-reveal-chip" @click="goHidden('stocks')">Stocks</view>
        <view class="gate-reveal-chip" @click="goHidden('sepa')">SEPA</view>
      </view>
    </view>

    <!-- Tab Bar -->
    <view class="tab-bar">
      <view
        class="tab-item"
        :class="{ active: activeTab === 'digest' }"
        @click="switchTab('digest')"
      >
        <text class="tab-text">Reports</text>
      </view>
      <view
        class="tab-item"
        :class="{ active: activeTab === 'briefing' }"
        @click="switchTab('briefing')"
      >
        <text class="tab-text">每日研报</text>
      </view>
      <!-- 深度报告 tab 已暂停（2026-08-02）：模块注释掉
      <view
        class="tab-item"
        :class="{ active: activeTab === 'reports' }"
        @click="switchTab('reports')"
      >
        <text class="tab-text">深度报告</text>
      </view>
      -->
      <view class="tab-indicator" :style="{ left: tabIndicatorLeft, width: '50%' }"></view>
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
            </view>
            <view class="dc-stats">
              <text class="dc-stat">{{ item.event_count || 0 }} 个事件</text>
              <text class="dc-sep">·</text>
              <text class="dc-stat">{{ item.material_update_count || 0 }} 个重要变化</text>
              <text class="dc-sep">·</text>
              <text class="dc-stat">{{ (sc(item).must_know || []).length }} 个必须知道</text>
            </view>

            <!-- 核心变化（跨事件共同信号，一眼看本时段最重要变化）-->
            <view v-if="sc(item).cross_event_signals && sc(item).cross_event_signals.length" class="dc-section dc-core">
              <text class="dc-section-title">核心变化</text>
              <view v-for="(s, si) in sc(item).cross_event_signals" :key="si" class="dc-core-item">
                <text class="dc-core-dot">•</text>
                <text class="dc-core-text">{{ s.title }}</text>
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
                  <text class="dc-mk-title">{{ e.title }}</text>
                  <text v-if="e.latest_change" class="dc-mk-change">{{ e.latest_change }}</text>
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
              <text class="meta-tag tag-sentiment" v-if="item.meta && item.meta.market_sentiment"><IconSvg name="dot" :color="sentimentColor(item.meta.market_sentiment)" class="meta-dot" size="10px" /> {{ item.meta.market_sentiment }}</text>
              <text class="meta-tag tag-s" v-if="item.meta && item.meta.tier_s"><IconSvg name="target" class="meta-ico" size="13px" /> {{ item.meta.tier_s }}</text>
              <text class="meta-tag tag-a" v-if="item.meta && item.meta.tier_a"><IconSvg name="clipboard" class="meta-ico" size="13px" /> {{ item.meta.tier_a }}</text>
              <text class="meta-tag tag-x" v-if="item.meta && item.meta.tier_x"><IconSvg name="warning" class="meta-ico" size="13px" /> {{ item.meta.tier_x }}</text>
            </view>
            <text class="briefing-gen-time" v-if="item.generation_sec"><IconSvg name="clock" class="meta-ico" size="12px" /> {{ item.generation_sec.toFixed(1) }}s</text>
          </view>
        </view>
      </view>

      <!-- Load more -->
      <view v-if="!briefingLoading && briefingList.length > 0 && briefingDays < 30" class="load-more" @click="loadMoreBriefings">
        <text class="load-more-text">加载更多</text>
      </view>
    </view>

    <!-- ═══════════════════════════════════════════
         Tab 3: 复盘（原有 Reports 列表）— 深度报告模块已暂停（2026-08-02）
         ═══════════════════════════════════════════ -->
    <view v-if="false /* 深度报告模块已暂停 2026-08-02 */" class="reports-tab">
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
    </view><!-- /container -->
  </view><!-- /page-layout -->
</template>

<script setup>
import { ref, reactive, computed, onMounted, nextTick } from 'vue'
import mpHtml from 'mp-html/dist/uni-app/components/mp-html/mp-html.vue'
import { fetchDigests, fetchBriefings } from '@/utils/api'
import { parseFrontMatter, renderMarkdown } from '@/utils/markdown'
// 深度报告模块已暂停（2026-08-02）：import { rawReports } from '@/data/reports'
import SiteFooter from '@/components/common/SiteFooter.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import PcSidebar from '@/components/common/PcSidebar.vue'
import IconSvg from '@/components/common/IconSvg.vue'
import GateButton from '@/components/common/GateButton.vue'
import { useGate } from '@/utils/useGate'
import { listTagStyle, listTagStyleMobile, formatDate, reportStatusLabel } from '@/utils/formatters'

// ── Tab State ──
// 默认「Reports」：用户打开产品首先看到最新阶段简报（PRD 4.2）
const activeTab = ref('digest')

// ── 侧门（gate）：Stocks / SEPA 对外隐藏，解锁后显现 ──
const { isOpen } = useGate()

// 移动端解锁后跳转到被隐藏的 Stocks / SEPA（已从原生 tabBar 移除，改用 navigateTo）
function goHidden(kind) {
  const url = kind === 'stocks' ? '/pages/stocks/index' : '/pages/sepa/index'
  uni.navigateTo({ url })
}

// ── 右看板：栏目导航 ──
const rightTabs = [
  { key: 'digest', iconName: 'news', label: 'Reports', desc: '过去几小时发生了什么' },
  { key: 'briefing', iconName: 'briefing', label: '每日研报', desc: 'AI 市场分析' },
  // 深度报告 已暂停（2026-08-02）：{ key: 'reports', iconName: 'clipboard', label: '深度报告', desc: '历史复盘与专题' },
]

// ── Tab indicator position (2 tabs: digest / briefing；深度报告已暂停) ──
const tabIndicatorLeft = computed(() => {
  if (activeTab.value === 'digest') return '0%'
  if (activeTab.value === 'briefing') return '50%'
  return '100%' // 防御：reports 已禁用
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
  // 深度报告 已暂停（2026-08-02）
  // if (tab === 'reports' && reportsList.value.length === 0 && !reportsLoading.value) {
  //   loadReports()
  // }
}

// ── Digest State ──
const digestList = ref([])
const digestLoading = ref(false)
const digestDays = ref(7)
const expandedIds = reactive(new Set())
// 深链：从企微推送 / ?id=<digest_id> 进入时，定位到对应简报
const targetDigestId = ref(null)

// ── Reports State（深度报告模块已暂停 2026-08-02）──
// const reportsList = ref([])
// const reportsLoading = ref(false)

// ── Briefing State ──
const briefingList = ref([])
const briefingLoading = ref(true)
const briefingDays = ref(7)

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
// 持续关注 = 持续事件(ongoing_updates) + 此前关注暂无进展(quiet_topics)
function ongoingList(item) {
  const s = sc(item)
  return [...(s.ongoing_updates || []), ...(s.quiet_topics || [])]
}
// 时段范围：08:30—12:15
function formatPeriodRange(item) {
  const fmt = (iso) => {
    const d = new Date(iso)
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  return `${fmt(item.period_start)}—${fmt(item.period_end)}`
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

const CONFIDENCE_LABELS = { high: '高可信', medium: '中可信', low: '低可信' }
function confidenceLabel(c) {
  return CONFIDENCE_LABELS[c] || c
}

// ── Icon helpers（替代 emoji）──
function periodIconName(label) {
  return { morning: 'sunrise', midday: 'sun', evening: 'sunset', night: 'moon' }[label] || 'sun'
}
function sentimentColor(s) {
  if (!s) return '#9ca3af'
  const t = String(s)
  if (t.includes('乐观') || t.includes('看多') || t.includes('偏多')) return '#16a34a'
  if (t.includes('悲观') || t.includes('看空') || t.includes('偏空')) return '#dc2626'
  if (t.includes('中性') || t.includes('震荡')) return '#d97706'
  return '#9ca3af'
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

// formatDate imported from formatters.js

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

// statusLabel → reportStatusLabel, sentimentEmoji imported from formatters.js
const statusLabel = reportStatusLabel

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

// 深度报告模块已暂停（2026-08-02），以下函数注释掉
// 从 Mock 数据生成 fallback 列表
// function getLocalReports() {
//   return rawReports.map((raw, idx) => {
//     const { meta } = parseFrontMatter(raw)
//     return {
//       id: idx,
//       sync_id: `local-${idx}`,
//       title: meta.title || '无标题',
//       date: meta.date || '',
//       cover: meta.cover || '',
//       summary: meta.summary || '',
//       _isLocal: true
//     }
//   })
// }
//
// async function loadReports() {
//   reportsLoading.value = true
//   try {
//     const data = await fetchReportsList()
//     if (data && data.length > 0) {
//       reportsList.value = data
//     } else {
//       reportsList.value = getLocalReports()
//     }
//   } catch (e) {
//     console.warn('API 不可用，使用本地数据:', e.message)
//     reportsList.value = getLocalReports()
//   } finally {
//     reportsLoading.value = false
//   }
// }

// 深度报告模块已暂停（2026-08-02），goDetail 不再使用
// const goDetail = (id) => {
//   const item = reportsList.value.find(r => r.id === id)
//   if (item && item._isLocal) {
//     uni.navigateTo({ url: `/pages/reports/detail?idx=${id}` })
//   } else {
//     uni.navigateTo({ url: `/pages/reports/detail?id=${id}` })
//   }
// }

const onShare = (item) => {
  // #ifdef H5
  if (navigator.share) {
    navigator.share({
      title: item.title,
      text: item.summary,
      url: window.location.origin + `/pages/reports/index?id=${item.id}`
    }).catch(() => {})
  } else {
    uni.setClipboardData({
      data: window.location.origin + `/pages/reports/index?id=${item.id}`,
      success: () => {
        uni.showToast({ title: '链接已复制', icon: 'none' })
      }
    })
  }
  // #endif
}

onMounted(() => {
  // 读取深链参数 ?id=<digest_id>（从企微推送链接进入时定位具体简报）
  const pages = getCurrentPages()
  const cur = pages[pages.length - 1]
  const opts = (cur && (cur.$page?.options || cur.options)) || {}
  if (opts.id) targetDigestId.value = opts.id

  // 默认展示 Reports（今日简报）时间轴，进入即加载
  if (activeTab.value === 'digest') {
    loadDigests()
  }
  loadBriefings()
})
</script>

<style scoped>
.reports-container {
  min-height: 100vh;
}

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

/* ── Tab Bar ── */
.tab-bar {
  display: flex;
  position: relative;
  border-bottom: 1rpx solid var(--color-border-light);
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
  color: var(--color-text-muted);
  font-weight: 500;
  transition: color 0.2s;
}
.tab-item.active .tab-text {
  color: var(--color-text-primary);
  font-weight: 700;
}
.tab-indicator {
  position: absolute;
  bottom: 0;
  width: 33.33%;
  height: 4rpx;
  background: var(--color-brand);
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
  background: var(--color-bg-hover);
  border-radius: 16rpx;
  padding: 28rpx;
  border: 1rpx solid var(--color-border-light);
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
  color: var(--color-text-primary);
  font-family: var(--font-display);
}

.briefing-date-weekday {
  font-size: 24rpx;
  color: var(--color-text-muted);
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
  background: var(--color-bg-success-soft);
}
.status-failed {
  background: var(--color-bg-danger-light);
}
.status-empty {
  background: var(--color-bg-neutral-soft);
}
.status-dot {
  font-size: 14rpx;
}
.status-ok .status-dot {
  color: var(--color-down);
}
.status-failed .status-dot {
  color: var(--color-up);
}
.status-empty .status-dot {
  color: var(--color-text-placeholder);
}
.status-text {
  font-size: 22rpx;
  font-weight: 500;
}
.status-ok .status-text {
  color: var(--color-success-text);
}
.status-failed .status-text {
  color: var(--color-danger-dark);
}
.status-empty .status-text {
  color: var(--color-text-muted);
}

.briefing-preview {
  font-size: 25rpx;
  color: var(--color-text-tertiary);
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
  border-top: 1rpx solid var(--color-border-light);
}

.meta-tags {
  display: flex;
  gap: 12rpx;
  flex-wrap: wrap;
}

.meta-tag {
  font-size: 22rpx;
  color: var(--color-brand);
  background: var(--color-bg-info-soft);
  padding: 4rpx 14rpx;
  border-radius: 8rpx;
  font-weight: 500;
}
.tag-sentiment {
  color: var(--color-text-tertiary);
  background: var(--color-border-light);
}
.tag-s {
  color: var(--color-warning);
  background: var(--color-bg-warning-light);
}
.tag-a {
  color: var(--color-brand);
  background: var(--color-bg-info-soft);
}
.tag-x {
  color: var(--color-danger-dark);
  background: var(--color-bg-danger-light);
}

.briefing-gen-time {
  font-size: 22rpx;
  color: var(--color-text-placeholder);
  font-family: var(--font-sans);
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
  border-bottom: 1rpx solid var(--color-border-light);
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
  font-size: 30rpx;
  font-weight: 700;
  color: var(--color-text-primary);
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-family: var(--font-sans);
}
.card-summary {
  font-size: 25rpx;
  color: var(--color-text-hint);
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
  color: var(--color-text-placeholder);
  font-family: var(--font-sans);
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
  color: var(--color-text-placeholder);
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
.dc-core-dot { color: var(--color-brand, #4285f4); font-weight: 700; line-height: 1.6; }
.dc-core-text {
  font-size: 26rpx;
  color: var(--color-text-primary);
  line-height: 1.55;
  font-weight: 600;
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
.dc-mk-title {
  font-size: 27rpx;
  font-weight: 600;
  color: var(--color-text-primary);
  line-height: 1.45;
  display: block;
}
.dc-mk-change {
  font-size: 24rpx;
  color: var(--color-text-secondary);
  line-height: 1.55;
  margin-top: 6rpx;
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
  .page-layout {
    display: flex;
    align-items: flex-start;
    gap: 0;
  }
  .container {
    flex: 1;
    min-width: 0;
  }
  .dc-title { font-size: 22px; }
  .dc-range { font-size: 14px; }
  .dc-stats { font-size: 13px; }
  .dc-section-title { font-size: 14px; }
  .dc-core-text { font-size: 15px; }
  .dc-mk-rank { font-size: 15px; min-width: 22px; }
  .dc-mk-title { font-size: 15px; }
  .dc-mk-change { font-size: 14px; }
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
    font-size: 13px;
  }
  .briefing-preview {
    font-size: 15px;
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
    font-size: 13px;
    padding: 2px 8px;
    border-radius: 4px;
  }
  .briefing-gen-time {
    font-size: 13px;
  }

  /* Reports */
  .reports-list {
    margin-top: 8px;
  }
  .report-card {
    padding: 20px 0;
    border-bottom: 1px solid var(--color-border-light);
    gap: 20px;
    transition: background-color 0.15s;
  }
  .report-card:hover {
    background-color: var(--color-bg-hover);
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
    font-size: 15px;
    margin-top: 8px;
    line-height: 1.5;
  }
  .card-bottom {
    margin-top: 12px;
  }
  .card-date {
    font-size: 13px;
  }
  .action-btn {
    width: 28px;
    height: 28px;
  }
  .action-btn:hover {
    background: var(--color-border);
  }
  .action-icon {
    font-size: 14px;
  }
}

@media screen and (min-width: 1200px) {
  /* ── 1:9 布局：导航栏(组件固定130px) : 内容区(撑满) ── */
  .page-layout {
    display: flex;
    gap: 0;
    max-width: 1600px;
    margin: 0 auto;
    align-items: flex-start;
    min-height: calc(100vh - var(--window-top));
  }
  .container {
    flex: 1;
    max-width: none;
    min-width: 0;
  }

  /* ── Tab bar ── */
  .tab-bar { gap: 40px; padding: 18px 28px 0; }
  .tab-text { font-size: 17px; }

  /* ── Digest card 字号放大 ── */
  .digest-card { padding: 32px 36px; margin: 26px 28px; max-width: none; }
  .digest-title { font-size: 24px; }
  .digest-time { font-size: 14px; }
  .digest-meta { font-size: 14px; gap: 20px; }
  .dc-title { font-size: 24px; }
  .dc-range { font-size: 15px; }
  .dc-stats { font-size: 14px; }
  .dc-section-title { font-size: 17px; }
  .dc-core-text { font-size: 16px; line-height: 1.65; }
  .dc-mk-rank { font-size: 16px; min-width: 24px; }
  .dc-mk-title { font-size: 16px; line-height: 1.55; }
  .dc-mk-change { font-size: 15px; line-height: 1.6; }
  .dc-mk-detail { font-size: 14px; }
  .dc-watch-text { font-size: 15px; }
  .dc-upcoming-text { font-size: 15px; }
  .badge-text { font-size: 14px; }
  .footer-stat { font-size: 14px; }

  /* ── Briefing card 字号放大 ── */
  .briefing-date-day { font-size: 19px; }
  .briefing-preview { font-size: 16px; }
  .card-title { font-size: 19px; }
  .card-summary { font-size: 16px; }

  /* ── Empty state ── */
  .empty-text { font-size: 17px; }
  .empty-hint { font-size: 14px; }
}
/* ── IconSvg 适配（替代 emoji）── */
.badge-icon { flex: none; }
.right-news-rank { flex: none; color: var(--color-brand); }
.sb-ico,
.sb-ico-sm,
.meta-ico { flex: none; margin-right: 3px; }
.meta-dot { flex: none; margin-right: 3px; }
.meta-tag { display: inline-flex; align-items: center; }
.briefing-gen-time { display: inline-flex; align-items: center; gap: 3px; }
.sb-changed-text,
.sb-event-change,
.sb-event-watch { display: inline-flex; align-items: center; }

</style>
