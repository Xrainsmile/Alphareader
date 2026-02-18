/**
 * API 配置与请求封装
 */

// 后端 API 基础地址 — 根据环境自动切换
// 生产环境用空字符串（相对路径，由 Nginx 反代到后端）
// 开发环境用 localhost:8000
const BASE_URL = import.meta.env.VITE_API_BASE_URL || (import.meta.env.MODE === 'production' ? '' : 'http://localhost:8000')

/**
 * 通用请求封装
 */
function request(url, options = {}) {
  return new Promise((resolve, reject) => {
    uni.request({
      url: `${BASE_URL}${url}`,
      method: options.method || 'GET',
      data: options.data || {},
      header: {
        'Content-Type': 'application/json',
        ...(options.headers || {})
      },
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
