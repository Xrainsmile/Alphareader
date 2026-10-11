/**
 * 导航框架统一管理（桌面端去重）
 *
 * 背景：uni-app 的 tabBar 是全局原生配置，桌面端无法用 CSS 隐藏，
 * 必须在页面生命周期里调用 uni.hideTabBar()。
 * 而桌面端已有 PcSidebar 左侧导航，两者同时出现 = 重复导航。
 *
 * 策略：
 *   ≥768px（桌面）→ 隐藏原生 tabBar，只保留 PcSidebar
 *   <768px（移动）→ 显示原生 tabBar，PcSidebar 本身 display:none
 */
import { onShow, onUnload } from '@dcloudio/uni-app'
import { onMounted, onBeforeUnmount } from 'vue'

const DESKTOP_BP = 768

export function isDesktop() {
  // #ifdef H5
  return typeof window !== 'undefined' && window.innerWidth >= DESKTOP_BP
  // #endif
  // #ifndef H5
  return false
  // #endif
}

function syncTabBar() {
  // #ifdef H5
  try {
    if (isDesktop()) uni.hideTabBar({ animation: false })
    else uni.showTabBar({ animation: false })
  } catch (e) {
    // 非 tabBar 页面调用会抛错，静默忽略
  }
  // #endif
}

/**
 * 在页面 setup 中调用，自动完成：
 *   1. 挂载/显示时按视口宽度同步 tabBar 显隐
 *   2. 监听 resize，跨断点时自动切换（避免用户缩放窗口后导航重复）
 *   3. 卸载时移除监听
 */
export function usePcNavFrame() {
  let handler = null

  const bind = () => {
    // #ifdef H5
    if (typeof window === 'undefined') return
    handler = () => syncTabBar()
    window.addEventListener('resize', handler)
    // #endif
  }

  const unbind = () => {
    // #ifdef H5
    if (handler && typeof window !== 'undefined') {
      window.removeEventListener('resize', handler)
      handler = null
    }
    // #endif
  }

  onMounted(() => {
    syncTabBar()
    bind()
  })

  onShow(() => {
    syncTabBar()
  })

  onBeforeUnmount(unbind)
  onUnload(unbind)
}
