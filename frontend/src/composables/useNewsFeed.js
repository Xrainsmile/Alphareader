/**
 * 实时事件 Feed 数据加载 composable（事件化新闻）
 * 管理：事件列表（仅事件根）、分页、加载状态、关联报道懒加载展开
 *
 * 与旧版的区别：
 * - 数据源 /api/v1/events（仅事件根，一页 20 条 = 20 个事件）
 * - 子报道不再混入列表，展开时按需调 /events/{id}/sources 懒加载
 */
import { ref, computed } from 'vue'
import { fetchEvents, fetchEventSources } from '../utils/api.js'

const PAGE_SIZE = 20

/** 事件 API 条目 → NewsCard 兼容字段 */
function adaptEvent(e) {
  return {
    ...e,
    // NewsCard 兼容映射
    ai_summary: e.summary,
    event_title: e.is_synthesized ? e.title : null,  // 徽标「事件 ·」前缀依据
    child_count: Math.max((e.article_count || 1) - 1, 0),
    related_to_id: null,  // 事件列表全是根
    // 关联报道懒加载占位
    related_items: null,
    _sourcesLoaded: false,
  }
}

export function useNewsFeed() {
  const newsList = ref([])
  const total = ref(0)
  const offset = ref(0)
  const loading = ref(true)
  const loadingMore = ref(false)
  const noMore = ref(false)
  const expandedGroups = ref({})

  /** 事件列表即分组列表（每项一个事件，children 由懒加载填充） */
  const groupedNews = computed(() => newsList.value)

  /** 切换关联报道折叠/展开；首次展开时懒加载全量信源 */
  async function toggleRelated(parentId) {
    const willExpand = !expandedGroups.value[parentId]
    expandedGroups.value = {
      ...expandedGroups.value,
      [parentId]: willExpand,
    }
    if (!willExpand) return

    const item = newsList.value.find(n => n.id === parentId)
    if (!item || item._sourcesLoaded) return
    try {
      const data = await fetchEventSources(parentId, { limit: 50 })
      // 信源接口含根本身，折叠区只展示子报道
      item.related_items = (data.data || data.items || []).filter(a => a.id !== parentId)
    } catch (e) {
      item.related_items = []
    }
    item._sourcesLoaded = true
  }

  /** 重置列表并加载第一页 */
  async function resetAndLoad(filterParams = {}) {
    newsList.value = []
    offset.value = 0
    noMore.value = false
    loading.value = true
    expandedGroups.value = {}
    try {
      const data = await fetchEvents({
        limit: PAGE_SIZE,
        offset: 0,
        ...filterParams,
      })
      newsList.value = (data.data || data.items || []).map(adaptEvent)
      total.value = data.total || 0
      offset.value = newsList.value.length
      noMore.value = offset.value >= total.value
    } catch (e) {
      console.error('加载事件失败:', e)
      uni.showToast({ title: '加载失败', icon: 'none' })
    } finally {
      loading.value = false
    }
  }

  /** 上拉加载更多 */
  async function loadMore(filterParams = {}) {
    if (loadingMore.value || noMore.value || loading.value) return
    loadingMore.value = true
    try {
      const data = await fetchEvents({
        limit: PAGE_SIZE,
        offset: offset.value,
        ...filterParams,
      })
      const items = (data.data || data.items || []).map(adaptEvent)
      newsList.value = newsList.value.concat(items)
      total.value = data.total || 0
      offset.value += items.length
      noMore.value = items.length < PAGE_SIZE || offset.value >= total.value
    } catch (e) {
      console.error('加载更多失败:', e)
      uni.showToast({ title: '加载失败', icon: 'none' })
    } finally {
      loadingMore.value = false
    }
  }

  return {
    newsList,
    total,
    loading,
    loadingMore,
    noMore,
    expandedGroups,
    groupedNews,
    toggleRelated,
    resetAndLoad,
    loadMore,
  }
}
