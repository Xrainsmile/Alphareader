<template>
  <view v-if="visible" class="modal-overlay" @click.self="close">
    <view class="modal-card">
      <!-- 头部 -->
      <view class="modal-header">
        <text class="modal-icon">📋</text>
        <text class="modal-title">录入价投标的</text>
        <text class="modal-desc">搜索并选择要加入价投观察池的股票</text>
      </view>

      <!-- 搜索框 -->
      <view class="search-wrap" :class="{ 'search-focus': searchFocused }">
        <text class="search-icon">🔍</text>
        <input
          class="search-input"
          type="text"
          placeholder="输入代码或名称搜索..."
          :value="searchQuery"
          :focus="visible && !selectedStock"
          @focus="searchFocused = true"
          @blur="searchFocused = false"
          @input="onInput"
          @confirm="doSearch"
        />
        <text v-if="searchQuery" class="search-clear" @click="clearSearch">✕</text>
      </view>

      <!-- 搜索结果列表 -->
      <view v-if="!selectedStock && searchResults.length > 0" class="result-list">
        <view
          v-for="item in searchResults"
          :key="item.ts_code"
          class="result-item"
          @click="selectStock(item)"
        >
          <text class="result-name">{{ item.name }}</text>
          <text class="result-code">{{ item.ts_code }}</text>
        </view>
      </view>
      <view v-if="!selectedStock && searched && searchResults.length === 0 && !searching" class="empty-hint">
        <text class="empty-text">无匹配结果</text>
      </view>
      <view v-if="searching" class="empty-hint">
        <text class="empty-text">搜索中...</text>
      </view>

      <!-- 已选中的股票 -->
      <view v-if="selectedStock" class="selected-card">
        <view class="selected-info">
          <text class="selected-name">{{ selectedStock.name }}</text>
          <text class="selected-code">{{ selectedStock.ts_code }}</text>
        </view>
        <view class="selected-remove" @click="clearSelection">
          <text class="remove-icon">✕</text>
        </view>
      </view>

      <!-- 投资理由（可选） -->
      <view v-if="selectedStock" class="reason-wrap">
        <textarea
          class="reason-input"
          placeholder="投资理由（可选）"
          :value="reason"
          @input="reason = $event.detail.value"
          maxlength="200"
          :auto-height="true"
        />
      </view>

      <!-- 提交状态 -->
      <text v-if="submitError" class="error-text">{{ submitError }}</text>

      <!-- 按钮 -->
      <view class="modal-actions">
        <view class="btn btn-cancel" @click="close">
          <text class="btn-text cancel-text">取消</text>
        </view>
        <view
          class="btn btn-confirm"
          :class="{ 'btn-disabled': !selectedStock || submitting }"
          @click="submit"
        >
          <text class="btn-text confirm-text">{{ submitting ? '提交中...' : '确认录入' }}</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  visible: { type: Boolean, required: true },
})

const emit = defineEmits(['update:visible', 'added'])

// 搜索状态
const searchQuery = ref('')
const searchFocused = ref(false)
const searchResults = ref([])
const searching = ref(false)
const searched = ref(false)

// 选中状态
const selectedStock = ref(null)
const reason = ref('')

// 提交状态
const submitting = ref(false)
const submitError = ref('')

// 打开时重置
watch(() => props.visible, (v) => {
  if (v) {
    searchQuery.value = ''
    searchResults.value = []
    searched.value = false
    searching.value = false
    selectedStock.value = null
    reason.value = ''
    submitting.value = false
    submitError.value = ''
  }
})

const close = () => emit('update:visible', false)

let searchTimer = null
const onInput = (e) => {
  searchQuery.value = e.detail.value
  submitError.value = ''
  if (searchTimer) clearTimeout(searchTimer)
  if (!e.detail.value.trim()) {
    searchResults.value = []
    searched.value = false
    return
  }
  // 防抖 400ms 自动搜索
  searchTimer = setTimeout(() => doSearch(), 400)
}

