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
          resolve(res.data)
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

// ── Stocks API（RS Rating 排行榜使用）──

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

// ── Sandbox API（模拟仓）──

/**
 * 模拟仓概览（净值曲线 + 概览指标）
 */
export function fetchSandboxOverview(days = 90) {
  return request(`/api/v1/sandbox/overview?days=${days}`)
}

/**
 * 观察池列表
 */
export function fetchSandboxStocks(status = '', discipline = '', q = '', holdingOnly = false) {
  const params = []
  if (status) params.push(`status=${status}`)
  if (discipline) params.push(`discipline=${discipline}`)
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
