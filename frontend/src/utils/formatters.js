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

/** Hacker Gravity 星级（3 级，替代精确数值）*/
export function gravityStars(score) {
  if (score == null) return ''
  if (score >= 1.0) return '★★★'
  if (score >= 0.3) return '★★'
  return '★'
}

/** Hacker Gravity 等级 class */
export function gravityClass(score) {
  if (score >= 1.0) return 'gravity-high'
  if (score >= 0.3) return 'gravity-medium'
  return 'gravity-normal'
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

/** 详情页 mp-html tag-style
 *  注意：mp-html 的 tag-style 是内联样式，uni-app 构建时不会转换其中的 rpx，
 *  因此必须使用浏览器可识别的单位（px / rem）。
 */
export const detailTagStyle = {
  p: 'font-size: 15px; color: #4a4a5a; line-height: 1.8; margin-bottom: 8px;',
  h1: 'font-size: 20px; font-weight: 800; color: #1a1a2e; margin: 14px 0 8px;',
  h2: 'font-size: 18px; font-weight: 700; color: #1a1a2e; margin: 12px 0 6px;',
  h3: 'font-size: 16px; font-weight: 600; color: #1a1a2e; margin: 10px 0 5px;',
  h4: 'font-size: 15px; font-weight: 600; color: #3a3a4a; margin: 8px 0 4px;',
  ul: 'padding-left: 18px; margin-bottom: 8px;',
  ol: 'padding-left: 18px; margin-bottom: 8px;',
  li: 'font-size: 15px; color: #4a4a5a; line-height: 1.8; margin-bottom: 4px;',
  blockquote: 'border-left: 3px solid #e0e0e6; padding-left: 12px; color: #6b6b7b; margin: 8px 0;',
  code: 'font-size: 13px; background: #f5f5f7; padding: 1px 5px; border-radius: 3px; color: #d63384;',
  pre: 'background: #f5f5f7; padding: 10px; border-radius: 6px; overflow-x: auto; margin: 8px 0;',
  img: 'max-width: 100%; border-radius: 6px;',
  table: 'width: 100%; border-collapse: collapse; margin: 8px 0;',
  th: 'font-size: 13px; padding: 6px 8px; background: #f5f5f7; border: 1px solid #e8e8ed; text-align: left; font-weight: 600;',
  td: 'font-size: 13px; padding: 6px 8px; border: 1px solid #e8e8ed;',
  strong: 'font-weight: 700; color: #1a1a2e;',
  em: 'font-style: italic; color: #5a5a6e;',
  hr: 'border: none; border-top: 1px solid #e8e8ed; margin: 12px 0;',
  a: 'color: #4285f4; text-decoration: none;',
}

/** 列表页 mp-html tag-style（更紧凑）
 *  同样使用 px 而非 rpx，原因见 detailTagStyle 注释。
 */
export const listTagStyle = {
  p: 'font-size: 14px; color: #5a5a6e; line-height: 1.7; margin-bottom: 6px;',
  h1: 'font-size: 18px; font-weight: 700; color: #1a1a2e; margin: 10px 0 5px;',
  h2: 'font-size: 16px; font-weight: 600; color: #1a1a2e; margin: 8px 0 4px;',
  h3: 'font-size: 15px; font-weight: 600; color: #1a1a2e; margin: 7px 0 4px;',
  h4: 'font-size: 14px; font-weight: 600; color: #3a3a4a; margin: 6px 0 3px;',
  ul: 'padding-left: 16px; margin-bottom: 5px;',
  ol: 'padding-left: 16px; margin-bottom: 5px;',
  li: 'font-size: 14px; color: #5a5a6e; line-height: 1.7; margin-bottom: 3px;',
  blockquote: 'border-left: 3px solid #e0e0e6; padding-left: 10px; color: #6b6b7b; margin: 5px 0;',
  code: 'font-size: 12px; background: #f5f5f7; padding: 1px 4px; border-radius: 3px; color: #d63384;',
  pre: 'background: #f5f5f7; padding: 8px; border-radius: 6px; overflow-x: auto; margin: 5px 0;',
  img: 'max-width: 100%; border-radius: 6px;',
  table: 'width: 100%; border-collapse: collapse; margin: 5px 0;',
  th: 'font-size: 12px; padding: 5px 6px; background: #f5f5f7; border: 1px solid #e8e8ed; text-align: left; font-weight: 600;',
  td: 'font-size: 12px; padding: 5px 6px; border: 1px solid #e8e8ed;',
  strong: 'font-weight: 700; color: #1a1a2e;',
  em: 'font-style: italic; color: #5a5a6e;',
  hr: 'border: none; border-top: 1px solid #e8e8ed; margin: 10px 0;',
  a: 'color: #4285f4; text-decoration: none;',
}
