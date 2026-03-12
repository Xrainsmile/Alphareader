<template>
  <view v-if="visible" class="modal-overlay" @click.self="onClose">
    <view class="modal-card">
      <!-- 头部 -->
      <view class="modal-header">
        <text class="modal-icon">💎</text>
        <text class="modal-title">添加价投标的</text>
        <text class="modal-desc">搜索股票代码或名称，录入投资理由</text>
      </view>

      <!-- Step 1: 搜索选股 -->
      <view v-if="step === 1" class="modal-body">
        <view class="field-label">选择股票</view>
        <view class="search-wrap">
          <text class="search-icon">🔍</text>
          <input
            class="search-input"
            type="text"
            v-model="searchQuery"
            placeholder="输入代码或名称..."
            @input="onSearchInput"
            @confirm="doSearch"
            :focus="visible && step === 1"
          />
          <view v-if="searchQuery" class="search-clear" @click="searchQuery = ''; searchResults = []">
            <text class="clear-icon">×</text>
          </view>
        </view>

        <!-- 搜索结果 -->
        <view v-if="searching" class="search-status">
          <text class="search-status-text">搜索中...</text>
        </view>
        <scroll-view v-else-if="searchResults.length > 0" scroll-y class="search-results">
          <view
            v-for="item in searchResults"
            :key="item.ts_code"
            class="search-result-item"
            :class="{ 'result-selected': selected && selected.ts_code === item.ts_code }"
            @click="onSelectStock(item)"
          >
            <view class="result-info">
              <text class="result-name">{{ item.name }}</text>
              <text class="result-code">{{ item.ts_code }}</text>
            </view>
            <text v-if="selected && selected.ts_code === item.ts_code" class="result-check">✓</text>
          </view>
        </scroll-view>
        <view v-else-if="searchQuery && searchDone" class="search-status">
          <text class="search-status-text">未找到匹配股票</text>
        </view>

        <!-- 已选股票 -->
        <view v-if="selected" class="selected-stock">
          <view class="selected-info">
            <text class="selected-name">{{ selected.name }}</text>
            <text class="selected-code">{{ selected.ts_code }}</text>
          </view>
          <view class="selected-remove" @click="selected = null">
            <text class="remove-icon">✕</text>
          </view>
        </view>

        <!-- 投资理由 -->
        <view class="field-label" style="margin-top: 24rpx;">投资理由（可选）</view>
        <textarea
          class="reason-input"
          v-model="reason"
          placeholder="为什么看好这家公司？好生意 / 好公司 / 好价格..."
          maxlength="500"
          :auto-height="true"
        />

        <view class="modal-actions">
          <view class="modal-btn btn-cancel" @click="onClose">
            <text class="btn-text cancel-text">取消</text>
          </view>
          <view class="modal-btn btn-confirm" :class="{ 'btn-disabled': !selected }" @click="goStep2">
            <text class="btn-text confirm-text">下一步</text>
          </view>
        </view>
      </view>

      <!-- Step 2: 密码验证 -->
      <view v-if="step === 2" class="modal-body">
        <view class="confirm-summary">
          <text class="confirm-label">即将添加</text>
          <view class="confirm-stock">
            <text class="confirm-name">{{ selected?.name }}</text>
            <text class="confirm-code">{{ selected?.ts_code }}</text>
          </view>
          <text v-if="reason" class="confirm-reason">{{ reason }}</text>
        </view>

        <view class="field-label">输入访问密码</view>
        <view class="pwd-wrap" :class="{ 'pwd-error': pwdError }">
          <input
            class="pwd-input"
            type="text"
            :password="true"
            v-model="password"
            placeholder="请输入密码"
            :focus="step === 2"
            @confirm="onSubmit"
          />
        </view>
        <text v-if="pwdError" class="error-text">密码错误，请重试</text>

        <view class="modal-actions">
          <view class="modal-btn btn-cancel" @click="step = 1">
            <text class="btn-text cancel-text">返回</text>
          </view>
          <view class="modal-btn btn-confirm" :class="{ 'btn-disabled': !password || submitting }" @click="onSubmit">
            <text class="btn-text confirm-text">{{ submitting ? '提交中...' : '确认添加' }}</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
import { ref, watch } from 'vue'
import { searchSandboxStock, addValueStock } from '@/utils/api'

const props = defineProps({
  visible: { type: Boolean, required: true },
})

const emit = defineEmits(['update:visible', 'added'])

const step = ref(1)
const searchQuery = ref('')
const searching = ref(false)
const searchDone = ref(false)
const searchResults = ref([])
const selected = ref(null)
const reason = ref('')
const password = ref('')
const pwdError = ref(false)
const submitting = ref(false)

let searchTimer = null

// 重置状态
watch(() => props.visible, (v) => {
  if (v) {
    step.value = 1
    searchQuery.value = ''
    searchResults.value = []
    selected.value = null
    reason.value = ''
    password.value = ''
    pwdError.value = false
    submitting.value = false
    searchDone.value = false
  }
})

