/**
 * API 配置与请求封装
 */

// 后端 API 基础地址 — 根据环境自动切换
// 生产环境用空字符串（相对路径，由 Nginx 反代到后端）
// 开发环境用 localhost:8000
const BASE_URL = import.meta.env.VITE_API_BASE_URL || (import.meta.env.MODE === 'production' ? '' : 'http://localhost:8000')

// API Key — 通过环境变量注入
const API_KEY = import.meta.env.VITE_API_KEY || ''

/**
 * 通用请求封装
 */
function request(url, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {})
  }
  // 自动注入 API Key
  if (API_KEY) {
    headers['X-API-Key'] = API_KEY
  }

  return new Promise((resolve, reject) => {
    uni.request({
      url: `${BASE_URL}${url}`,
      method: options.method || 'GET',
      data: options.data || {},
      header: headers,
      timeout: 15000,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          // 自动解包 APIResponse / PaginatedResponse 格式
          // 如果返回 {code, message, data, ...} 结构，取 data 字段作为实际数据
          // 同时将 total/limit/offset 等分页字段保留到解包后的对象上
          const body = res.data
          if (body && typeof body === 'object' && 'code' in body && 'data' in body) {
            if (body.code !== 0) {
              reject(new Error(body.message || `API Error code=${body.code}`))
              return
            }
            // PaginatedResponse: 将分页信息附加到 data 包装中
            if ('total' in body && Array.isArray(body.data)) {
              resolve({
                items: body.data,
                total: body.total,
                limit: body.limit,
                offset: body.offset,
              })
              return
            }
            resolve(body.data)
            return
          }
          resolve(body)
        } else {
          reject(new Error(`HTTP ${res.statusCode}: ${JSON.stringify(res.data)}`))
        }
      },
      fail: (err) => {
        reject(new Error(err.errMsg || '网络请求失败'))
      }
    })
  })
}

// ── News API（首页使用）──

/**
 * 获取新闻列表
 */
export function fetchNews(params = {}) {
  const query = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
  return request(`/api/v1/news/${query ? '?' + query : ''}`)
}

/**
 * 搜索新闻
 */
export function searchNews(params = {}) {
  const query = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
  return request(`/api/v1/news/search${query ? '?' + query : ''}`)
}

/**
 * 搜索建议（自动补全）
 */
export function fetchSearchSuggestions(q) {
  return request(`/api/v1/news/search/suggest?q=${encodeURIComponent(q)}`)
}

/**
 * 热门话题
 */
export function fetchHotTopics() {
  return request(`/api/v1/news/search/hot`)
}

/**
 * 生成大模型提示词
 */
export function generatePrompt(params = {}) {
  const query = Object.entries(params)
    .filter(([, v]) => v !== undefined)
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
  return request(`/api/v1/bridge/generate_prompt${query ? '?' + query : ''}`)
}

// ── Reports API（每日复盘模块使用）──

/**
 * 获取 Reports 列表
 */
export function fetchReportsList(limit = 20, offset = 0) {
  return request(`/api/v1/reports/?limit=${limit}&offset=${offset}`)
}

/**
 * 获取单篇 Report 详情
 */
export function fetchReportDetail(id) {
  return request(`/api/v1/reports/${id}`)
}

// ── Digests API（新闻概览时间轴使用）──

/**
 * 获取新闻概览列表（按时间倒序）
 * @param {number} days 获取最近几天，默认 7
 */
export function fetchDigests(days = 7) {
  return request(`/api/v1/digests/?days=${days}`)
}

// ── Stocks API（RS Rating + VCP 排行榜使用）──

/**
 * 获取 RS Rating 排行榜
 */
export function fetchRSRating(params = {}) {
  const query = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
  return request(`/api/v1/stocks/rs_rating${query ? '?' + query : ''}`)
}

/**
 * 搜索股票（代码/名称/拼音首字母）
 */
export function searchStocks(params = {}) {
  const query = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
  return request(`/api/v1/stocks/search${query ? '?' + query : ''}`)
}

/**
 * 获取 VCP 策略白名单
 */
