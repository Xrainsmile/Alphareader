<template>
  <view class="page-layout">
    <PcSidebar active="bookmarks" @open-settings="showSettings = true" @open-score="showScore = true" />

    <view class="container">
      <view class="page-head">
        <view class="page-head-left">
          <text class="eyebrow">保留线索，随时回看</text>
          <text class="page-title">我的收藏</text>
          <text class="page-sub">收藏值得继续关注的事件，让阅读有迹可循。</text>
        </view>
      </view>

      <view class="list-summary">
        <text class="list-summary-text">已收藏 {{ bookmarkCount }} 个事件</text>
        <text class="list-summary-dim">按收藏时间排序</text>
      </view>

      <view v-if="!bookmarkCount" class="panel empty-panel">
        <text class="empty-title">还没有收藏的事件</text>
        <text class="empty-desc">在资讯列表、简报或详情页点击书签图标，即可收藏。</text>
        <text class="empty-link" @click="goNews">继续浏览资讯</text>
      </view>

      <view v-else class="panel news-list">
        <NewsCard
          v-for="item in items"
          :key="item.id"
          :item="item"
          :density="'standard'"
          @open="onOpen"
          @tag-search="onTagSearch"
          @ticker-click="onTicker"
        />
      </view>

      <view class="rail-note">
        收藏跟随事件：资讯列表、简报和详情页使用同一份收藏。可在任意入口添加或取消。
      </view>

      <SiteFooter />
    </view>

    <SettingsDialog :visible="showSettings" @close="showSettings = false" />
    <ScoreInfoDialog :visible="showScore" @close="showScore = false" />
  </view>
</template>

<script setup>
import { ref } from 'vue'
import PcSidebar from '@/components/common/PcSidebar.vue'
import SiteFooter from '@/components/common/SiteFooter.vue'
import NewsCard from '@/components/news/NewsCard.vue'
import SettingsDialog from '@/components/common/SettingsDialog.vue'
import ScoreInfoDialog from '@/components/common/ScoreInfoDialog.vue'
import { useBookmarks } from '@/utils/useBookmarks.js'

const showSettings = ref(false)
const showScore = ref(false)

// 收藏正文由 useBookmarks 统一维护（快照在收藏时写入），此处直接读取
const { bookmarkCount, bookmarkItems: items } = useBookmarks()

function goNews() {
  uni.switchTab({ url: '/pages/index/index' })
}

function onOpen(url, id) {
  if (url) uni.navigateTo({ url: `/pages/events/detail?id=${id}` })
}
function onTagSearch() {}
function onTicker() {}
</script>

<style scoped>
.page-layout { display: flex; min-height: 100vh; background: var(--color-bg); }
.container {
  flex: 1;
  min-width: 0;
  padding: 28px 26px 40px;
  max-width: 860px;
}
.page-head { margin-bottom: 22px; }
.page-head-left { display: flex; flex-direction: column; gap: 4px; }
.eyebrow {
  font-size: 11px;
  letter-spacing: 1.6px;
  font-weight: 600;
  color: var(--color-brand);
  margin-bottom: 4px;
}
.page-title { font-size: 24px; font-weight: 700; color: var(--color-text-primary); letter-spacing: -0.4px; }
.page-sub { font-size: 13px; color: var(--color-text-secondary); margin-top: 6px; line-height: 1.6; }

.list-summary {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 2px;
  font-size: 12px;
  color: var(--color-text-secondary);
}
.list-summary-dim { color: var(--color-text-muted); font-size: 11px; }

.panel {
  background: var(--color-bg-card);
  border: 1px solid var(--color-border);
  border-radius: 12px;
  padding: 8px 16px;
}
.empty-panel {
  padding: 46px 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  text-align: center;
}
.empty-title { font-size: 15px; font-weight: 600; color: var(--color-text-primary); }
.empty-desc { font-size: 12px; color: var(--color-text-secondary); line-height: 1.7; max-width: 380px; }
.empty-link { font-size: 13px; color: var(--color-brand); font-weight: 600; margin-top: 6px; cursor: pointer; }

.news-list { display: flex; flex-direction: column; }

.rail-note {
  font-size: 11px;
  color: var(--color-text-muted);
  line-height: 1.75;
  padding: 16px 2px 0;
}

/* 移动端：容器铺满 */
@media screen and (max-width: 767px) {
  .container { padding: 20px 14px 32px; max-width: none; }
  .page-title { font-size: 21px; }
}
</style>
