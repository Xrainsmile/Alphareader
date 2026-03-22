<template>
  <!-- 搜索栏 -->
  <view class="search-bar" :class="{ 'search-bar-focus': searchFocused }">
    <view class="search-input-wrap">
      <text class="search-icon">🔍</text>
      <input
        class="search-input"
        type="text"
        placeholder="搜索财经新闻..."
        :value="searchQuery"
        @input="$emit('input', $event)"
        @focus="$emit('focus')"
        @confirm="$emit('confirm')"
        confirm-type="search"
      />
      <view v-if="searchQuery" class="search-clear" @click="$emit('clear')">
        <text class="search-clear-icon">×</text>
      </view>
    </view>
    <view v-if="searchMode" class="search-cancel" @click="$emit('exit')">
      <text class="search-cancel-text">取消</text>
    </view>
  </view>

  <!-- 搜索面板: 热门话题 + 搜索历史 (搜索模式且无查询时) -->
  <view v-if="searchMode && !searchQuery" class="search-panel">
    <!-- 搜索历史 -->
    <view v-if="searchHistory.length" class="sp-section">
      <view class="sp-section-header">
        <text class="sp-section-title">搜索历史</text>
        <view class="sp-clear-btn" @click="$emit('clear-history')">
          <text class="sp-clear-text">清除</text>
        </view>
      </view>
      <view class="sp-tags">
        <view v-for="h in searchHistory" :key="h" class="sp-tag" @click="$emit('quick-search', h)">
          <text class="sp-tag-text">{{ h }}</text>
        </view>
      </view>
    </view>
    <!-- 热门话题 -->
    <view v-if="hotTopics.length" class="sp-section">
      <view class="sp-section-header">
        <text class="sp-section-title">热门话题</text>
      </view>
      <view class="sp-tags">
        <view v-for="t in hotTopics" :key="t" class="sp-tag sp-tag-hot" @click="$emit('quick-search', t)">
          <text class="sp-tag-text">{{ t }}</text>
        </view>
      </view>
    </view>
  </view>

  <!-- 搜索结果 -->
  <view v-if="searchMode && searchQuery && searchSubmitted" class="search-results">
    <view class="search-results-header">
      <text class="search-results-count">找到 {{ searchTotal }} 条结果</text>
    </view>

    <view v-if="searchLoading && searchList.length === 0" class="loading-container">
      <text class="loading-text">搜索中...</text>
    </view>

    <view v-else-if="searchList.length === 0" class="empty-container">
      <text class="empty-text">未找到相关新闻，换个关键词试试</text>
    </view>

    <view v-else class="card-wrapper">
      <view v-for="(item, idx) in searchList" :key="item.id">
        <NewsCard
          :item="item"
          highlighted
          :class="{ 'news-card-last': idx === searchList.length - 1 }"
          @open="(url, id) => $emit('open', url, id)"
          @tag-search="(tag) => $emit('tag-search', tag)"
          @ticker-click="(code) => $emit('ticker-click', code)"
        />
      </view>
    </view>

    <view v-if="searchList.length > 0" class="load-more">
      <text v-if="searchLoadingMore" class="load-more-text">正在加载更多...</text>
      <text v-else-if="searchNoMore" class="load-more-text">— 没有更多了 —</text>
    </view>
  </view>
</template>

<script setup>
import NewsCard from './NewsCard.vue'

defineProps({
  searchMode: { type: Boolean, default: false },
  searchFocused: { type: Boolean, default: false },
  searchQuery: { type: String, default: '' },
  searchSubmitted: { type: Boolean, default: false },
  searchList: { type: Array, default: () => [] },
  searchTotal: { type: Number, default: 0 },
  searchLoading: { type: Boolean, default: false },
  searchLoadingMore: { type: Boolean, default: false },
  searchNoMore: { type: Boolean, default: false },
  searchHistory: { type: Array, default: () => [] },
  hotTopics: { type: Array, default: () => [] },
})

defineEmits([
  'input',
  'focus',
  'confirm',
  'clear',
  'exit',
  'clear-history',
  'quick-search',
  'open',
  'tag-search',
  'ticker-click',
])
</script>
