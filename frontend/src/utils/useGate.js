/**
 * 侧门（gate）共享状态：控制 Stocks / SEPA 对外隐藏与解锁。
 *
 * 默认对外隐藏 Stocks / SEPA 入口；在 Reports 旁连点 3 次「!」按钮，
 * 输入 Stocks 自身密码通过 verify-access 后，将 gate_open + 两套私密令牌
 * 一并写入 uni storage，Stocks 与 SEPA 入口同时显现。
 *
 * 使用模块级单例 ref，保证 PcSidebar / Reports 页 / 各子页读到的 isOpen 同步。
 */

import { ref } from 'vue'

const STORAGE_KEY = 'gate_open'

// 模块单例：所有 importer 共享同一 ref
const isOpen = ref(false)
try {
  isOpen.value = uni.getStorageSync(STORAGE_KEY) === 'true'
} catch (_) {}

/**
 * 解锁：写入 gate_open，并顺带把 Stocks / SEPA 的私密令牌一并缓存，
 * 免去各自再验一次密码。
 * @param {{ token?: string }} opts verify-access 返回的 7 天令牌
 */
function openGate({ token } = {}) {
  try {
    uni.setStorageSync(STORAGE_KEY, 'true')
    if (token) {
      uni.setStorageSync('sb_unlocked', 'true')
      uni.setStorageSync('sb_token', token)
      uni.setStorageSync('sepa_unlocked', 'true')
      uni.setStorageSync('sepa_token', token)
    }
  } catch (_) {}
  isOpen.value = true
}

/** 从 storage 重新同步（例如页面冷启动）*/
function checkGate() {
  try {
    isOpen.value = uni.getStorageSync(STORAGE_KEY) === 'true'
  } catch (_) {}
  return isOpen.value
}

export function useGate() {
  return { isOpen, openGate, checkGate }
}
