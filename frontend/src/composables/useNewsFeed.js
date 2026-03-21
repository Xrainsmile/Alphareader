/**
 * 新闻 Feed 数据加载 composable
 * 管理：列表数据、分页、加载状态、聚合分组、关联报道展开
 */
import { ref, computed } from 'vue'
import { fetchNews } from '../utils/api.js'

const PAGE_SIZE = 20

export function useNewsFeed() {
  const newsList = ref([])
  const total = ref(0)
  const offset = ref(0)
  const loading = ref(true)
  const loadingMore = ref(false)
  const noMore = ref(false)
  const expandedGroups = ref({})

  /**
   * 将扁平的 newsList 转换为「父子嵌套」结构
   */
  const groupedNews = computed(() => {
    const list = newsList.value
    if (!list || !list.length) return []

    const parentMap = new Map()
    const orphans = []

    for (const item of list) {
      if (!item.related_to_id) {
        parentMap.set(item.id, { ...item, children: [] })
      }
    }

    for (const item of list) {
      if (item.related_to_id) {
        const parent = parentMap.get(item.related_to_id)
        if (parent) {
          parent.children.push(item)
        } else {
          orphans.push({ ...item, children: [] })
        }
      }
    }

    const result = []
    const addedIds = new Set()
    for (const item of list) {
      if (!item.related_to_id && parentMap.has(item.id) && !addedIds.has(item.id)) {
        result.push(parentMap.get(item.id))
        addedIds.add(item.id)
      }
    }
    for (const o of orphans) {
      if (!addedIds.has(o.id)) {
        result.push(o)
        addedIds.add(o.id)
      }
    }

    return result
  })

  /** 切换关联报道折叠/展开 */
  function toggleRelated(parentId) {
    expandedGroups.value = {
      ...expandedGroups.value,
      [parentId]: !expandedGroups.value[parentId],
    }
  }

  /** 重置列表并加载第一页 */
  async function resetAndLoad(filterParams = {}) {
    newsList.value = []
    offset.value = 0
    noMore.value = false
    loading.value = true
    expandedGroups.value = {}
    try {
      const data = await fetchNews({
        limit: PAGE_SIZE,
        offset: 0,
        ...filterParams,
      })
      newsList.value = data.items || []
      total.value = data.total || 0
      offset.value = newsList.value.length
      noMore.value = offset.value >= total.value
    } catch (e) {
      console.error('加载新闻失败:', e)
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
      const data = await fetchNews({
        limit: PAGE_SIZE,
        offset: offset.value,
        ...filterParams,
      })
      const items = data.items || []
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
