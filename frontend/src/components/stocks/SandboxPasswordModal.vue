<template>
  <view v-if="visible" class="pwd-overlay" @click.self="$emit('update:visible', false)">
    <view class="pwd-card">
      <view class="pwd-header">
        <text class="pwd-icon">🔒</text>
        <text class="pwd-title">访问验证</text>
        <text class="pwd-desc">模拟仓为私密内容，请输入访问密码</text>
      </view>
      <view class="pwd-input-wrap" :class="{ 'pwd-input-error': error }">
        <input
          class="pwd-input"
          type="text"
          :password="true"
          placeholder="请输入密码"
          :value="password"
          :focus="visible"
          @input="$emit('update:password', $event.detail.value)"
          @confirm="$emit('confirm')"
        />
      </view>
      <text v-if="error" class="pwd-error-text">密码错误，请重试</text>
      <view class="pwd-actions">
        <view class="pwd-btn pwd-btn-cancel" @click="$emit('update:visible', false)">
          <text class="pwd-btn-text cancel-text">取消</text>
        </view>
        <view class="pwd-btn pwd-btn-confirm" @click="$emit('confirm')">
          <text class="pwd-btn-text confirm-text">确认</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script setup>
defineProps({
  visible: { type: Boolean, required: true },
  password: { type: String, required: true },
  error: { type: Boolean, default: false },
})

defineEmits(['update:visible', 'update:password', 'confirm'])
</script>

<style scoped>
.pwd-overlay {
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

.pwd-card {
  width: 600rpx;
  max-width: 320px;
  background: var(--color-bg-card);
  border-radius: 24rpx;
  padding: 48rpx 40rpx 36rpx;
  box-shadow: 0 16rpx 48rpx rgba(0, 0, 0, 0.12);
  animation: slideUp 0.25s ease;
}
@keyframes slideUp { from { transform: translateY(40rpx); opacity: 0; } to { transform: translateY(0); opacity: 1; } }

.pwd-header {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 36rpx;
}
.pwd-icon {
  font-size: 48rpx;
  margin-bottom: 16rpx;
}
.pwd-title {
  font-size: 34rpx;
  font-weight: 700;
  color: var(--color-text-primary);
  letter-spacing: 1rpx;
  font-family: var(--font-display);
}
.pwd-desc {
  font-size: 24rpx;
  color: var(--color-text-muted);
  margin-top: 10rpx;
  text-align: center;
  line-height: 1.5;
}

.pwd-input-wrap {
  background: var(--color-bg-active);
  border-radius: 16rpx;
  padding: 24rpx 28rpx;
  border: 2rpx solid var(--color-border);
  transition: border-color 0.2s, box-shadow 0.2s;
}
.pwd-input-wrap:focus-within {
  border-color: var(--color-text-primary);
  box-shadow: 0 2rpx 12rpx rgba(26, 26, 46, 0.1);
}
.pwd-input-error {
  border-color: var(--color-up) !important;
  box-shadow: 0 2rpx 12rpx rgba(255, 59, 48, 0.15) !important;
  animation: shake 0.3s ease;
}
@keyframes shake {
  0%, 100% { transform: translateX(0); }
  25% { transform: translateX(-8rpx); }
  75% { transform: translateX(8rpx); }
}

.pwd-input {
  width: 100%;
  font-size: 30rpx;
  color: var(--color-text-primary);
  background: transparent;
  border: none;
  outline: none;
  letter-spacing: 4rpx;
}

.pwd-error-text {
  display: block;
  font-size: 22rpx;
  color: var(--color-up);
  margin-top: 12rpx;
  text-align: center;
}

.pwd-actions {
  display: flex;
  gap: 20rpx;
  margin-top: 36rpx;
}
.pwd-btn {
  flex: 1;
  padding: 22rpx 0;
  border-radius: 14rpx;
  text-align: center;
  cursor: pointer;
  transition: opacity 0.15s;
}
.pwd-btn:active { opacity: 0.7; }

.pwd-btn-cancel {
  background: var(--color-bg);
}
.pwd-btn-confirm {
  background: var(--color-text-primary);
}
.pwd-btn-text {
  font-size: 28rpx;
  font-weight: 600;
}
.cancel-text { color: var(--color-text-muted); }
.confirm-text { color: var(--color-text-white); }

@media (min-width: 750px) {
  .pwd-card { padding: 36px 32px 28px; border-radius: 16px; }
  .pwd-icon { font-size: 32px; }
  .pwd-title { font-size: 18px; }
  .pwd-desc { font-size: 13px; }
  .pwd-input-wrap { padding: 12px 16px; border-radius: 10px; }
  .pwd-input { font-size: 16px; }
  .pwd-error-text { font-size: 12px; }
  .pwd-actions { gap: 12px; margin-top: 24px; }
  .pwd-btn { padding: 12px 0; border-radius: 10px; }
  .pwd-btn-text { font-size: 15px; }
}
</style>
