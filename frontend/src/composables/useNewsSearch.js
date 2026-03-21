/**
 * 新闻搜索 composable
 * 管理：搜索模式、搜索历史、热门话题、搜索结果分页
 */
import { ref } from 'vue'
import { searchNews, fetchHotTopics } from '../utils/api.js'

const PAGE_SIZE = 20
const SEARCH_HISTORY_KEY = 'alphareader_search_history'
const MAX_HISTORY = 10

export function useNewsSearch() {
  const searchMode = ref(false)
  const searchFocused = ref(false)
  const searchQuery = ref('')
  const searchSubmitted = ref(false)
  const searchList = ref([])
  const searchTotal = ref(0)
  const searchOffset = ref(0)
  const searchLoading = ref(false)
  const searchLoadingMore = ref(false)
  const searchNoMore = ref(false)
  const searchHistory = ref([])
  const hotTopics = ref([])

  /** 加载搜索历史 */
  function loadSearchHistory() {
    try {
      const raw = uni.getStorageSync(SEARCH_HISTORY_KEY)
      searchHistory.value = raw ? JSON.parse(raw) : []
    } catch { searchHistory.value = [] }
  }

  /** 添加搜索历史 */
  function addToHistory(keyword) {
    let history = searchHistory.value.filter(h => h !== keyword)
    history.unshift(keyword)
    if (history.length > MAX_HISTORY) history = history.slice(0, MAX_HISTORY)
    searchHistory.value = history
    try { uni.setStorageSync(SEARCH_HISTORY_KEY, JSON.stringify(history)) } catch {}
  }

  /** 清除搜索历史 */
  function clearHistory() {
    searchHistory.value = []
    try { uni.removeStorageSync(SEARCH_HISTORY_KEY) } catch {}
  }

  /** 加载热门话题 */
  async function loadHotTopics() {
    if (hotTopics.value.length) return
    try {
      const data = await fetchHotTopics()
      hotTopics.value = data.topics || []
    } catch { /* ignore */ }
  }

  /** 搜索框获得焦点 */
  function onSearchFocus() {
    searchFocused.value = true
    searchMode.value = true
    loadSearchHistory()
    loadHotTopics()
  }

  /** 搜索输入 */
  function onSearchInput(e) {
    searchQuery.value = e.detail.value
    searchSubmitted.value = false
  }

  /** 回车确认搜索 */
  function onSearchConfirm() {
    const q = searchQuery.value.trim()
    if (!q) return
    addToHistory(q)
    doSearch()
  }

  /** 点击热门话题/历史快速搜索 */
  function onQuickSearch(keyword) {
    searchQuery.value = keyword
    addToHistory(keyword)
    doSearch()
  }

  /** 点击新闻标签触发搜索 */
  function onTagSearch(tag) {
    searchMode.value = true
    searchFocused.value = true
    searchQuery.value = tag
    addToHistory(tag)
    loadSearchHistory()
    loadHotTopics()
    doSearch()
  }

  /** 清除搜索输入 */
  function onClearSearch() {
    searchQuery.value = ''
    searchSubmitted.value = false
    searchList.value = []
    searchTotal.value = 0
  }

  /** 退出搜索模式 */
  function onExitSearch() {
    searchMode.value = false
    searchFocused.value = false
    searchQuery.value = ''
    searchSubmitted.value = false
    searchList.value = []
    searchTotal.value = 0
    searchOffset.value = 0
  }

  /** 执行搜索 */
  async function doSearch() {
    const q = searchQuery.value.trim()
    if (!q) return
    searchSubmitted.value = true
    searchLoading.value = true
    searchList.value = []
    searchOffset.value = 0
    searchNoMore.value = false
    try {
      const data = await searchNews({ q, limit: PAGE_SIZE, offset: 0 })
      searchList.value = data.items || []
      searchTotal.value = data.total || 0
      searchOffset.value = searchList.value.length
      searchNoMore.value = searchOffset.value >= searchTotal.value
    } catch (e) {
      console.error('搜索失败:', e)
      uni.showToast({ title: '搜索失败', icon: 'none' })
    } finally {
      searchLoading.value = false
    }
  }

  /** 搜索加载更多 */
  async function searchLoadMore() {
    if (searchLoadingMore.value || searchNoMore.value || searchLoading.value) return
    searchLoadingMore.value = true
    try {
      const data = await searchNews({
        q: searchQuery.value.trim(),
        limit: PAGE_SIZE,
        offset: searchOffset.value,
      })
      const items = data.items || []
      searchList.value = searchList.value.concat(items)
      searchTotal.value = data.total || 0
      searchOffset.value += items.length
      searchNoMore.value = items.length < PAGE_SIZE || searchOffset.value >= searchTotal.value
    } catch (e) {
      console.error('搜索加载更多失败:', e)
    } finally {
      searchLoadingMore.value = false
    }
  }

  return {
    searchMode,
    searchFocused,
    searchQuery,
    searchSubmitted,
    searchList,
    searchTotal,
    searchLoading,
    searchLoadingMore,
    searchNoMore,
    searchHistory,
    hotTopics,
    onSearchFocus,
    onSearchInput,
    onSearchConfirm,
    onQuickSearch,
    onTagSearch,
    onClearSearch,
    onExitSearch,
    doSearch,
    searchLoadMore,
    clearHistory,
  }
}
