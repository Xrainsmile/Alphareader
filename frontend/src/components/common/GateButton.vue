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

/* ── 圆形「!」按钮（默认静态，仅点击时触发摇摆）── */
.gate-btn {
  width: 40rpx;
  height: 40rpx;
  border-radius: 50%;
  border: 2rpx solid var(--color-text-hint, #c0c4cc);
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: border-color 0.2s, background-color 0.2s, color 0.2s;
}
.gate-btn:hover,
.gate-hover {
  border-color: var(--color-brand, #4285f4);
  background: var(--color-bg-brand-light, #eef4ff);
}
.gate-mark {
  font-size: 28rpx;
  font-weight: 800;
  color: var(--color-text-hint, #c0c4cc);
  line-height: 1;
  transition: color 0.2s;
}
.gate-btn:hover .gate-mark,
.gate-hover .gate-mark {
  color: var(--color-brand, #4285f4);
}

/* 点击：俏皮的左右摇摆（重启式动画）*/
.gate-wobble {
  animation: gateWobble 0.6s ease;
  border-color: var(--color-brand, #4285f4);
  background: var(--color-bg-brand-light, #eef4ff);
}
.gate-wobble .gate-mark {
  color: var(--color-brand, #4285f4);
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
