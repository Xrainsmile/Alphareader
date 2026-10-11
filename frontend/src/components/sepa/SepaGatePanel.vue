<template>
  <view>
    <view v-if="loading" class="sepa-loading">Loading...</view>

    <template v-else>
      <view class="sepa-card">
        <view class="sepa-gate-status" :class="gate.gate_open ? 'open' : 'closed'">
          <view class="big">{{ gate.gate_open ? '🟢 闸门开启' : '🔴 闸门关闭' }}</view>
          <view class="sub">{{ gate.gate_open ? '允许开新仓' : '禁止开新仓，仅可管理已有持仓' }}</view>
        </view>
        <view class="sepa-section-sub" v-if="gate.updated_at">最后更新：{{ gate.updated_at.slice(0, 16).replace('T', ' ') }}</view>
      </view>

      <!-- 4 项指标编辑 -->
      <view class="sepa-card">
        <view class="sepa-section-title">Market Gate Indicators <text class="sepa-section-sub">All 4 conditions → Gate Open</text></view>

        <view class="sepa-check-row">
          <text class="sepa-check-label">① Index above 50-day MA</text>
          <switch :checked="form.index_above_ma50" color="var(--color-down)" @change="onSwitch('index_above_ma50', $event)" />
        </view>
        <view class="sepa-check-row">
          <text class="sepa-check-label">② 50-day MA slope rising</text>
          <switch :checked="form.ma50_trending_up" color="var(--color-down)" @change="onSwitch('ma50_trending_up', $event)" />
        </view>
        <view class="sepa-check-row">
          <text class="sepa-check-label">③ Market breadth healthy (A/D ratio &gt; 1)</text>
          <switch :checked="form.breadth_healthy" color="var(--color-down)" @change="onSwitch('breadth_healthy', $event)" />
        </view>
        <view class="sepa-check-row">
          <text class="sepa-check-label">④ New highs &gt; new lows</text>
          <switch :checked="form.new_highs_gt_lows" color="var(--color-down)" @change="onSwitch('new_highs_gt_lows', $event)" />
        </view>

        <view class="sepa-field" style="margin-top: 18rpx;">
          <text class="sepa-field-label">Notes</text>
          <input class="sepa-input" :value="form.note" placeholder="如：大盘转弱，缩量观望" @input="form.note = $event.detail.value" />
        </view>

        <view class="sepa-risk-box" style="margin-top: 0;">
          <view class="sepa-risk-line">
            <text class="k">Gate Status After Submit</text>
            <text class="v" :class="computedOpen ? 'pnl-down' : 'pnl-up'">{{ computedOpen ? '开启' : '关闭' }}</text>
          </view>
        </view>

        <view class="sepa-btn sepa-btn-primary" style="margin-top: 16rpx;" @click="save">Save Gate Status</view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { fetchSepaGate, updateSepaGate } from '@/utils/api'

const props = defineProps({
  market: { type: String, required: true },
  unlocked: { type: Boolean, default: false },
})
const emit = defineEmits(['need-unlock', 'changed'])

const loading = ref(false)
const gate = ref({ gate_open: false })
const form = reactive({
  index_above_ma50: false,
  ma50_trending_up: false,
  breadth_healthy: false,
  new_highs_gt_lows: false,
  note: '',
})

const computedOpen = computed(() =>
  form.index_above_ma50 && form.ma50_trending_up && form.breadth_healthy && form.new_highs_gt_lows
)

const load = async () => {
  loading.value = true
  try {
    const g = await fetchSepaGate(props.market)
    gate.value = g
    form.index_above_ma50 = g.index_above_ma50
    form.ma50_trending_up = g.ma50_trending_up
    form.breadth_healthy = g.breadth_healthy
    form.new_highs_gt_lows = g.new_highs_gt_lows
    form.note = g.note || ''
  } catch (e) {
    uni.showToast({ title: 'Failed to load', icon: 'none' })
  } finally {
    loading.value = false
  }
}

const onSwitch = (key, e) => { form[key] = e.detail.value }

const save = async () => {
  if (!props.unlocked) { emit('need-unlock'); return }
  try {
    await updateSepaGate({ market: props.market, ...form })
    uni.showToast({ title: 'Saved', icon: 'success' })
    await load()
    emit('changed')
  } catch (e) {
    uni.showToast({ title: e.message || '保存失败', icon: 'none' })
  }
}

watch(() => props.market, load)
defineExpose({ load })
load()
</script>
