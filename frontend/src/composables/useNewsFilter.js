/**
 * 新闻筛选 composable
 * 管理：排序 / 时效 / 来源 / 评分 筛选 + 面板临时状态
 */
import { ref, computed } from 'vue'

export function useNewsFilter() {
  // ── 常量配置 ──
  const scoreOptions = [5, 6, 7, 8, 9]
  const categoryTabs = [
    { value: '', label: '全部' },
    { value: '财经', label: '财经' },
    { value: '科技', label: '科技' },
  ]
  const cnSources = ['财联社']
  const enSources = ['MarketWatch', 'Seeking Alpha', 'Finnhub']
  const techSources = ['TechCrunch', 'Hacker News', 'OpenAI Blog', 'Google AI Blog', 'Anthropic', 'Hugging Face', 'MIT Tech Review']
  const sortTabs = [
    { value: 'hot', label: 'Gravity' },
    { value: 'latest', label: '最新' },
    { value: 'score', label: '评分' },
  ]
  const ageOptions = [
    { value: 24, label: '24h' },
    { value: 48, label: '48h' },
    { value: 72, label: '3天' },
    { value: 168, label: '7天' },
    { value: 0, label: '不限' },
  ]

  // ── 实际生效的筛选值 ──
  const minScore = ref(6)
  const currentSource = ref('')
  const currentSort = ref('hot')
  const maxAgeHours = ref(24)
  const currentCategory = ref('')
  const onlyHighlight = ref(false)

  // ── 面板暂存值 ──
  const filterOpen = ref(false)
  const tmpSort = ref('hot')
  const tmpAge = ref(24)
  const tmpSource = ref('')
  const tmpScore = ref(6)
  const tmpHighlight = ref(false)

  const hasActiveFilter = computed(() => {
    return currentSort.value !== 'hot' || minScore.value !== 6 || currentSource.value !== '' || maxAgeHours.value !== 24 || onlyHighlight.value
  })

  const filterTags = computed(() => {
    const tags = []
    if (onlyHighlight.value) tags.push('🔥 重点')
    const tab = sortTabs.find(t => t.value === currentSort.value)
    if (tab && currentSort.value !== 'hot') tags.push(tab.label)
    if (currentSort.value === 'hot') tags.push('Gravity')
    const age = ageOptions.find(a => a.value === maxAgeHours.value)
    if (age && maxAgeHours.value !== 24) tags.push(age.label)
    if (currentSource.value) tags.push(currentSource.value)
    if (minScore.value !== 6) tags.push(`≥${minScore.value}`)
    return tags
  })

  /** 构建 API 请求参数 */
  function buildFilterParams() {
    return {
      min_score: minScore.value,
      source: currentSource.value || undefined,
      category: currentCategory.value || undefined,
      sort: currentSort.value,
      max_age_hours: maxAgeHours.value || undefined,
      highlight_only: onlyHighlight.value || undefined,
    }
  }

  /** 打开/关闭筛选浮窗 */
  function openFilter() {
    if (filterOpen.value) {
      filterOpen.value = false
      return
    }
    tmpSort.value = currentSort.value
    tmpAge.value = maxAgeHours.value
    tmpSource.value = currentSource.value
    tmpScore.value = minScore.value
    tmpHighlight.value = onlyHighlight.value
    filterOpen.value = true
  }

  /** 确认筛选 — 暂存值写入实际值，返回 true 表示需要重新加载 */
  function confirmFilter() {
    currentSort.value = tmpSort.value
    maxAgeHours.value = tmpAge.value
    currentSource.value = tmpSource.value
    minScore.value = tmpScore.value
    onlyHighlight.value = tmpHighlight.value
    filterOpen.value = false
    return true
  }

  /** 取消 — 关闭面板不应用 */
  function cancelFilter() {
    filterOpen.value = false
  }

  /** 重置暂存值为默认 */
  function resetTmp() {
    tmpSort.value = 'hot'
    tmpAge.value = 24
    tmpSource.value = ''
    tmpScore.value = 6
    tmpHighlight.value = false
  }

  /** 切换分类 Tab，返回 true 表示需要重新加载 */
  function switchCategory(cat) {
    if (currentCategory.value === cat) return false
    currentCategory.value = cat
    return true
  }

  return {
    // 常量
    scoreOptions,
    categoryTabs,
    cnSources,
    enSources,
    techSources,
    sortTabs,
    ageOptions,
    // 生效值
    minScore,
    currentSource,
    currentSort,
    maxAgeHours,
    currentCategory,
    onlyHighlight,
    // 面板
    filterOpen,
    tmpSort,
    tmpAge,
    tmpSource,
    tmpScore,
    tmpHighlight,
    // 计算
    hasActiveFilter,
    filterTags,
    // 方法
    buildFilterParams,
    openFilter,
    confirmFilter,
    cancelFilter,
    resetTmp,
    switchCategory,
  }
}
