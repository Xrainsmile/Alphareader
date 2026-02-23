/**
 * 用户行为埋点模块 — 攒批上报曝光/点击/停留时长
 *
 * 策略：
 *   - 事件先存入内存队列
 *   - 每 30 秒自动 flush，或页面隐藏/卸载时立即 flush
 *   - 上报失败静默丢弃，不影响用户体验
 */

import { reportAnalyticsEvents } from './api.js'

const FLUSH_INTERVAL = 30000 // 30 秒
let _queue = []
let _timer = null
let _pageEnterTime = 0

/** 记录一个事件 */
function _push(type, dimension = '_total', value = 1) {
  _queue.push({ type, dimension, value })
}

/** 批量上报并清空队列 */
function _flush() {
  if (_queue.length === 0) return
  const batch = _queue.splice(0)
  reportAnalyticsEvents(batch).catch(() => {
    // 上报失败静默忽略
  })
}

/** 初始化：启动定时 flush + 监听页面生命周期 */
export function initTracker() {
  if (_timer) return // 防止重复初始化
  _timer = setInterval(_flush, FLUSH_INTERVAL)

  // 页面进入时记录
  _pageEnterTime = Date.now()
  _push('page_view')

  // #ifdef H5
  // 页面隐藏/关闭时上报停留时长
  const onVisibilityChange = () => {
    if (document.visibilityState === 'hidden') {
      _reportDuration()
      _flush()
    } else if (document.visibilityState === 'visible') {
      // 重新进入时刷新计时
      _pageEnterTime = Date.now()
      _push('page_view')
    }
  }
  document.addEventListener('visibilitychange', onVisibilityChange)

  // beforeunload 兜底
  window.addEventListener('beforeunload', () => {
    _reportDuration()
    _flush()
  })
  // #endif
}

/** 记录停留时长 */
function _reportDuration() {
  if (_pageEnterTime > 0) {
    const sec = Math.round((Date.now() - _pageEnterTime) / 1000)
    if (sec > 0 && sec < 7200) { // 忽略异常值（>2h）
      _push('session_duration', '_total', sec)
    }
    _pageEnterTime = 0
  }
}

/** 上报新闻曝光 */
export function trackImpression(newsId) {
  if (!newsId) return
  _push('news_impression', String(newsId))
  _push('news_impression', '_total')
}

/** 上报新闻点击 */
export function trackClick(newsId) {
  if (!newsId) return
  _push('news_click', String(newsId))
  _push('news_click', '_total')
}

/** 销毁 tracker（页面卸载时调用） */
export function destroyTracker() {
  _reportDuration()
  _flush()
  if (_timer) {
    clearInterval(_timer)
    _timer = null
  }
}
