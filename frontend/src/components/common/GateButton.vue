<template>
  <!-- 未解锁才显示「!」入口；解锁后由导航（侧栏 / 页面入口）接管 -->
  <view v-if="!isOpen" class="gate-wrap">
    <view
      class="gate-btn"
      :class="{ 'gate-wobble': wobble }"
      hover-class="gate-hover"
      @click="onGateClick"
    >
      <text class="gate-mark">!</text>
    </view>

    <!-- 复用模拟仓密码弹窗（密码即 Stocks 自身密码）-->
    <SandboxPasswordModal
      :visible="modalVisible"
      :password="pwd"
      :error="pwdError"
      @update:visible="onModalVisible"
      @update:password="pwd = $event"
      @confirm="onConfirm"
    />
  </view>
</template>

<script setup>
import { ref } from 'vue'
import SandboxPasswordModal from '@/components/stocks/SandboxPasswordModal.vue'
import { verifySandboxAccess } from '@/utils/api'
import { useGate } from '@/utils/useGate'

const { isOpen, openGate } = useGate()

const CLICK_WINDOW_MS = 1500 // 两次点击间隔超过此值则重新计数
const REQUIRED_CLICKS = 3

const clickCount = ref(0)
const lastClick = ref(0)
const wobble = ref(false)
const modalVisible = ref(false)
const pwd = ref('')
const pwdError = ref(false)

function triggerWobble() {
  // 先移除再添加 class，重启 CSS 动画（跨端安全，不用 rAF）
  wobble.value = false
  setTimeout(() => { wobble.value = true }, 30)
  setTimeout(() => { wobble.value = false }, 630)
}

function onGateClick() {
  const now = Date.now()
  if (now - lastClick.value > CLICK_WINDOW_MS) clickCount.value = 0
  lastClick.value = now
  clickCount.value += 1
  triggerWobble()
  if (clickCount.value >= REQUIRED_CLICKS) {
    clickCount.value = 0
    openModal()
  }
}

function openModal() {
  pwd.value = ''
  pwdError.value = false
  modalVisible.value = true
}

function onModalVisible(v) {
  modalVisible.value = v
}

async function onConfirm() {
  if (!pwd.value) {
    pwdError.value = true
    return
  }
  pwdError.value = false
  try {
    const res = await verifySandboxAccess(pwd.value)
    const token = res && res.token ? res.token : ''
    openGate({ token })
    modalVisible.value = false
    pwd.value = ''
    uni.showToast({ title: '已解锁 Stocks / SEPA', icon: 'none' })
  } catch (_) {
    pwdError.value = true
  }
}
</script>

<style scoped>
.gate-wrap {
  display: inline-flex;
  align-items: center;
}

/* ── 圆形「!」按钮 ── */
.gate-btn {
  width: 40rpx;
  height: 40rpx;
  border-radius: 50%;
  border: 2rpx solid var(--color-brand, #4285f4);
  background: var(--color-bg-brand-light, #eef4ff);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  /* 待机轻微呼吸，提示可点击 */
  animation: gatePulse 2.2s ease-in-out infinite;
}
.gate-hover {
  opacity: 0.8;
}
.gate-mark {
  font-size: 28rpx;
  font-weight: 800;
  color: var(--color-brand, #4285f4);
  line-height: 1;
  transform: translateY(-1rpx);
}

/* 点击：俏皮的左右摇摆 + 旋转（重启式动画）*/
.gate-wobble {
  animation: gateWobble 0.6s ease;
}

@keyframes gatePulse {
  0%, 100% {
    transform: scale(1);
    box-shadow: 0 0 0 0 rgba(66, 133, 244, 0);
  }
  50% {
    transform: scale(1.1);
    box-shadow: 0 0 0 8rpx rgba(66, 133, 244, 0.18);
  }
}

@keyframes gateWobble {
  0%   { transform: rotate(0deg) translateX(0); }
  15%  { transform: rotate(-16deg) translateX(-3rpx); }
  30%  { transform: rotate(13deg) translateX(3rpx); }
  45%  { transform: rotate(-9deg) translateX(-2rpx); }
  60%  { transform: rotate(6deg) translateX(2rpx); }
  75%  { transform: rotate(-3deg); }
  100% { transform: rotate(0deg) translateX(0); }
}

/* 桌面端（侧栏内）放大一点更醒目 */
@media screen and (min-width: 768px) {
  .gate-btn {
    width: 24px;
    height: 24px;
  }
  .gate-mark {
    font-size: 16px;
  }
  @keyframes gatePulse {
    0%, 100% { transform: scale(1); box-shadow: 0 0 0 0 rgba(66,133,244,0); }
    50% { transform: scale(1.12); box-shadow: 0 0 0 5px rgba(66,133,244,0.18); }
  }
  @keyframes gateWobble {
    0%   { transform: rotate(0deg) translateX(0); }
    15%  { transform: rotate(-16deg) translateX(-2px); }
    30%  { transform: rotate(13deg) translateX(2px); }
    45%  { transform: rotate(-9deg) translateX(-1px); }
    60%  { transform: rotate(6deg) translateX(1px); }
    75%  { transform: rotate(-3deg); }
    100% { transform: rotate(0deg) translateX(0); }
  }
}
</style>
