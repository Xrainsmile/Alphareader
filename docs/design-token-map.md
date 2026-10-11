# AlphaReader 设计令牌映射表（全量令牌化项目）
# 生成时间：2026-10-11
# 用途：硬编码色值 -> 设计令牌 的替换对照，供批量替换脚本与人工核对使用

## 一、可安全替换（已有等价令牌，46.2%，73 处）
# 判定标准：App.vue 中已存在完全相同的色值定义，语义等价，替换后渲染无变化

#4285f4  ->  var(--color-brand)              # 品牌蓝，出现 15 次
#34c759  ->  var(--color-down)               # 绿（跌）
#8c8c9a  ->  var(--color-text-muted)         # 弱化文字
#1a1a2e  ->  var(--color-text-primary)       # 主文字
#ff3b30  ->  var(--color-up)                 # 红（涨）
#ff9500  ->  var(--color-warning)            # 警告橙
#2563eb  ->  var(--color-info-hover)         # 信息蓝 hover
#3b82f6  ->  var(--color-info)               # 信息蓝
#2e7d32  ->  var(--color-success-text)       # 成功文字
#6b7280  ->  var(--color-neutral)            # 中性灰
#3b78e7  ->  var(--color-brand-hover)
#007aff  ->  var(--color-brand-ios)
#1677ff  ->  var(--color-brand-alt)
#ef4444  ->  var(--color-up-alt)
#22c55e  ->  var(--color-down-alt)
#f59e0b  ->  var(--color-warning-alt)
#e8f0fe  ->  var(--color-bg-tag)             # 或 --color-bg-info-soft（同值，需按语境选）
#f5f5f7  ->  var(--color-bg-code)
#f5f6f8  ->  var(--color-bg-input)           # 或 --color-bg-active（同值，需按语境选）
#f5f7fa  ->  var(--color-bg-secondary)
#fafbfc  ->  var(--color-bg-hover)
#dcfce7  ->  var(--color-bg-success-light)
#e8f5e9  ->  var(--color-bg-success-soft)
#dbeafe  ->  var(--color-bg-info-light)
#eff6ff  ->  var(--color-bg-info-accent)
#f0f4ff  ->  var(--color-bg-info-blend)
#f3f4f6  ->  var(--color-bg-neutral-light)
#f5f5f5  ->  var(--color-bg-neutral-soft)
#f0f5ff  ->  var(--color-bg-brand-light)
#f0f0f5  ->  var(--color-bg-dropdown-hover)
#d0e0f8  ->  var(--color-bg-tag-hover)
#e8e8ed  ->  var(--color-border)
#f0f0f2  ->  var(--color-border-light)
#c0c0cc  ->  var(--color-border-hover)
#e0e0e6  ->  var(--color-border-divider)
#f2f2f5  ->  var(--color-border-subtle)
#d0d0d8  ->  var(--color-border-separator)
#3a3a4a  ->  var(--color-text-secondary)
#5a5a6e  ->  var(--color-text-tertiary)
#4a4a5a  ->  var(--color-text-body)
#b0b0be  ->  var(--color-text-placeholder)
#6b6b7b  ->  var(--color-text-hint)
#8e8e93  ->  var(--color-neutral-light)
#16a34a  ->  var(--color-success-dark)
#c62828  ->  var(--color-danger-dark)
#FFEBEE  ->  var(--color-bg-danger-light)
#fff3e0  ->  var(--color-bg-warning-light)
#e65100  ->  var(--color-warning-deep)
#FF9800  ->  var(--color-time-morning)
#F44336  ->  var(--color-time-midday)
#9C27B0  ->  var(--color-time-evening)
#3F51B5  ->  var(--color-time-night)
#FFF3E0  ->  var(--color-bg-time-morning)
#F3E5F5  ->  var(--color-bg-time-evening)
#E8EAF6  ->  var(--color-bg-time-night)
#f0f0f4  ->  var(--color-bg-active-press)    # 近似，需核对
#f8f8fa  ->  var(--color-bg-subtle)

## 二、需新建令牌（53.8%，85 处）
# 判定标准：App.vue 中无相同定义，属于令牌体系缺口，需定义后替换

# 纯色/基础（建议归入基础色）
#ffffff / #fff  ->  建议复用 --color-bg-card 或 --color-text-white（按语境）
#000 / #000000  ->  建议 --color-black（稀缺，仅阴影/遮罩用）

# 语义色变体（建议归入语义色，同类已有 up/down/warning 体系）
#eb4b4b  ->  --color-danger            # 红，4 次
#f5a623  ->  --color-warning-soft      # 橙黄，3 次
#30b86e  ->  --color-success           # 绿，3 次
#43a047  ->  --color-success-hover     # 深绿，2 次
#1e88e5  ->  --color-info-active       # 蓝，2 次
#1565c0  ->  --color-info-deep         # 深蓝文字，3 次
#3b78dc  ->  --color-brand-deep        # 品牌蓝变体，2 次

# 浅色底（建议归入状态背景）
#eef4ff  ->  --color-bg-brand-softer   # 5 次
#e3f2fd  ->  --color-bg-info-softer    # 3 次
#f2f2f7  ->  --color-bg-subtle-alt     # 3 次
#e5eaf1  ->  --color-bg-neutral-tint   # 2 次

# 边框/中性
#c0c4cc  ->  --color-border-strong     # 2 次
#555     ->  --color-text-dim          # 2 次

# 一次性装饰色（图表/标签用，建议保留硬编码或建 --chart-* 系列）
#a855f7 / #06b6d4 / #ec4899 / #8b5cf6   # 各 1 次，图表系列色

## 三、圆角令牌化（14 种散值 -> 刻度）
# 现有：--radius-sm(0.25rem=4px) / --radius-md(0.5rem=8px) / --radius-lg(0.625rem=10px) / --radius-pill(1.125rem=18px)
# rpx 分布：16rpx(26) 12rpx(24) 8rpx(17) 20rpx(16) 14rpx(13) 10rpx(8) 24rpx(6) 32rpx(5) 6rpx(4) 3rpx(4) 999rpx(2) 4rpx(2) 36rpx(1) 2rpx(1) 18rpx(1)
# 建议新增刻度令牌（不覆盖现有 rem 令牌）：
#   --radius-xs: 4rpx   --radius-sm2: 6rpx  --radius-md2: 8rpx
#   --radius-lg2: 12rpx --radius-xl: 16rpx  --radius-2xl: 20rpx
#   --radius-3xl: 24rpx --radius-4xl: 32rpx --radius-full: 999rpx
# 低频值 2/3/18/36rpx 建议就近收敛到刻度

## 四、风险与约束
# 1. 同值多令牌（如 #e8f0fe 对应 --color-bg-tag 与 --color-bg-info-soft）需人工按语境选，不可盲替
# 2. rgba() 半透明值不在本次统计范围（158 处仅统计 #hex），需单独处理
# 3. 渐变 linear-gradient 内色值需同步令牌化，见 App.vue 已定义的 --gradient-* 系列
# 4. rpx 与 px 单位不可混用：移动端档用 rpx 令牌，PC 档用 px 令牌
# 5. 替换后必须逐页截图回归，重点：色值反差、hover 态、图表系列色
