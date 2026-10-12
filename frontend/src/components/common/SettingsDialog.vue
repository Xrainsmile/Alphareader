<template>
  <view v-if="visible" class="dlg-mask" @click="$emit('close')">
    <view class="dlg" @click.stop>
      <view class="dlg-head">
        <text class="dlg-title">阅读设置</text>
        <text class="dlg-close" @click="$emit('close')">✕</text>
      </view>

      <view class="dlg-body">
        <view class="set-row">
          <text class="set-label">界面语言</text>
          <text class="set-value">简体中文</text>
        </view>

        <view class="set-row">
          <text class="set-label">时间显示</text>
          <text class="set-value">北京时间（UTC+8）</text>
        </view>

        <view class="set-row">
          <text class="set-label">资讯阅读密度</text>
          <view class="set-seg">
            <text
              class="set-seg-btn"
              :class="{ 'set-seg-on': density === 'compact' }"
              @click="pick('compact')"
            >紧凑</text>
            <text
              class="set-seg-btn"
              :class="{ 'set-seg-on': density === 'standard' }"
              @click="pick('standard')"
            >舒适</text>
          </view>
        </view>

        <view class="set-note">
          导航、日期、筛选和提示统一使用中文。公司品牌、媒体名称与股票代码保留原名，避免歧义。收藏与阅读密度会保存在当前浏览器中。
        </view>
      </view>

      <view class="dlg-actions">
        <text class="dlg-btn dlg-btn-primary" @click="$emit('close')">完成</text>
      </view>
    </view>
  </view>
</template>

<script setup>
import { computed } from 'vue'
import { useBookmarks } from '@/utils/useBookmarks.js'

const props = defineProps({
  visible: { type: Boolean, default: false },
})
const emit = defineEmits(['close'])

const { settings, updateSettings } = useBookmarks()
const density = computed(() => settings.value.density)

function pick(mode) {
  updateSettings({ density: mode })
  // 同步到资讯列表使用的存储键，保证两处一致
  try { uni.setStorageSync('news_density', mode) } catch (_) {}
  emit('close')
}
</script>

<style scoped>
.dlg-mask {
  position: fixed;
  inset: 0;
  background: rgba(28, 38, 60, 0.32);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 900;
  padding: 20px;
}
.dlg {
  width: 100%;
  max-width: 440px;
  background: var(--color-bg-card);
  border-radius: 14px;
  box-shadow: 0 20px 60px rgba(21, 35, 61, 0.18);
  overflow: hidden;
}
.dlg-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--color-border);
}
.dlg-title { font-size: 16px; font-weight: 650; color: var(--color-text-primary); }
.dlg-close { font-size: 14px; color: var(--color-text-muted); padding: 2px 4px; cursor: pointer; }
.dlg-body { padding: 4px 20px 8px; max-height: 60vh; overflow-y: auto; }

.set-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 15px;
  padding: 14px 0;
  border-bottom: 1px solid var(--color-border);
  font-size: 13px;
}
.set-label { color: var(--color-text-primary); flex: none; }
.set-value { color: var(--color-text-muted); font-size: 12px; }
.set-seg {
  display: inline-flex;
  background: var(--color-bg-secondary);
  border-radius: 7px;
  padding: 2px;
  gap: 2px;
  flex: none;
}
.set-seg-btn {
  font-size: 12px;
  color: var(--color-text-secondary);
  padding: 4px 12px;
  border-radius: 5px;
  cursor: pointer;
}
.set-seg-on {
  background: var(--color-bg-card);
  color: var(--color-brand);
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(23, 34, 62, 0.08);
}
.set-note {
  font-size: 11px;
  color: var(--color-text-muted);
  line-height: 1.7;
  padding: 14px 0 4px;
}

.dlg-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 20px 18px;
  border-top: 1px solid var(--color-border);
}
.dlg-btn {
  font-size: 13px;
  padding: 8px 18px;
  border-radius: 8px;
  cursor: pointer;
  border: 1px solid var(--color-border);
  color: var(--color-text-secondary);
}
.dlg-btn-primary {
  background: var(--color-brand);
  border-color: var(--color-brand);
  color: #fff;
  font-weight: 600;
}
</style>
