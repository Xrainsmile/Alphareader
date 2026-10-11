<script>
export default {
  onLaunch() {
    // AlphaReader launched
  },
}
</script>

<style>
/* ── 全局 CSS 变量（设计 Token） ── */
:root {
  /* 基础色 */
  --color-bg: #f0f2f5;
  --color-bg-primary: #ffffff;
  --color-bg-card: #ffffff;
  --color-bg-secondary: #f5f7fa;
  --color-bg-hover: #fafbfc;
  --color-bg-active: #f5f6f8;
  --color-bg-input: #f5f6f8;
  --color-bg-tag: #e8f0fe;
  --color-bg-code: #f5f5f7;

  /* 文字色 */
  --color-text-primary: #1a1a2e;
  --color-text-secondary: #3a3a4a;
  --color-text-tertiary: #5a5a6e;
  --color-text-body: #4a4a5a;
  --color-text-muted: #8c8c9a;
  --color-text-placeholder: #b0b0be;
  --color-text-hint: #6b6b7b;

  --color-text-white: #ffffff;

  /* 品牌色 */
  --color-brand: #4285f4;
  --color-brand-alt: #1677ff;
  --color-brand-light: rgba(66, 133, 244, 0.08);
  --color-brand-hover: #3b78e7;
  --color-brand-ios: #007aff;

  /* 语义色 */
  --color-up: #ff3b30;
  --color-up-alt: #ef4444;
  --color-down: #34c759;
  --color-down-alt: #22c55e;
  --color-warning: #ff9500;
  --color-warning-alt: #f59e0b;
  --color-info: #3b82f6;
  --color-info-hover: #2563eb;
  --color-success-dark: #16a34a;
  --color-success-text: #2e7d32;
  --color-danger-dark: #c62828;
  --color-neutral: #6b7280;
  --color-neutral-light: #8e8e93;

  /* 状态背景 */
  --color-bg-success-light: #dcfce7;
  --color-bg-success-soft: #e8f5e9;
  --color-bg-info-light: #dbeafe;
  --color-bg-info-soft: #e8f0fe;
  --color-bg-info-accent: #eff6ff;
  --color-bg-info-blend: #f0f4ff;
  --color-bg-danger-light: #FFEBEE;
  --color-bg-neutral-light: #f3f4f6;
  --color-bg-neutral-soft: #f5f5f5;
  --color-bg-brand-light: #f0f5ff;
  --color-bg-dropdown-hover: #f0f0f5;
  --color-bg-tag-hover: #d0e0f8;
  --color-bg-active-press: #e8e8f0;
  --color-bg-section: #f7f8fa;
  --color-bg-subtle: #f8f8fa;

  /* 边框 */
  --color-border: #e8e8ed;
  --color-border-light: #f0f0f2;
  --color-border-hover: #c0c0cc;
  --color-border-divider: #e0e0e6;
  --color-border-subtle: #f2f2f5;
  --color-border-separator: #d0d0d8;

  /* 渐变色 */
  --gradient-vcp-hot: linear-gradient(135deg, #ff3b30, #ff6b5a);
  --gradient-vcp-warm: linear-gradient(135deg, #ff9500, #ffb340);
  --gradient-vcp-normal: linear-gradient(135deg, #34c759, #5dd67a);
  --gradient-vcp-cool: linear-gradient(135deg, #8e8e93, #a8a8ae);
  /* ── 评分专用色阶（与情绪色解耦，按分数逐级增强视觉权重）──
     设计原则：<7 属低优先级，用中性灰并降低对比；≥7 才逐级加色加重。
     注意：此处的红仅表示「重要/值得关注」，不表示涨跌（涨跌用 --color-up/down）。*/
  --score-5-bg: #e8e8ee;
  --score-5-text: #9a9aa8;
  --score-4-bg: #eceef4;
  --score-4-text: #8a8a99;
  --score-3-bg: var(--color-brand-light);
  --score-3-text: var(--color-brand);
  --score-2-bg: rgba(255, 149, 0, 0.16);
  --score-2-text: #e8870e;
  --score-1-bg: var(--gradient-sentiment-strong-bull);
  --score-1-text: #ffffff;
  --gradient-sentiment-strong-bull: linear-gradient(135deg, #ff3b30, #e02b20);
  --gradient-sentiment-mild-bull: linear-gradient(135deg, #ff9500, #e8870e);
  --gradient-sentiment-caution: linear-gradient(135deg, #f0b429, #d4981e);
  --gradient-sentiment-mild-bear: linear-gradient(135deg, #34c759, #28a745);
  --gradient-sentiment-neutral: linear-gradient(135deg, #a0a0b0, #8c8c9a);
  --gradient-info-bar: linear-gradient(90deg, #3b82f6, #60a5fa);
  --gradient-info-bg: linear-gradient(180deg, #f0f7ff 0%, #ffffff 40%);
  --gradient-briefing-bg: linear-gradient(135deg, #f7f8fa 0%, #eef1f5 100%);

  /* 时段色 */
  --color-time-morning: #FF9800;
  --color-time-midday: #F44336;
  --color-time-evening: #9C27B0;
  --color-time-night: #3F51B5;
  --color-bg-time-morning: #FFF3E0;
  --color-bg-time-evening: #F3E5F5;
  --color-bg-time-night: #E8EAF6;

  /* 辅助色 */
  --color-bg-warning-light: #fff3e0;
  --color-warning-deep: #e65100;

  /* 语义色补充（全量令牌化新增，对应原散落硬编码） */
  --color-danger: #eb4b4b;
  --color-success: #30b86e;
  --color-success-hover: #43a047;
  --color-info-active: #1e88e5;
  --color-info-deep: #1565c0;
  --color-brand-deep: #3b78dc;
  --color-warning-soft: #f5a623;

  /* 状态背景补充 */
  --color-bg-brand-softer: #eef4ff;
  --color-bg-info-softer: #e3f2fd;
  --color-bg-subtle-alt: #f2f2f7;
  --color-bg-neutral-tint: #e5eaf1;

  /* 边框与文字补充 */
  --color-border-strong: #c0c4cc;
  --color-text-dim: #555555;
  --color-black: #000000;

  /* 字体 */
  --font-sans: 'PingFang SC', 'SF Pro Text', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
  --font-display: 'SF Pro Display', 'PingFang SC', -apple-system, sans-serif;
  --font-mono: 'SF Mono', 'Roboto Mono', 'Menlo', monospace;
  --font-numeric: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;

  /* 圆角 */
  --radius-sm: 0.25rem;
  --radius-md: 0.5rem;
  --radius-lg: 0.625rem;
  --radius-pill: 1.125rem;

  /* 圆角刻度（全量令牌化新增，独立命名避免覆盖上方 rem 令牌）
     rpx 系列用于移动端档，px 系列用于 PC 断点档 */
  --radius-r-xs: 4rpx;
  --radius-r-sm: 6rpx;
  --radius-r-md: 8rpx;
  --radius-r-lg: 12rpx;
  --radius-r-xl: 16rpx;
  --radius-r-2xl: 20rpx;
  --radius-r-3xl: 24rpx;
  --radius-r-4xl: 32rpx;
  --radius-r-full: 999rpx;
  --radius-p-xs: 3px;
  --radius-p-sm: 4px;
  --radius-p-md: 6px;
  --radius-p-lg: 8px;
  --radius-p-xl: 10px;
  --radius-p-2xl: 12px;
  --radius-p-3xl: 14px;
  --radius-p-4xl: 16px;
  --radius-p-5xl: 20px;
  --radius-p-full: 999px;

  /* 阴影 */
  --shadow-sm: 0 0.03125rem 0.25rem rgba(0, 0, 0, 0.04);
  --shadow-md: 0 0.0625rem 0.5rem rgba(0, 0, 0, 0.05);
  --shadow-lg: 0 0.25rem 1.25rem rgba(0, 0, 0, 0.12);

  /* 层级（z-index）规范：基础1 / 吸顶10 / 浮层100 / 模态1000 */
  --z-base: 1;
  --z-sticky: 10;
  --z-overlay: 100;
  --z-modal: 1000;

  /* 间距刻度（4 的倍数） */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-half: 2px;
  --space-7: 28px;
  --space-8: 32px;
  --space-10: 40px;

  /* 间距刻度 rpx 系列（移动端档，1px ≈ 2rpx） */
  --space-r-half: 4rpx;
  --space-r-1: 8rpx;
  --space-r-2: 16rpx;
  --space-r-3: 24rpx;
  --space-r-4: 32rpx;
  --space-r-5: 40rpx;
  --space-r-6: 48rpx;
}

/* 全局样式 — page 兼容小程序，body/uni-page-body 兼容 H5 */
page,
body,
uni-page-body {
  background-color: var(--color-bg);
  color: var(--color-text-primary);
  font-family: var(--font-sans);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* PC 端滚动条美化 */
@media screen and (min-width: 768px) {
  ::-webkit-scrollbar {
    width: 6px;
  }
  ::-webkit-scrollbar-track {
    background: transparent;
  }
  ::-webkit-scrollbar-thumb {
    background: rgba(0, 0, 0, 0.15);
    border-radius: 3px;
  }
  ::-webkit-scrollbar-thumb:hover {
    background: rgba(0, 0, 0, 0.25);
  }
  /* 鼠标选中文本样式 */
  ::selection {
    background: rgba(66, 133, 244, 0.2);
    color: inherit;
  }
}
</style>
