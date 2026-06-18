<template>
  <view>
    <!-- 周期切换 -->
    <view class="sepa-filter-bar">
      <view class="sepa-filter-chip" :class="{ active: period === 'all' }" @click="setPeriod('all')">全程</view>
      <view class="sepa-filter-chip" :class="{ active: period === 'week' }" @click="setPeriod('week')">本周</view>
    </view>

    <view v-if="loading" class="sepa-loading">加载中…</view>

    <template v-else-if="kpi">
      <!-- 纪律达标率（核心 KPI）-->
      <view class="sepa-card">
        <view class="sepa-kpi-hero">
          <view class="sepa-kpi-ring" :class="disciplineClass">
            {{ kpi.discipline_rate == null ? '—' : kpi.discipline_rate + '%' }}
          </view>
          <view class="sepa-kpi-ring-label">纪律达标率（目标 {{ kpi.discipline_target }}%）</view>
          <view class="sepa-progress">
            <view class="sepa-progress-fill" :class="{ ok: (kpi.discipline_rate || 0) >= kpi.discipline_target }"
                  :style="{ width: (kpi.discipline_rate || 0) + '%' }"></view>
          </view>
        </view>
      </view>

      <!-- 其余 KPI -->
      <view class="sepa-card">
        <view class="sepa-kpi-grid">
          <view class="sepa-kpi-cell">
            <view class="num" :class="plrClass">{{ kpi.profit_loss_ratio == null ? '—' : kpi.profit_loss_ratio }}</view>
            <view class="lbl">盈亏比</view>
            <view class="tgt">目标 ≥ {{ kpi.profit_loss_target }}　均盈 {{ kpi.avg_win_pct }}% / 均亏 {{ kpi.avg_loss_pct }}%</view>
          </view>
          <view class="sepa-kpi-cell">
            <view class="num" :class="winClass">{{ kpi.win_rate == null ? '—' : kpi.win_rate + '%' }}</view>
            <view class="lbl">胜率</view>
            <view class="tgt">参考 ≥ {{ kpi.win_rate_ref }}%</view>
          </view>
          <view class="sepa-kpi-cell">
            <view class="num" :class="{ ok: kpi.sample_size >= kpi.sample_target }">{{ kpi.sample_size }}</view>
            <view class="lbl">样本量（已完成）</view>
            <view class="tgt">目标 ≥ {{ kpi.sample_target }}</view>
            <view class="sepa-progress">
              <view class="sepa-progress-fill" :class="{ ok: kpi.sample_size >= kpi.sample_target }"
                    :style="{ width: Math.min(100, kpi.sample_size / kpi.sample_target * 100) + '%' }"></view>
            </view>
          </view>
          <view class="sepa-kpi-cell">
            <view class="num" :class="pnlClass(kpi.total_return)">{{ fmtPct(kpi.total_return) }}</view>
            <view class="lbl">总收益（参考）</view>
            <view class="tgt">不设要求</view>
          </view>
        </view>
      </view>

      <!-- 实验评估结论 -->
      <view class="sepa-card">
        <view class="sepa-section-title">实验评估结论</view>
        <view class="sepa-verdict" :class="kpi.passed ? 'pass' : 'fail'">{{ kpi.verdict }}</view>
        <view class="sepa-mindcard">达标条件：纪律 100% + 盈亏比 ≥ 2 + 样本 ≥ 15。核心产出是「纪律达标率」，不是收益率。</view>
      </view>
    </template>
  </view>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { fetchSepaKpi } from '@/utils/api'

const props = defineProps({
  market: { type: String, required: true },
})

const loading = ref(false)
const kpi = ref(null)
const period = ref('all')

const load = async () => {
  loading.value = true
  try {
    kpi.value = await fetchSepaKpi(props.market, period.value)
  } catch (e) {
    uni.showToast({ title: '加载失败', icon: 'none' })
  } finally {
    loading.value = false
  }
}

const setPeriod = (p) => {
  if (period.value === p) return
  period.value = p
  load()
}

const fmtPct = (v) => {
  if (v == null) return '—'
  return (v > 0 ? '+' : '') + v + '%'
}
const pnlClass = (v) => {
  if (v == null || v === 0) return 'pnl-flat'
  return v > 0 ? 'pnl-up' : 'pnl-down'
}
const disciplineClass = computed(() => {
  if (!kpi.value || kpi.value.discipline_rate == null) return ''
  return kpi.value.discipline_rate >= kpi.value.discipline_target ? 'ok' : 'bad'
})
const plrClass = computed(() => {
  if (!kpi.value || kpi.value.profit_loss_ratio == null) return ''
  return kpi.value.profit_loss_ratio >= kpi.value.profit_loss_target ? 'ok' : 'bad'
})
const winClass = computed(() => {
  if (!kpi.value || kpi.value.win_rate == null) return ''
  return kpi.value.win_rate >= kpi.value.win_rate_ref ? 'ok' : 'bad'
})

watch(() => props.market, () => { period.value = 'all'; load() })
defineExpose({ load })
load()
</script>
