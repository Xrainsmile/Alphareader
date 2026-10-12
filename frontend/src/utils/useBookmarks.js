/**
 * 收藏（Bookmarks）
 *
 * 收藏跟随「事件」而非单篇报道：同一事件的不同信源共用一份收藏状态。
 * 存储键统一为 bookmark_event_ids，资讯列表 / 简报 / 详情页三处共用。
 *
 * 说明：当前为本地存储（uni.setStorageSync）。若后续接入后端，
 * 只需替换 readStore / writeStore 两个函数即可，上层 API 不变。
 */
import { ref, computed } from 'vue'

const STORAGE_KEY = 'bookmark_event_ids'
const SETTINGS_KEY = 'reader_settings'
const SNAPSHOT_KEY = 'bookmark_snapshots'

/** 收藏的事件 id 集合（响应式，全局单例） */
const bookmarkIds = ref(new Set())

/** 事件正文快照：收藏页离线还原卡片用 */
const snapshots = ref({})

/** 阅读设置：语言 / 时区 / 密度 */
const settings = ref({
  lang: 'zh',
  timezone: 'Asia/Shanghai',
  density: 'standard',
})

function readStore(key, fallback) {
  try {
    const raw = uni.getStorageSync(key)
    if (!raw) return fallback
    return typeof raw === 'string' ? JSON.parse(raw) : raw
  } catch (_) {
    return fallback
  }
}

function writeStore(key, value) {
  try {
    uni.setStorageSync(key, JSON.stringify(value))
  } catch (_) {
    // 存储不可用时静默失败，不影响阅读
  }
}

/**
 * 事件 id 归一化：优先用 event_id（跨信源稳定），
 * 否则退回 id。保证同一事件不同报道落到同一份收藏。
 */
function eventKey(item) {
  if (!item) return ''
  return item.event_id || item.event_key || item.id || ''
}

function loadSnapshots() {
  snapshots.value = readStore(SNAPSHOT_KEY, {}) || {}
}

function saveSnapshot(item) {
  const k = eventKey(item)
  if (!k) return
  const snap = {
    id: k,
    event_title: item.event_title || item.title,
    title: item.title,
    ai_summary: item.ai_summary || item.event_summary,
    ai_score: item.ai_score,
    source: item.source,
    published_at: item.published_at || item.created_at,
    tags: item.tags || [],
    url: item.url,
    saved_at: Date.now(),
  }
  snapshots.value = { ...snapshots.value, [k]: snap }
  writeStore(SNAPSHOT_KEY, snapshots.value)
}

function removeSnapshot(k) {
  const next = { ...snapshots.value }
  delete next[k]
  snapshots.value = next
  writeStore(SNAPSHOT_KEY, next)
}

function persistBookmarks() {
  writeStore(STORAGE_KEY, [...bookmarkIds.value])
}

function persistSettings() {
  writeStore(SETTINGS_KEY, settings.value)
}

/** 初始化：在应用启动时调用一次 */
function initBookmarks() {
  loadSnapshots()
  const ids = readStore(STORAGE_KEY, [])
  bookmarkIds.value = new Set(Array.isArray(ids) ? ids : [])
  const s = readStore(SETTINGS_KEY, null)
  if (s && typeof s === 'object') {
    settings.value = { ...settings.value, ...s }
  }
}

/** 是否已收藏 */
function isBookmarked(item) {
  const k = eventKey(item)
  return k ? bookmarkIds.value.has(k) : false
}

/** 切换收藏，返回切换后的状态 */
function toggleBookmark(item) {
  const k = eventKey(item)
  if (!k) return false
  const next = new Set(bookmarkIds.value)
  const removing = next.has(k)
  if (removing) {
    next.delete(k)
    removeSnapshot(k)
  } else {
    next.add(k)
    saveSnapshot(item)
  }
  bookmarkIds.value = next
  persistBookmarks()
  return !removing
}

/** 更新阅读设置 */
function updateSettings(patch) {
  settings.value = { ...settings.value, ...patch }
  persistSettings()
}

/** 清空收藏 */
function clearBookmarks() {
  bookmarkIds.value = new Set()
  snapshots.value = {}
  writeStore(SNAPSHOT_KEY, {})
  persistBookmarks()
}

/** 收藏数量 */
const bookmarkCount = computed(() => bookmarkIds.value.size)

/** 收藏 id 列表（按插入顺序） */
const bookmarkList = computed(() => [...bookmarkIds.value])

/** 收藏正文列表，按收藏时间倒序 */
const bookmarkItems = computed(() =>
  [...bookmarkIds.value]
    .map((id) => snapshots.value[id])
    .filter(Boolean)
    .sort((a, b) => (b.saved_at || 0) - (a.saved_at || 0)),
)

export { bookmarkIds, bookmarkCount, bookmarkList, bookmarkItems, snapshots, settings }
export { initBookmarks, loadSnapshots, isBookmarked, toggleBookmark, updateSettings, clearBookmarks, eventKey }

export function useBookmarks() {
  return {
    bookmarkIds,
    bookmarkCount,
    bookmarkList,
    bookmarkItems,
    snapshots,
    settings,
    initBookmarks,
    loadSnapshots,
    isBookmarked,
    toggleBookmark,
    updateSettings,
    clearBookmarks,
    eventKey,
  }
}
