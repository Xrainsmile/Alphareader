<template>
  <!-- 点击外部关闭下拉的遮罩 -->
  <view v-if="indDropdown || conDropdown" class="icf-overlay" @click="indDropdown = false; conDropdown = false"></view>

  <view class="vcp-filters">
    <!-- 行业搜索栏 -->
    <view class="vcp-search-section">
      <view class="vcp-search-bar" :class="{ 'vcp-search-bar-focus': indDropdown }" @click.stop="indDropdown = !indDropdown; conDropdown = false">
        <view class="vcp-search-input-wrap">
          <text class="vcp-search-icon">🔍</text>
          <input
            class="vcp-search-input"
            type="text"
            v-model="indSearch"
            placeholder="搜索行业..."
            @focus="indDropdown = true; conDropdown = false"
            @click.stop
          />
          <text v-if="selIndustries.length > 0" class="vcp-search-badge">{{ selIndustries.length }}</text>
          <view v-if="indSearch" class="vcp-search-clear" @click.stop="indSearch = ''">
            <text class="vcp-search-clear-icon">×</text>
          </view>
        </view>
      </view>
      <!-- 行业下拉列表 -->
      <view v-if="indDropdown" class="vcp-dropdown" @click.stop>
        <scroll-view scroll-y class="vcp-dropdown-scroll">
          <view
            v-for="ind in filteredIndustries"
            :key="ind"
            class="vcp-dropdown-item"
            :class="{ 'vcp-dropdown-item-active': selIndustries.includes(ind) }"
            @click.stop="toggleIndustry(ind)"
          >
            <text class="vcp-dropdown-check">{{ selIndustries.includes(ind) ? '✓' : '' }}</text>
            <text class="vcp-dropdown-text">{{ ind }}</text>
          </view>
          <view v-if="filteredIndustries.length === 0" class="vcp-dropdown-empty">
            <text>无匹配行业</text>
          </view>
        </scroll-view>
      </view>
      <!-- 行业已选标签 -->
      <view v-if="selIndustries.length > 0" class="vcp-tags">
        <text
          v-for="ind in selIndustries"
          :key="ind"
          class="vcp-tag"
          @click.stop="toggleIndustry(ind)"
        >{{ ind }} ✕</text>
      </view>
    </view>

    <!-- 概念搜索栏 -->
    <view class="vcp-search-section">
      <view class="vcp-search-bar" :class="{ 'vcp-search-bar-focus': conDropdown }" @click.stop="conDropdown = !conDropdown; indDropdown = false">
        <view class="vcp-search-input-wrap">
          <text class="vcp-search-icon">🔍</text>
          <input
            class="vcp-search-input"
            type="text"
            v-model="conSearch"
            placeholder="搜索概念板块..."
            @focus="conDropdown = true; indDropdown = false"
            @click.stop
          />
          <text v-if="selConcepts.length > 0" class="vcp-search-badge">{{ selConcepts.length }}</text>
          <view v-if="conSearch" class="vcp-search-clear" @click.stop="conSearch = ''">
            <text class="vcp-search-clear-icon">×</text>
          </view>
        </view>
      </view>
      <!-- 概念下拉列表 -->
      <view v-if="conDropdown" class="vcp-dropdown" @click.stop>
        <scroll-view scroll-y class="vcp-dropdown-scroll">
          <view
            v-for="con in filteredConcepts"
            :key="con"
            class="vcp-dropdown-item"
            :class="{ 'vcp-dropdown-item-active': selConcepts.includes(con) }"
            @click.stop="toggleConcept(con)"
          >
            <text class="vcp-dropdown-check">{{ selConcepts.includes(con) ? '✓' : '' }}</text>
            <text class="vcp-dropdown-text">{{ con }}</text>
          </view>
          <view v-if="filteredConcepts.length === 0" class="vcp-dropdown-empty">
            <text>无匹配概念</text>
          </view>
        </scroll-view>
      </view>
      <!-- 概念已选标签 -->
      <view v-if="selConcepts.length > 0" class="vcp-tags">
        <text
          v-for="con in selConcepts"
          :key="con"
          class="vcp-tag"
          @click.stop="toggleConcept(con)"
        >{{ con }} ✕</text>
      </view>
    </view>

    <!-- 清除全部按钮 -->
    <view v-if="selIndustries.length + selConcepts.length > 0" class="vcp-clear-all" @click="clearAll">
      <text class="vcp-clear-all-text">清除全部筛选 ({{ selIndustries.length + selConcepts.length }})</text>
    </view>
  </view>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  industryOptions: { type: Array, default: () => [] },
  conceptOptions: { type: Array, default: () => [] },
})

const emit = defineEmits(['change'])

// 内部状态
const selIndustries = ref([])
const selConcepts = ref([])
const indSearch = ref('')
const conSearch = ref('')
const indDropdown = ref(false)
const conDropdown = ref(false)

// 筛选后的选项
const filteredIndustries = computed(() => {
  const kw = indSearch.value.trim().toLowerCase()
  if (!kw) return props.industryOptions
  return props.industryOptions.filter(i => i.toLowerCase().includes(kw))
})

const filteredConcepts = computed(() => {
  const kw = conSearch.value.trim().toLowerCase()
  if (!kw) return props.conceptOptions
  return props.conceptOptions.filter(c => c.toLowerCase().includes(kw))
})

const toggleIndustry = (ind) => {
  const idx = selIndustries.value.indexOf(ind)
  if (idx >= 0) selIndustries.value.splice(idx, 1)
  else selIndustries.value.push(ind)
}

const toggleConcept = (con) => {
  const idx = selConcepts.value.indexOf(con)
  if (idx >= 0) selConcepts.value.splice(idx, 1)
  else selConcepts.value.push(con)
}

const clearAll = () => {
  selIndustries.value = []
  selConcepts.value = []
  indSearch.value = ''
  conSearch.value = ''
}

// 当选中项变化时通知父组件
watch([selIndustries, selConcepts], () => {
  emit('change', {
    industries: [...selIndustries.value],
    concepts: [...selConcepts.value],
  })
}, { deep: true })

// 暴露清除方法给父组件
defineExpose({ clearAll })
</script>
