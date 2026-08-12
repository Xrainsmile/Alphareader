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
  // 图片专用排版皮肤：覆盖克隆节点继承的网页样式（网页为屏幕阅读优化，
  // 分享图需要更大的字号行距与更清晰的视觉层次）。选择器以
  // .digest-export-wrapper 开头提升优先级，与设备无关、输出恒定。
  // 字号体系按手机物理显示反推：画布 680px 在 390px 手机屏上缩放比 0.574，
  // 正文 22px → 物理 ~12.6px（接近 App 正文标准），不再费眼。
  const css = `
  .digest-export-wrapper {
    position: fixed; left: -10000px; top: 0;
    width: 680px; padding: 28px; box-sizing: border-box;
    background: #eef1f5;
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif;
  }

  /* ── 主卡片：白卡 + 顶部品牌渐变条 ── */
  .digest-export-wrapper .digest-card {
    margin: 0; padding: 0 40px 36px; border: none; border-radius: 20px;
    background: #ffffff; box-shadow: 0 2px 14px rgba(15, 23, 42, 0.06);
    overflow: hidden;
  }
  .digest-export-wrapper .digest-card::before {
    content: ''; display: block; height: 8px;
    margin: 0 -40px 30px;
    background: linear-gradient(90deg, #4285f4, #1677ff);
  }

  /* ── 头部：大标题 + 时间范围 + 统计胶囊 ── */
  .digest-export-wrapper .dc-head {
    flex-direction: column; align-items: flex-start; gap: 10px;
  }
  .digest-export-wrapper .dc-title {
    font-size: 46px; font-weight: 800; color: #111827; letter-spacing: 1px;
  }
  .digest-export-wrapper .dc-range { font-size: 18px; color: #9ca3af; }
  .digest-export-wrapper .dc-stats { margin-top: 12px; gap: 10px; }
  .digest-export-wrapper .dc-stat {
    font-size: 16px; font-weight: 600; color: #1677ff;
    background: rgba(66, 133, 244, 0.08); border-radius: 999px;
    padding: 6px 16px;
  }
  .digest-export-wrapper .dc-sep { display: none; }

  /* ── 区块标题：品牌色左条，区块间距拉开 ── */
  .digest-export-wrapper .dc-section { margin-top: 40px; }
  .digest-export-wrapper .dc-section-title {
    display: block; font-size: 24px; font-weight: 700; color: #111827;
    line-height: 1.3; padding-left: 16px; border-left: 6px solid #4285f4;
    margin-bottom: 18px;
  }

  /* ── 时段概览：浅灰底信息块 ── */
  .digest-export-wrapper .dc-overview {
    background: #f8fafc; border-radius: 16px; padding: 22px 24px;
  }
  .digest-export-wrapper .dc-overview-text {
    font-size: 22px; line-height: 1.85; color: #374151;
  }
  .digest-export-wrapper .dc-change { margin-top: 14px; }
  .digest-export-wrapper .dc-change-label { font-size: 15px; padding: 3px 12px; }
  .digest-export-wrapper .dc-change-text {
    font-size: 22px; line-height: 1.85; color: #374151;
  }

  /* ── 核心变化 ── */
  .digest-export-wrapper .dc-core-item { margin-top: 16px; }
  .digest-export-wrapper .dc-core-dot { color: #4285f4; font-size: 24px; }
  .digest-export-wrapper .dc-core-text {
    font-size: 22px; font-weight: 600; color: #1f2937; line-height: 1.65;
  }
  .digest-export-wrapper .dc-core-summary {
    font-size: 20px; color: #6b7280; line-height: 1.75; margin-top: 6px;
  }

  /* ── 必须知道：浅灰子卡片 + 品牌色编号 ── */
  .digest-export-wrapper .dc-mk {
    background: #f8fafc; border: none; border-radius: 16px;
    padding: 20px 22px; margin-top: 14px;
  }
  .digest-export-wrapper .dc-mk-rank {
    font-size: 26px; font-weight: 800; color: #4285f4; min-width: 44px;
    line-height: 1.5;
  }
  .digest-export-wrapper .dc-mk-title {
    font-size: 23px; font-weight: 700; color: #111827; line-height: 1.55;
  }
  .digest-export-wrapper .dc-conf {
    border-radius: 999px; padding: 3px 12px; font-size: 14px; font-weight: 600;
  }
  .digest-export-wrapper .dc-mk-change {
    font-size: 21px; color: #4b5563; line-height: 1.8; margin-top: 10px;
  }
  .digest-export-wrapper .dc-mk-impact,
  .digest-export-wrapper .dc-mk-watch {
    font-size: 18px; color: #6b7280; line-height: 1.75; margin-top: 8px;
  }

  /* ── 值得留意 / 持续关注 ── */
  .digest-export-wrapper .dc-watch { margin-top: 12px; }
  .digest-export-wrapper .dc-watch-bullet { color: #c3cad3; }
  .digest-export-wrapper .dc-watch-text {
    font-size: 20px; color: #4b5563; line-height: 1.75;
  }
  .digest-export-wrapper .dc-watch-note { color: #9ca3af; }

  /* ── 接下来关注 ── */
  .digest-export-wrapper .dc-upcoming { margin-top: 12px; }
  .digest-export-wrapper .dc-upcoming-time {
    font-size: 15px; color: #1677ff; background: rgba(66, 133, 244, 0.08);
    border-radius: 8px; padding: 3px 10px; margin-right: 10px;
  }
  .digest-export-wrapper .dc-upcoming-text {
    font-size: 20px; color: #4b5563; line-height: 1.75;
  }

  /* ── 底部品牌栏 ── */
  .digest-export-footer {
    display: flex; align-items: center; justify-content: space-between;
    margin-top: 22px; padding: 26px 30px;
    background: #ffffff; border-radius: 20px; border: none;
    box-shadow: 0 2px 14px rgba(15, 23, 42, 0.06);
  }
  .digest-export-brand { display: flex; align-items: center; gap: 18px; }
  .digest-export-logo { width: 54px; height: 54px; border-radius: 13px; }
  .digest-export-brand-text { display: flex; flex-direction: column; gap: 6px; }
  .digest-export-site { font-size: 23px; font-weight: 800; color: #111827; letter-spacing: 0.5px; }
  .digest-export-date { font-size: 16px; color: #9ca3af; }
  .digest-export-qr { display: flex; flex-direction: column; align-items: center; gap: 10px; }
  .digest-export-qr-img { width: 104px; height: 104px; }
  .digest-export-qr-tip { font-size: 15px; color: #9ca3af; }
  `
  const style = document.createElement('style')
  style.setAttribute('data-digest-export', '')
  style.textContent = css
  document.head.appendChild(style)
}
