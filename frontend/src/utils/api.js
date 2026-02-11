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

/**
 * 获取新闻列表（分页 + Hacker Gravity 排序）
 * 返回 { items, total, limit, offset, sort, gravity, max_age_hours }
 *
 * 排序模式 hot 使用 Hacker News 原版重力公式:
 *   rank = (points - 1) / (hours_elapsed + 2) ^ gravity
 * 其中 points = ai_score (AI 评分替代用户投票数)
 *
 * @param {Object} opts
 * @param {number}  opts.limit        - 每页条数 (默认 20)
 * @param {number}  opts.offset       - 偏移量
 * @param {number}  opts.min_score    - 最低 AI 评分 (默认 6)
 * @param {string}  opts.source       - 来源筛选
 * @param {string}  opts.sector       - 板块筛选
 * @param {string}  opts.sort         - 排序模式: hot(Hacker Gravity) | latest(最新) | score(评分)
 * @param {number}  opts.gravity      - 重力因子 (默认 1.8, 与 HN 一致, 仅 hot 模式)
 * @param {number}  opts.max_age_hours - 最大新闻年龄/小时 (默认 72)
 */
export function fetchNews({ limit = 20, offset = 0, min_score = 6, source, sector, sort = 'hot', gravity, max_age_hours } = {}) {
  const params = { limit, offset, min_score, sort }
  if (source) params.source = source
  if (sector) params.sector = sector
  if (gravity != null) params.gravity = gravity
  if (max_age_hours != null) params.max_age_hours = max_age_hours
  return request('/news/', { data: params })
}

/** 生成 Gemini Prompt */
export function generatePrompt({ sector, date, top_n = 10 } = {}) {
  const params = { top_n }
  if (sector) params.sector = sector
  if (date) params.date = date
  return request('/bridge/generate_prompt', { data: params })
}