export function fetchVCPWatchlist(params = {}) {
  const query = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
  return request(`/api/v1/stocks/vcp_watchlist${query ? '?' + query : ''}`)
}

/**
 * 获取 VCP 白名单可用的行业和概念板块枚举值（用于筛选器）
 * @param {string} market 市场：CN=A股, US=美股
 */
export function fetchVCPFilters(market = 'CN') {
  return request(`/api/v1/stocks/vcp_watchlist/filters?market=${market}`)
}

/**
 * 获取价投策略白名单
 */
export function fetchValueWatchlist() {
  return request('/api/v1/stocks/value_watchlist')
}

/**
 * 获取右侧趋势策略白名单
 */
export function fetchTrendWatchlist(params = {}) {
  const query = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
  return request(`/api/v1/stocks/trend_watchlist${query ? '?' + query : ''}`)
}

/**
 * 获取右侧趋势白名单可用的行业和概念板块枚举值（用于筛选器）
 * @param {string} market 市场：CN=A股, US=美股
 */
export function fetchTrendFilters(market = 'CN') {
  return request(`/api/v1/stocks/trend_watchlist/filters?market=${market}`)
}

/**
 * 手动触发美股行情更新
 * @param {Object} params - {days, force}
 */
export function triggerUSQuoteUpdate(params = {}) {
  const query = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
  return request(`/api/v1/stocks/us/update_quotes${query ? '?' + query : ''}`, { method: 'POST' })
}

/**
 * Ticker 速览 — 查询指定标的是否在当日 VCP / 趋势白名单中
 * @param {string} code 股票代码（如 300750、NVDA、300750.SZ）
 */
export function tickerLookup(code) {
  return request(`/api/v1/stocks/ticker_lookup?code=${encodeURIComponent(code)}`)
}

// ── Catalyst API（催化剂标的）──

/**
 * 获取催化剂标的排行榜
 * @param {Object} params - {target_date, confirm_level, min_heat}
 */
export function fetchCatalystStocks(params = {}) {
  const query = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
  return request(`/api/v1/catalyst/stocks${query ? '?' + query : ''}`)
}

/**
 * 批量查询多只标的的催化剂命中状态
 * @param {string[]} tsCodes 股票代码数组
 */
export function batchCheckCatalyst(tsCodes) {
  if (!tsCodes || tsCodes.length === 0) return Promise.resolve({ date: null, items: {} })
  return request(`/api/v1/catalyst/batch_check?ts_codes=${encodeURIComponent(tsCodes.join(','))}`)
}

// ── Sandbox API（模拟仓）──

/**
 * 验证模拟仓访问密码
 */
export function verifySandboxAccess(password) {
  return request('/api/v1/sandbox/verify-access', {
    method: 'POST',
    data: { password },
  })
}

/**
 * 模拟仓概览（净值曲线 + 概览指标）
 */
export function fetchSandboxOverview(days = 90) {
  return request(`/api/v1/sandbox/overview?days=${days}`)
}

/**
 * 观察池列表
 */
export function fetchSandboxStocks(status = '', statusFilter = '', q = '', holdingOnly = false) {
  const params = []
  // statusFilter 用于按 watching/holding 筛选（替代旧的 discipline 参数）
  const effectiveStatus = statusFilter || status
  if (effectiveStatus) params.push(`status=${effectiveStatus}`)
  if (q) params.push(`q=${encodeURIComponent(q)}`)
  if (holdingOnly) params.push(`holding_only=true`)
  const qs = params.length ? `?${params.join('&')}` : ''
  return request(`/api/v1/sandbox/stocks${qs}`)
}

/**
 * 单只股票详情（推演 + 交易记录）
 */
export function fetchSandboxStockDetail(stockId) {
  return request(`/api/v1/sandbox/stocks/${stockId}`)
}

// ── Briefing API（每日研报使用）──

/**
 * 获取研报列表（按日期倒序）
 * @param {number} days 获取最近几天，默认 7
 */
export function fetchBriefings(days = 7) {
  return request(`/api/v1/briefings/?days=${days}`)
}

/**
 * 获取最新一条研报
 */
