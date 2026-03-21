/**
 * 公共格式化工具函数
 * 多个页面共用的 score / time / gravity / sentiment 格式化
 */

/** AI 评分颜色等级 */
export function scoreClass(score) {
  if (score >= 9) return 'score-high'
  if (score >= 8) return 'score-medium'
  if (score >= 7) return 'score-normal'
  if (score >= 6) return 'score-low'
  return 'score-muted'
}

/** AI 评分格式化（保留 1 位小数） */
export function formatScore(score) {
  if (score == null) return '-'
  return Number(score).toFixed(1)
}

/** 相对时间格式化 */
export function formatTime(iso) {
  if (!iso) return ''
  const now = new Date()
  const d = new Date(iso)
  const diffMs = now - d
  const diffMin = Math.floor(diffMs / 60000)
  if (diffMin < 1) return '刚刚'
  if (diffMin < 60) return `${diffMin}分钟前`
  const diffHour = Math.floor(diffMin / 60)
  if (diffHour < 24) return `${diffHour}小时前`
  const diffDay = Math.floor(diffHour / 24)
  if (diffDay < 7) return `${diffDay}天前`
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${mm}-${dd}`
}

/** Hacker Gravity 值格式化 — 保留 1 位小数 */
export function formatGravity(score) {
  if (score == null) return ''
  return Number(score).toFixed(1)
}

/** Hacker Gravity 等级 class */
export function gravityClass(score) {
  if (score >= 1.0) return 'gravity-high'
  if (score >= 0.3) return 'gravity-medium'
  if (score >= 0.05) return 'gravity-normal'
  return 'gravity-low'
}

/** 情绪 class */
export function sentimentClass(score) {
  if (score >= 3)  return 'sentiment-bull'
  if (score >= 1)  return 'sentiment-mild-bull'
  if (score === 0) return 'sentiment-neutral'
  if (score >= -2) return 'sentiment-mild-bear'
  return 'sentiment-bear'
}

/** 情绪图标 */
export function sentimentIcon(score) {
  if (score >= 3)  return '▲'
  if (score >= 1)  return '△'
  if (score === 0) return '—'
  if (score >= -2) return '▽'
  return '▼'
}

/** 相关度分数格式化 */
export function formatRelevance(score) {
  if (score == null) return ''
  const pct = Math.min(score * 100, 99.9)
  return pct < 1 ? pct.toFixed(2) : pct.toFixed(1)
}

// ── 日期格式化 ──

/** 日期格式化（如 "3月21日"） */
export function formatDate(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const M = d.getMonth() + 1
  const D = d.getDate()
  return `${M}月${D}日`
}

/** 日期+时间格式化（如 "3/21 14:30"） */
export function formatDateTime(isoStr) {
  if (!isoStr) return ''
  const d = new Date(isoStr)
  const M = d.getMonth() + 1
  const D = d.getDate()
  const h = String(d.getHours()).padStart(2, '0')
  const m = String(d.getMinutes()).padStart(2, '0')
  return `${M}/${D} ${h}:${m}`
}

/** 带星期的日期格式化（如 "3月21日 周六"） */
export function formatDateWithWeekday(dateStr) {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  const M = d.getMonth() + 1
  const D = d.getDate()
  const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  return `${M}月${D}日 ${weekdays[d.getDay()]}`
}

// ── 状态标签 ──

/** 研报状态标签 */
export function reportStatusLabel(status) {
  const map = {
    ok: '已完成',
    failed: '生成失败',
    empty: '暂无数据',
  }
  return map[status] || status
}

/** 股票状态标签 */
export function stockStatusLabel(status) {
  const map = {
    holding: '持仓中',
    watching: '观察中',
    exited: '已退出',
  }
  return map[status] || status
}

/** 市场情绪 emoji */
export function sentimentEmoji(sentiment) {
  if (!sentiment) return ''
  const s = sentiment.toLowerCase ? sentiment.toLowerCase() : String(sentiment)
  if (s.includes('乐观') || s.includes('看多') || s.includes('偏多')) return '🟢'
  if (s.includes('悲观') || s.includes('看空') || s.includes('偏空')) return '🔴'
  if (s.includes('中性') || s.includes('震荡')) return '🟡'
  return '⚪'
}

// ── mp-html Tag Style 常量 ──

/** 详情页 mp-html tag-style */
export const detailTagStyle = {
  p: 'font-size: 28rpx; color: #4a4a5a; line-height: 1.8; margin-bottom: 16rpx;',
  h1: 'font-size: 36rpx; font-weight: 800; color: #1a1a2e; margin: 24rpx 0 12rpx;',
  h2: 'font-size: 32rpx; font-weight: 700; color: #1a1a2e; margin: 20rpx 0 10rpx;',
  h3: 'font-size: 30rpx; font-weight: 600; color: #1a1a2e; margin: 16rpx 0 8rpx;',
  h4: 'font-size: 28rpx; font-weight: 600; color: #3a3a4a; margin: 12rpx 0 6rpx;',
  ul: 'padding-left: 32rpx; margin-bottom: 12rpx;',
  ol: 'padding-left: 32rpx; margin-bottom: 12rpx;',
  li: 'font-size: 28rpx; color: #4a4a5a; line-height: 1.8; margin-bottom: 6rpx;',
  blockquote: 'border-left: 6rpx solid #e0e0e6; padding-left: 20rpx; color: #6b6b7b; margin: 12rpx 0;',
  code: 'font-size: 24rpx; background: #f5f5f7; padding: 2rpx 8rpx; border-radius: 4rpx; color: #d63384;',
  pre: 'background: #f5f5f7; padding: 16rpx; border-radius: 8rpx; overflow-x: auto; margin: 12rpx 0;',
  img: 'max-width: 100%; border-radius: 8rpx;',
  table: 'width: 100%; border-collapse: collapse; margin: 12rpx 0;',
  th: 'font-size: 24rpx; padding: 10rpx 12rpx; background: #f5f5f7; border: 1rpx solid #e8e8ed; text-align: left; font-weight: 600;',
  td: 'font-size: 24rpx; padding: 10rpx 12rpx; border: 1rpx solid #e8e8ed;',
  strong: 'font-weight: 700; color: #1a1a2e;',
  em: 'font-style: italic; color: #5a5a6e;',
  hr: 'border: none; border-top: 1rpx solid #e8e8ed; margin: 20rpx 0;',
  a: 'color: #4285f4; text-decoration: none;',
}

/** 列表页 mp-html tag-style（更紧凑） */
export const listTagStyle = {
  p: 'font-size: 26rpx; color: #5a5a6e; line-height: 1.7; margin-bottom: 12rpx;',
  h1: 'font-size: 32rpx; font-weight: 700; color: #1a1a2e; margin: 16rpx 0 8rpx;',
  h2: 'font-size: 30rpx; font-weight: 600; color: #1a1a2e; margin: 14rpx 0 6rpx;',
  h3: 'font-size: 28rpx; font-weight: 600; color: #1a1a2e; margin: 12rpx 0 6rpx;',
  h4: 'font-size: 26rpx; font-weight: 600; color: #3a3a4a; margin: 10rpx 0 4rpx;',
  ul: 'padding-left: 28rpx; margin-bottom: 8rpx;',
  ol: 'padding-left: 28rpx; margin-bottom: 8rpx;',
  li: 'font-size: 26rpx; color: #5a5a6e; line-height: 1.7; margin-bottom: 4rpx;',
  blockquote: 'border-left: 4rpx solid #e0e0e6; padding-left: 16rpx; color: #6b6b7b; margin: 8rpx 0;',
  code: 'font-size: 22rpx; background: #f5f5f7; padding: 2rpx 6rpx; border-radius: 4rpx; color: #d63384;',
  pre: 'background: #f5f5f7; padding: 12rpx; border-radius: 8rpx; overflow-x: auto; margin: 8rpx 0;',
  img: 'max-width: 100%; border-radius: 8rpx;',
  table: 'width: 100%; border-collapse: collapse; margin: 8rpx 0;',
  th: 'font-size: 22rpx; padding: 8rpx 10rpx; background: #f5f5f7; border: 1rpx solid #e8e8ed; text-align: left; font-weight: 600;',
  td: 'font-size: 22rpx; padding: 8rpx 10rpx; border: 1rpx solid #e8e8ed;',
  strong: 'font-weight: 700; color: #1a1a2e;',
  em: 'font-style: italic; color: #5a5a6e;',
  hr: 'border: none; border-top: 1rpx solid #e8e8ed; margin: 16rpx 0;',
  a: 'color: #4285f4; text-decoration: none;',
}
