/**
 * Markdown 工具函数
 * - parseFrontMatter: 手写轻量 Front Matter 解析（替代 gray-matter，避免 Node 依赖）
 * - renderMarkdown: 使用 marked 将 Markdown 正文转为 HTML
 */
import { marked } from 'marked'

// 配置 marked
marked.setOptions({
  breaks: true,
  gfm: true
})

/**
 * 解析 Front Matter + 正文
 * @param {string} raw - 原始 .md 字符串（含 --- 元数据块）
 * @returns {{ meta: Object, content: string }}
 */
export function parseFrontMatter(raw) {
  const str = raw.trim()
  const meta = {}

  // 匹配 --- ... --- 块
  const match = str.match(/^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)$/)
  if (!match) {
    return { meta, content: str }
  }

  const yamlBlock = match[1]
  const content = match[2]

  // 逐行解析 key: value
  yamlBlock.split('\n').forEach(line => {
    const idx = line.indexOf(':')
    if (idx === -1) return
    const key = line.slice(0, idx).trim()
    let value = line.slice(idx + 1).trim()
    // 去除可能的引号包裹
    if ((value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1)
    }
    meta[key] = value
  })

  return { meta, content }
}

/**
 * Markdown 正文 → HTML
 * @param {string} mdContent - 纯 Markdown 正文（不含 Front Matter）
 * @returns {string} HTML 字符串
 */
export function renderMarkdown(mdContent) {
  return marked.parse(mdContent || '')
}

/**
 * 一次性完成：解析元数据 + 渲染 HTML
 * @param {string} raw - 原始 .md 字符串
 * @returns {{ meta: Object, html: string }}
 */
export function parseAndRender(raw) {
  const { meta, content } = parseFrontMatter(raw)
  const html = renderMarkdown(content)
  return { meta, html }
}