const onClose = () => {
  emit('update:visible', false)
}

const onSearchInput = () => {
  searchDone.value = false
  if (searchTimer) clearTimeout(searchTimer)
  const q = searchQuery.value.trim()
  if (!q || q.length < 1) {
    searchResults.value = []
    return
  }
  searchTimer = setTimeout(() => doSearch(), 400)
}

const doSearch = async () => {
  const q = searchQuery.value.trim()
  if (!q) return
  searching.value = true
  try {
    const data = await searchSandboxStock(q)
    searchResults.value = data.items || []
  } catch (e) {
    console.error('搜索失败:', e)
  } finally {
    searching.value = false
    searchDone.value = true
  }
}

const onSelectStock = (item) => {
  selected.value = { ts_code: item.ts_code, name: item.name }
  searchResults.value = []
  searchQuery.value = ''
  searchDone.value = false
}

const goStep2 = () => {
  if (!selected.value) return
  step.value = 2
}

const onSubmit = async () => {
  if (!password.value || submitting.value) return
  submitting.value = true
  pwdError.value = false

  try {
    await addValueStock({
      ts_code: selected.value.ts_code,
      name: selected.value.name,
      reason: reason.value || null,
      password: password.value,
    })
    // 缓存密码供后续删除操作使用
    try { uni.setStorageSync('value_pwd', password.value) } catch (_) {}
    uni.showToast({ title: '添加成功', icon: 'success' })
    emit('added')
    emit('update:visible', false)
  } catch (e) {
    const msg = e.message || ''
    if (msg.includes('403')) {
      pwdError.value = true
      setTimeout(() => { pwdError.value = false }, 1500)
    } else if (msg.includes('409')) {
      uni.showToast({ title: '该股票已在白名单中', icon: 'none' })
    } else {
      uni.showToast({ title: '添加失败', icon: 'none' })
    }
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
  max-width: 360px;
  background: #ffffff;
  border-radius: 24rpx;
  padding: 40rpx 36rpx 32rpx;
  box-shadow: 0 16rpx 48rpx rgba(0, 0, 0, 0.12);
  animation: slideUp 0.25s ease;
  max-height: 85vh;
  overflow-y: auto;
}
@keyframes slideUp { from { transform: translateY(40rpx); opacity: 0; } to { transform: translateY(0); opacity: 1; } }

.modal-header {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 32rpx;
}
.modal-icon { font-size: 48rpx; margin-bottom: 12rpx; }
.modal-title {
  font-size: 34rpx; font-weight: 700; color: #1a1a2e;
  letter-spacing: 1rpx;
  font-family: 'SF Pro Display', 'PingFang SC', -apple-system, sans-serif;
}
.modal-desc {
  font-size: 24rpx; color: #8c8c9a; margin-top: 8rpx; text-align: center; line-height: 1.5;
}

.modal-body { }

.field-label {
  font-size: 24rpx; color: #6a6a7a; font-weight: 600;
  margin-bottom: 12rpx;
}

/* 搜索栏 */
.search-wrap {
  display: flex;
  align-items: center;
  background: #f5f6f8;
  border-radius: 16rpx;
  padding: 20rpx 24rpx;
  border: 2rpx solid #e8e8ed;
  transition: border-color 0.2s;
}
.search-wrap:focus-within {
  border-color: #3b82f6;
}
.search-icon { font-size: 28rpx; margin-right: 12rpx; flex-shrink: 0; }
.search-input {
  flex: 1; font-size: 28rpx; color: #1a1a2e;
  background: transparent; border: none; outline: none;
}
.search-clear { padding: 4rpx 8rpx; cursor: pointer; }
.clear-icon { font-size: 32rpx; color: #b0b0be; }

/* 搜索结果 */
.search-results {
  max-height: 360rpx;
  margin-top: 12rpx;
  border: 2rpx solid #e8e8ed;
  border-radius: 12rpx;
  background: #fff;
}
.search-result-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18rpx 20rpx;
  border-bottom: 1rpx solid #f0f0f2;
  cursor: pointer;
  transition: background 0.15s;
}
.search-result-item:last-child { border-bottom: none; }
.search-result-item:active { background: #f0f5ff; }
.result-selected { background: #f0f5ff; }
.result-info { display: flex; flex-direction: column; }
.result-name { font-size: 28rpx; font-weight: 600; color: #1a1a2e; }
.result-code { font-size: 22rpx; color: #8c8c9a; margin-top: 2rpx; font-family: 'SF Mono', 'Menlo', monospace; }
.result-check { font-size: 28rpx; color: #3b82f6; font-weight: 700; }

.search-status {
  padding: 24rpx; text-align: center;
}
.search-status-text { font-size: 24rpx; color: #8c8c9a; }

/* 已选股票 */
.selected-stock {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 16rpx;
  padding: 18rpx 20rpx;
  background: #f0f7ff;
  border-radius: 12rpx;
  border: 2rpx solid #3b82f6;
}
.selected-info { display: flex; align-items: baseline; gap: 10rpx; }
.selected-name { font-size: 28rpx; font-weight: 700; color: #1a1a2e; }
.selected-code { font-size: 22rpx; color: #3b82f6; font-family: 'SF Mono', 'Menlo', monospace; }
.selected-remove {
  padding: 8rpx 12rpx; cursor: pointer;
}
.remove-icon { font-size: 28rpx; color: #8c8c9a; }

/* 投资理由 */
.reason-input {
  width: 100%;
  min-height: 120rpx;
  padding: 20rpx 24rpx;
  font-size: 26rpx;
  color: #1a1a2e;
  background: #f5f6f8;
  border: 2rpx solid #e8e8ed;
  border-radius: 12rpx;
  line-height: 1.6;
  transition: border-color 0.2s;
}
.reason-input:focus {
  border-color: #3b82f6;
}

/* 确认摘要 */
.confirm-summary {
  background: #f8fafc;
  border-radius: 12rpx;
  padding: 24rpx;
  margin-bottom: 24rpx;
}
.confirm-label { font-size: 22rpx; color: #8c8c9a; display: block; margin-bottom: 10rpx; }
.confirm-stock { display: flex; align-items: baseline; gap: 10rpx; margin-bottom: 8rpx; }
.confirm-name { font-size: 32rpx; font-weight: 800; color: #1a1a2e; }
.confirm-code { font-size: 24rpx; color: #3b82f6; font-family: 'SF Mono', 'Menlo', monospace; }
.confirm-reason {
  font-size: 24rpx; color: #4a4a5a; line-height: 1.6;
  display: block; margin-top: 8rpx;
}

/* 密码输入 */
.pwd-wrap {
  background: #f5f6f8;
  border-radius: 16rpx;
  padding: 22rpx 24rpx;
  border: 2rpx solid #e8e8ed;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.pwd-wrap:focus-within {
  border-color: #1a1a2e;
  box-shadow: 0 2rpx 12rpx rgba(26, 26, 46, 0.1);
}
.pwd-error {
  border-color: #ff3b30 !important;
  box-shadow: 0 2rpx 12rpx rgba(255, 59, 48, 0.15) !important;
  animation: shake 0.3s ease;
}
@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-8rpx); }
  75% { transform: translateX(8rpx); }
}
.pwd-input {
  width: 100%; font-size: 28rpx; color: #1a1a2e;
  background: transparent; border: none; outline: none; letter-spacing: 4rpx;
}
.error-text {
  display: block; font-size: 22rpx; color: #ff3b30;
  margin-top: 10rpx; text-align: center;
}

/* 操作按钮 */
.modal-actions {
  display: flex;
  gap: 16rpx;
  margin-top: 32rpx;
}
.modal-btn {
  flex: 1;
  padding: 22rpx 0;
  border-radius: 14rpx;
  text-align: center;
  cursor: pointer;
  transition: opacity 0.15s;
}
.modal-btn:active { opacity: 0.7; }
.btn-cancel { background: #f0f2f5; }
.btn-confirm { background: #1a1a2e; }
.btn-disabled { opacity: 0.4; pointer-events: none; }
.btn-text { font-size: 28rpx; font-weight: 600; }
.cancel-text { color: #8c8c9a; }
.confirm-text { color: #ffffff; }

@media (min-width: 750px) {
  .modal-card { padding: 32px 28px 24px; border-radius: 16px; }
  .modal-icon { font-size: 32px; }
  .modal-title { font-size: 18px; }
  .modal-desc { font-size: 13px; }
  .field-label { font-size: 13px; margin-bottom: 8px; }
  .search-wrap { padding: 12px 16px; border-radius: 10px; }
  .search-icon { font-size: 15px; margin-right: 8px; }
  .search-input { font-size: 14px; }
  .search-results { max-height: 200px; margin-top: 8px; border-radius: 8px; }
  .search-result-item { padding: 10px 14px; }
  .result-name { font-size: 14px; }
  .result-code { font-size: 12px; }
  .result-check { font-size: 15px; }
  .search-status-text { font-size: 13px; }
  .selected-stock { margin-top: 10px; padding: 10px 14px; border-radius: 8px; }
  .selected-name { font-size: 15px; }
  .selected-code { font-size: 12px; }
  .reason-input { min-height: 80px; padding: 12px 16px; font-size: 14px; border-radius: 8px; }
  .confirm-summary { padding: 16px; margin-bottom: 16px; border-radius: 8px; }
  .confirm-label { font-size: 12px; }
  .confirm-name { font-size: 18px; }
  .confirm-code { font-size: 13px; }
  .confirm-reason { font-size: 13px; }
  .pwd-wrap { padding: 12px 16px; border-radius: 10px; }
  .pwd-input { font-size: 15px; }
  .error-text { font-size: 12px; }
  .modal-actions { gap: 10px; margin-top: 20px; }
  .modal-btn { padding: 12px 0; border-radius: 10px; }
  .btn-text { font-size: 15px; }
}
</style>