export function fetchLatestBriefing() {
  return request('/api/v1/briefings/latest')
}

/**
 * 获取单条研报详情
 * @param {number} id 研报 ID
 */
export function fetchBriefingDetail(id) {
  return request(`/api/v1/briefings/${id}`)
}

// ── Analytics API（用户行为上报）──

/**
 * 批量上报用户行为事件
 */
export function reportAnalyticsEvents(events) {
  return request('/api/v1/analytics/events', {
    method: 'POST',
    data: { events },
  })
}

// ── SEPA 模拟盘训练系统 API（A股/港股/美股 三市场独立账户）──

/** 拼接 query string */
function _qs(params = {}) {
  const q = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
  return q ? `?${q}` : ''
}

/** 写操作鉴权头 — 携带解锁时缓存的 SEPA 访问密码 */
function _sepaAuthHeader() {
  let pwd = ''
  try { pwd = uni.getStorageSync('sepa_pwd') || '' } catch (_) {}
  return pwd ? { 'X-Sandbox-Password': pwd } : {}
}

// 三市场账户概要（市场切换器）
export function fetchSepaMarkets() {
  return request('/api/v1/sepa/markets')
}

// 市场闸门
export function fetchSepaGate(market) {
  return request(`/api/v1/sepa/gate${_qs({ market })}`)
}
export function updateSepaGate(data) {
  return request('/api/v1/sepa/admin/gate', { method: 'PUT', data, headers: _sepaAuthHeader() })
}

// 股池 Watchlist
export function fetchSepaWatchlist(market, status = '') {
  return request(`/api/v1/sepa/watchlist${_qs({ market, status })}`)
}
export function fetchSepaWatchlistItem(id) {
  return request(`/api/v1/sepa/watchlist/${id}`)
}
export function addSepaWatchlist(data) {
  return request('/api/v1/sepa/admin/watchlist', { method: 'POST', data, headers: _sepaAuthHeader() })
}
export function updateSepaWatchlist(id, data) {
  return request(`/api/v1/sepa/admin/watchlist/${id}`, { method: 'PUT', data, headers: _sepaAuthHeader() })
}
export function deleteSepaWatchlist(id) {
  return request(`/api/v1/sepa/admin/watchlist/${id}`, { method: 'DELETE', headers: _sepaAuthHeader() })
}
// 填代码自动带出指标（现价/MA/RS/52周高低）
export function autofillSepaMetrics(market, symbol) {
  return request(`/api/v1/sepa/autofill${_qs({ market, symbol })}`)
}

// 账户总览 + 持仓
export function fetchSepaAccount(market) {
  return request(`/api/v1/sepa/account${_qs({ market })}`)
}
export function updateSepaAccount(data) {
  return request('/api/v1/sepa/admin/account', { method: 'PUT', data, headers: _sepaAuthHeader() })
}

// KPI 仪表盘
export function fetchSepaKpi(market, period = 'all') {
  return request(`/api/v1/sepa/kpi${_qs({ market, period })}`)
}

// 交易日志
export function fetchSepaTrades(market, filter = 'all') {
  return request(`/api/v1/sepa/trades${_qs({ market, filter })}`)
}
export function sepaTradesExportUrl(market) {
  return `${BASE_URL}/api/v1/sepa/trades/export${_qs({ market })}`
}

// 买点检查（不下单）
export function checkSepaBuy(data) {
  return request('/api/v1/sepa/check', { method: 'POST', data })
}

// 开仓（M7 纪律强制拦截）
export function openSepaTrade(data) {
  return request('/api/v1/sepa/admin/trades', { method: 'POST', data, headers: _sepaAuthHeader() })
}
// 平仓（强制标注是否守纪律）
export function closeSepaTrade(id, data) {
  return request(`/api/v1/sepa/admin/trades/${id}/close`, { method: 'POST', data, headers: _sepaAuthHeader() })
}
// 撤销交易
export function deleteSepaTrade(id) {
  return request(`/api/v1/sepa/admin/trades/${id}`, { method: 'DELETE', headers: _sepaAuthHeader() })
}
