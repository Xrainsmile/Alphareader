/**
 * 简报导出为图片（digestExport.js）
 *
 * 把 Reports 页中某一期简报的卡片导出为 PNG 分享图：
 * 1. 克隆页面上的 .digest-card 节点（类样式随节点走，视觉与网页前端一致）；
 * 2. 挂载到离屏导出容器，底部追加品牌栏（Logo + 站点 + 二维码）；
 * 3. html2canvas 截图并触发浏览器下载。
 *
 * 仅 H5 可用（依赖 DOM / Canvas / 下载），其他端调用方应提前拦截。
 *
 * 注意：html2canvas/qrcode 用静态 import——uni 构建对动态 import() 的
 * chunk 路径处理有缺陷（运行时生成非法相对 specifier 导致加载失败）。
 */

import html2canvas from 'html2canvas'
import QRCode from 'qrcode'

const SITE_BASE = 'https://www.alphareader.site'

/** 生成「打开本期简报」的深链（与企微推送同格式：进入后自动定位该期） */
export function digestShareUrl(digestId) {
  return `${SITE_BASE}/#/pages/reports/index?id=${digestId}`
}

/** 当前运行环境是否支持导出（H5 浏览器） */
export function canExportImage() {
  return typeof document !== 'undefined' && typeof window !== 'undefined'
}

function _el(tag, className, text) {
  const node = document.createElement(tag)
  if (className) node.className = className
  if (text != null) node.textContent = text
  return node
}

/**
 * 导出指定简报为 PNG。
 * @param {object} item  简报列表项（需含 id / period_display / digest_date / period_label）
 * @returns {Promise<void>}
 */
export async function exportDigestImage(item) {
  if (!canExportImage()) {
    throw new Error('当前环境不支持导出，请使用浏览器打开')
  }
  // 1. 找到页面上的简报卡片并克隆
  const host = document.getElementById(`digest-${item.id}`)
  const card = host && host.querySelector('.digest-card')
  if (!card) throw new Error('未找到简报卡片，请稍后重试')

  const clone = card.cloneNode(true)
  // 图片里不需要交互入口与导出按钮自身
  clone.querySelectorAll('.dc-export, .dc-mk-foot').forEach((n) => n.remove())

  // 2. 离屏导出容器（html2canvas 要求元素真实参与布局，不能 display:none）
  const wrapper = _el('div', 'digest-export-wrapper')
  wrapper.appendChild(clone)

  // 3. 底部品牌栏：Logo + 名称/日期 + 二维码
  const footer = _el('div', 'digest-export-footer')

  const brand = _el('div', 'digest-export-brand')
  const logo = _el('img', 'digest-export-logo')
  logo.src = '/static/logo.png'
  logo.crossOrigin = 'anonymous'
  brand.appendChild(logo)
  const brandText = _el('div', 'digest-export-brand-text')
  brandText.appendChild(_el('div', 'digest-export-site', 'AlphaReader · 阶段简报'))
  brandText.appendChild(
    _el('div', 'digest-export-date', `${item.digest_date} ${item.period_display || ''}`)
  )
  brand.appendChild(brandText)

  const qrBox = _el('div', 'digest-export-qr')
  const qrImg = _el('img', 'digest-export-qr-img')
  qrImg.src = await QRCode.toDataURL(digestShareUrl(item.id), {
    width: 168,
    margin: 0,
    color: { dark: '#1f2329', light: '#ffffff' },
  })
  qrBox.appendChild(qrImg)
  qrBox.appendChild(_el('div', 'digest-export-qr-tip', '扫码查看本期'))

  footer.appendChild(brand)
  footer.appendChild(qrBox)
  wrapper.appendChild(footer)

  // 4. 内联样式（scoped 样式不作用于动态创建的离屏节点）
  _injectExportStyles()
  document.body.appendChild(wrapper)

  try {
    const canvas = await html2canvas(wrapper, {
      scale: 2, // 2x 保证手机端清晰度
      backgroundColor: '#f2f3f5',
      useCORS: true,
      logging: false,
    })
    const a = document.createElement('a')
    a.href = canvas.toDataURL('image/png')
    a.download = `AlphaReader_${item.digest_date}_${item.period_label || 'digest'}.png`
    document.body.appendChild(a)
    a.click()
    a.remove()
  } finally {
    wrapper.remove()
  }
}

let _stylesInjected = false
function _injectExportStyles() {
  if (_stylesInjected) return
  _stylesInjected = true
  const css = `
  .digest-export-wrapper {
    position: fixed; left: -10000px; top: 0;
    width: 750px; padding: 32px; box-sizing: border-box;
    background: #f2f3f5;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif;
  }
  .digest-export-wrapper .digest-card { margin: 0; }
  .digest-export-footer {
    display: flex; align-items: center; justify-content: space-between;
    margin-top: 20px; padding: 20px 24px;
    background: #ffffff; border-radius: 16px;
    border: 1px solid #eef0f2;
  }
  .digest-export-brand { display: flex; align-items: center; gap: 14px; }
  .digest-export-logo { width: 44px; height: 44px; border-radius: 10px; }
  .digest-export-brand-text { display: flex; flex-direction: column; gap: 4px; }
  .digest-export-site { font-size: 17px; font-weight: 700; color: #1f2329; }
  .digest-export-date { font-size: 13px; color: #9ca3af; }
  .digest-export-qr { display: flex; flex-direction: column; align-items: center; gap: 6px; }
  .digest-export-qr-img { width: 84px; height: 84px; }
  .digest-export-qr-tip { font-size: 12px; color: #9ca3af; }
  `
  const style = document.createElement('style')
  style.setAttribute('data-digest-export', '')
  style.textContent = css
  document.head.appendChild(style)
}
