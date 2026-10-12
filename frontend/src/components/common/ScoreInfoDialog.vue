<template>
  <view v-if="visible" class="dlg-mask" @click="$emit('close')">
    <view class="dlg" @click.stop>
      <view class="dlg-head">
        <text class="dlg-title">评分与信源</text>
        <text class="dlg-close" @click="$emit('close')">✕</text>
      </view>

      <view class="dlg-body">
        <view class="score-intro">
          评分满分为 10 分，保留一位小数。综合事件影响力、信息时效性与信源权威度，帮助你安排阅读优先级。
        </view>

        <view v-for="row in rows" :key="row.label" class="score-explain">
          <view class="score-chip" :class="row.cls">
            <text class="score-chip-num">{{ row.sample }}</text>
          </view>
          <view class="score-explain-body">
            <text class="score-explain-title">{{ row.label }}</text>
            <text class="score-explain-desc">{{ row.desc }}</text>
          </view>
        </view>

        <view class="score-note-title">确定性单独判断：</view>
        <view class="score-note">
          「依据充分」表示有正式公告或清晰的一手证据；「有待确认」表示关键细节仍需官方确认。信源数量展示关联报道的不同来源，多个来源可能引用同一份原始消息。
        </view>
      </view>

      <view class="dlg-actions">
        <text class="dlg-btn dlg-btn-primary" @click="$emit('close')">我知道了</text>
      </view>
    </view>
  </view>
</template>

<script setup>
defineProps({
  visible: { type: Boolean, default: false },
})
defineEmits(['close'])

const rows = [
  { sample: '9.2', cls: 'score-chip-major', label: '9 分及以上 · 重大', desc: '影响范围广，值得立即查看。' },
  { sample: '8.3', cls: 'score-chip-important', label: '8—8.9 分 · 重要', desc: '有明确新增信息，建议优先阅读。' },
  { sample: '7.6', cls: 'score-chip-normal', label: '7—7.9 分 · 值得关注', desc: '与相关领域有关，可结合兴趣阅读。' },
  { sample: '6.4', cls: 'score-chip-low', label: '低于 7 分 · 常规', desc: '使用灰色弱化显示，可稍后阅读。' },
]
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
  box-shadow: 0 20px 60px rgba(21, 35, 61, 0.22);
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
.dlg-body { padding: 4px 20px 8px; max-height: 62vh; overflow-y: auto; }

.score-intro {
  font-size: 12px;
  color: var(--color-text-secondary);
  line-height: 1.75;
  padding: 14px 0;
}

.score-explain {
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 12px 0;
  border-bottom: 1px solid var(--color-border);
}
.score-chip {
  width: 42px;
  height: 34px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: none;
  font-variant-numeric: tabular-nums;
}
.score-chip-num { font-size: 13px; font-weight: 650; }
.score-chip-major { background: var(--score-1-bg); }
.score-chip-major .score-chip-num { color: var(--score-1-text); }
.score-chip-important { background: var(--score-2-bg); }
.score-chip-important .score-chip-num { color: var(--score-2-text); }
.score-chip-normal { background: var(--score-3-bg); }
.score-chip-normal .score-chip-num { color: var(--score-3-text); }
.score-chip-low { background: var(--score-4-bg); }
.score-chip-low .score-chip-num { color: var(--score-4-text); }

.score-explain-body { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.score-explain-title { font-size: 12px; font-weight: 600; color: var(--color-text-primary); }
.score-explain-desc { font-size: 11px; color: var(--color-text-muted); line-height: 1.6; }

.score-note-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--color-text-primary);
  padding: 14px 0 4px;
}
.score-note {
  font-size: 11px;
  color: var(--color-text-muted);
  line-height: 1.75;
  padding-bottom: 6px;
}

.dlg-actions {
  display: flex;
  justify-content: flex-end;
  padding: 14px 20px 18px;
  border-top: 1px solid var(--color-border);
}
.dlg-btn-primary {
  font-size: 13px;
  padding: 8px 18px;
  border-radius: 8px;
  cursor: pointer;
  background: var(--color-brand);
  border: 1px solid var(--color-brand);
  color: #fff;
  font-weight: 600;
}
</style>
