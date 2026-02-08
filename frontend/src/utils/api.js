/**
 * API 请求封装
 * 在 Docker 部署时通过 Nginx 反代 /api -> backend:8000
 */

const BASE_URL = '/api/v1'

function request(url, options = {}) {
  return new Promise((resolve, reject) => {
    uni.request({
      url: `${BASE_URL}${url}`,
      method: options.method || 'GET',
      data: options.data,
      header: {
        'Content-Type': 'application/json',
        ...options.header,
      },
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
        } else {
          reject(new Error(`HTTP ${res.statusCode}: ${JSON.stringify(res.data)}`))
        }
      },
      fail: (err) => {
        reject(new Error(err.errMsg || '网络请求失败'))
      },
    })
  })
}

/** 获取新闻列表 */
export function fetchNews({ limit = 30, min_score = 6, source, sector } = {}) {
  const params = { limit, min_score }
  if (source) params.source = source
  if (sector) params.sector = sector
  return request('/news/', { data: params })
}

/** 生成 Gemini Prompt */
export function generatePrompt({ sector, date, top_n = 10 } = {}) {
  const params = { top_n }
  if (sector) params.sector = sector
  if (date) params.date = date
  return request('/bridge/generate_prompt', { data: params })
}

/** 触发 Pipeline */
export function triggerPipeline() {
  return request('/news/pipeline/run', { method: 'POST' })
}

/** 查询 Pipeline 状态 */
export function getPipelineStatus() {
  return request('/news/pipeline/status')
}