const doSearch = async () => {
  const q = searchQuery.value.trim()
  if (!q) return
  searching.value = true
  searched.value = false
  try {
    const res = await uni.request({
      url: `${import.meta.env.VITE_API_BASE_URL || (import.meta.env.MODE === 'production' ? '' : 'http://localhost:8000')}/api/v1/sandbox/stock-search?q=${encodeURIComponent(q)}`,
      method: 'GET',
      header: {
        'X-API-Key': import.meta.env.VITE_API_KEY || '',
      },
    })
    if (res[0]) throw res[0]
    const data = res[1] || res
    const body = data.data || data
    searchResults.value = body.items || []
  } catch (e) {
    console.error('搜索失败:', e)
    searchResults.value = []
  } finally {
    searching.value = false
    searched.value = true
  }
}

const clearSearch = () => {
  searchQuery.value = ''
  searchResults.value = []
  searched.value = false
}

const selectStock = (item) => {
  selectedStock.value = item
  searchResults.value = []
  searchQuery.value = ''
}

const clearSelection = () => {
  selectedStock.value = null
  reason.value = ''
  submitError.value = ''
}

const submit = async () => {
  if (!selectedStock.value || submitting.value) return
  submitting.value = true
  submitError.value = ''

  // 从 localStorage 获取密码缓存；若无缓存则用已验证过的密码（进入模拟仓时已验证）
  let pwd = ''
  try { pwd = uni.getStorageSync('sb_pwd') || '' } catch (_) {}
  if (!pwd) {
    submitError.value = '请先退出重新进入模拟仓验证密码'
    submitting.value = false
    return
  }

  try {
    const res = await uni.request({
      url: `${import.meta.env.VITE_API_BASE_URL || (import.meta.env.MODE === 'production' ? '' : 'http://localhost:8000')}/api/v1/sandbox/value-stock/add`,
      method: 'POST',
      header: {
        'Content-Type': 'application/json',
        'X-API-Key': import.meta.env.VITE_API_KEY || '',
      },
      data: {
        ts_code: selectedStock.value.ts_code,
        name: selectedStock.value.name,
        reason: reason.value.trim() || null,
        password: pwd,
      },
    })
    const data = res[1] || res
    if (data.statusCode >= 400) {
      const detail = data.data?.detail || `HTTP ${data.statusCode}`
      submitError.value = detail
      submitting.value = false
      return
    }
    // 成功
    emit('added')
    close()
    uni.showToast({ title: '录入成功', icon: 'success' })
  } catch (e) {
    console.error('录入失败:', e)
    submitError.value = e.message || '网络错误'
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(26, 26, 46, 0.5);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  animation: fadeIn 0.2s ease;
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

.modal-card {
  width: 640rpx;
  max-width: 340px;
  max-height: 80vh;
  background: #ffffff;
  border-radius: 24rpx;
  padding: 44rpx 36rpx 32rpx;
  box-shadow: 0 16rpx 48rpx rgba(0, 0, 0, 0.12);
  animation: slideUp 0.25s ease;
  overflow-y: auto;
}
@keyframes slideUp { from { transform: translateY(40rpx); opacity: 0; } to { transform: translateY(0); opacity: 1; } }

.modal-header {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 32rpx;
}
.modal-icon { font-size: 44rpx; margin-bottom: 12rpx; }
.modal-title {
  font-size: 34rpx;
  font-weight: 700;
  color: #1a1a2e;
  letter-spacing: 1rpx;
  font-family: 'SF Pro Display', 'PingFang SC', -apple-system, sans-serif;
}
.modal-desc {
  font-size: 24rpx;
  color: #8c8c9a;
  margin-top: 8rpx;
  text-align: center;
}

/* 搜索框 */
.search-wrap {
  display: flex;
  align-items: center;
  background: #f5f6f8;
  border-radius: 16rpx;
  padding: 20rpx 24rpx;
  border: 2rpx solid #e8e8ed;
  transition: border-color 0.2s, box-shadow 0.2s;
  gap: 12rpx;
}
.search-focus {
  border-color: #1a1a2e;
  box-shadow: 0 2rpx 12rpx rgba(26, 26, 46, 0.1);
}
.search-icon { font-size: 28rpx; flex-shrink: 0; }
.search-input {
  flex: 1;
  font-size: 28rpx;
  color: #1a1a2e;
  background: transparent;
  border: none;
  outline: none;
}
.search-clear {
  font-size: 26rpx;
  color: #8c8c9a;
  padding: 4rpx 8rpx;
  cursor: pointer;
  flex-shrink: 0;
}

/* 搜索结果 */
.result-list {
  max-height: 360rpx;
  overflow-y: auto;
  margin-top: 16rpx;
  background: #fafbfc;
  border-radius: 12rpx;
  border: 1rpx solid #e8e8ed;
}
.result-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20rpx 24rpx;
  border-bottom: 1rpx solid #f0f0f2;
  cursor: pointer;
  transition: background 0.15s;
}
.result-item:last-child { border-bottom: none; }
.result-item:active { background: #e8e8f0; }
.result-name {
  font-size: 28rpx;
  font-weight: 600;
  color: #1a1a2e;
}
.result-code {
  font-size: 24rpx;
  color: #8c8c9a;
  font-family: 'SF Mono', 'Menlo', monospace;
}

.empty-hint {
  text-align: center;
  padding: 24rpx 0;
}
.empty-text {
  font-size: 24rpx;
  color: #8c8c9a;
}

/* 已选中卡片 */
.selected-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 20rpx;
  padding: 20rpx 24rpx;
  background: #f0f4ff;
  border: 2rpx solid #3b82f6;
  border-radius: 14rpx;
}
.selected-info { display: flex; align-items: center; gap: 16rpx; }
.selected-name {
  font-size: 30rpx;
  font-weight: 700;
  color: #1a1a2e;
}
.selected-code {
  font-size: 24rpx;
  color: #3b82f6;
  font-family: 'SF Mono', 'Menlo', monospace;
}
.selected-remove {
  padding: 8rpx 12rpx;
  cursor: pointer;
}
.remove-icon {
  font-size: 26rpx;
  color: #8c8c9a;
}

/* 投资理由 */
.reason-wrap {
  margin-top: 20rpx;
}
.reason-input {
  width: 100%;
  min-height: 120rpx;
  font-size: 26rpx;
  color: #1a1a2e;
  background: #f5f6f8;
  border-radius: 14rpx;
  padding: 20rpx 24rpx;
  border: 2rpx solid #e8e8ed;
  box-sizing: border-box;
  line-height: 1.6;
  transition: border-color 0.2s;
}
.reason-input:focus {
  border-color: #1a1a2e;
}

/* 错误提示 */
.error-text {
  display: block;
  font-size: 22rpx;
  color: #ff3b30;
  margin-top: 16rpx;
  text-align: center;
}

/* 按钮 */
.modal-actions {
  display: flex;
  gap: 20rpx;
  margin-top: 28rpx;
}
.btn {
  flex: 1;
  padding: 22rpx 0;
  border-radius: 14rpx;
  text-align: center;
  cursor: pointer;
  transition: opacity 0.15s;
}
.btn:active { opacity: 0.7; }
.btn-cancel { background: #f0f2f5; }
.btn-confirm { background: #1a1a2e; }
.btn-disabled { opacity: 0.4; pointer-events: none; }
.btn-text { font-size: 28rpx; font-weight: 600; }
.cancel-text { color: #8c8c9a; }
.confirm-text { color: #ffffff; }

@media (min-width: 750px) {
  .modal-card { padding: 32px 28px 24px; border-radius: 16px; max-width: 360px; }
  .modal-icon { font-size: 28px; }
  .modal-title { font-size: 18px; }
  .modal-desc { font-size: 13px; }
  .search-wrap { padding: 10px 14px; border-radius: 10px; }
  .search-input { font-size: 15px; }
  .result-list { max-height: 200px; }
  .result-item { padding: 10px 14px; }
  .result-name { font-size: 15px; }
  .result-code { font-size: 13px; }
  .selected-card { padding: 10px 14px; border-radius: 10px; }
  .selected-name { font-size: 16px; }
  .selected-code { font-size: 13px; }
  .reason-input { font-size: 14px; padding: 10px 14px; min-height: 60px; border-radius: 10px; }
  .error-text { font-size: 12px; }
  .modal-actions { gap: 12px; margin-top: 20px; }
  .btn { padding: 12px 0; border-radius: 10px; }
  .btn-text { font-size: 15px; }
}
</style>
