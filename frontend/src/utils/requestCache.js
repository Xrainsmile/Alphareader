// 跨组件实例存活的前端请求缓存（切换 tab / 路由不销毁）
//
// 解决 stocks 模块反复切 tab 时，左侧 VCP 白名单 + 右侧策略画像 & 市场适配
// 每次都重新发请求、反复转圈的问题。这些数据的计算都在日终（收盘后）完成，
// 盘中（甚至同一天内）反复拉取纯属浪费。
//
// 特性：
//  - 模块级 Map，组件销毁（v-if 卸载）不影响缓存，切回即命中。
//  - TTL 过期自动失效（按写入时间窗口）。
//  - 并发去重：同一 key 同时多次调用只发一次请求。
//  - cachePeek 同步读，命中时组件可零转圈直接填充。

const store = new Map() // key -> { value?, promise?, t }

export const CACHE_TTL = {
  SHORT: 5 * 60 * 1000, // 5min：白名单 / 策略概览 / 催化剂（日终计算，盘中不变）
  MID: 15 * 60 * 1000, // 15min
  LONG: 30 * 60 * 1000, // 30min：筛选器枚举（几乎不变）
}

// 同步读取未过期缓存值；未命中 / 过期 / 未完成返回 undefined
export function cachePeek(key, ttlMs) {
  const e = store.get(key)
  if (!e || e.value === undefined) return undefined
  if (ttlMs != null && Date.now() - e.t >= ttlMs) return undefined
  return e.value
}

// 读-写一体：命中未过期值则同步返回；否则执行 fetcher（并发去重）并缓存
export function cacheGet(key, ttlMs, fetcher) {
  const hit = cachePeek(key, ttlMs)
  if (hit !== undefined) return hit

  const e = store.get(key)
  if (e && e.promise) return e.promise // 进行中，复用同一次请求

  const promise = Promise.resolve()
    .then(() => fetcher())
    .then((v) => {
      store.set(key, { value: v, t: Date.now() })
      return v
    })
    .catch((err) => {
      store.delete(key) // 失败不污染缓存
      throw err
    })

  store.set(key, { promise, t: Date.now() })
  return promise
}

// 主动失效（如手动刷新场景）
export function cacheInvalidate(key) {
  if (key == null) store.clear()
  else store.delete(key)
}
