
## 前端标准化组件规范

### 搜索栏组件 (Capsule Search Bar)
项目统一使用胶囊圆角搜索栏风格，参考实现位于 `frontend/src/pages/stocks/index.vue` 的 VCP 筛选器区域。新增搜索功能时 **必须复用** 以下 CSS 类名体系，禁止另起一套样式。

**HTML 结构模板：**
```html
<view class="vcp-filters">
  <view class="vcp-search-section">
    <view class="vcp-search-bar" :class="{ 'vcp-search-bar-focus': focused }">
      <view class="vcp-search-input-wrap">
        <text class="vcp-search-icon">🔍</text>
        <input class="vcp-search-input" placeholder="搜索..." />
        <!-- 可选：右侧已选数量角标 -->
        <text class="vcp-search-badge">N</text>
        <!-- 可选：清除按钮 -->
        <view class="vcp-search-clear"><text class="vcp-search-clear-icon">×</text></view>
      </view>
    </view>
    <!-- 可选：浮动下拉列表 -->
    <view class="vcp-dropdown">
      <scroll-view scroll-y class="vcp-dropdown-scroll">
        <view class="vcp-dropdown-item">...</view>
      </scroll-view>
    </view>
    <!-- 可选：已选标签 -->
    <view class="vcp-tags"><text class="vcp-tag">标签 ✕</text></view>
  </view>
</view>
```

**核心 CSS 类名速查：**
| 类名 | 用途 |
|---|---|
| `.vcp-filters` | 搜索区容器，提供间距与 z-index 层叠上下文 |
| `.vcp-search-section` | 单个搜索栏区块（含下拉与标签） |
| `.vcp-search-bar` | 搜索栏 flex 行 |
| `.vcp-search-bar-focus` | 焦点态修饰（蓝色边框+阴影） |
| `.vcp-search-input-wrap` | 胶囊圆角输入框容器（白底、36rpx圆角、border） |
| `.vcp-search-icon` | 搜索图标 🔍 |
| `.vcp-search-input` | 输入框本体 |
| `.vcp-search-badge` | 右侧蓝色数量角标 |
| `.vcp-search-clear` / `.vcp-search-clear-icon` | 清除按钮 |
| `.vcp-dropdown` | 浮动下拉弹出层（absolute, z-index:100） |
| `.vcp-dropdown-item` / `.vcp-dropdown-item-active` | 下拉选项 |
| `.vcp-tags` / `.vcp-tag` | 已选标签条 |
| `.vcp-overlay` | 透明全屏遮罩（用于点击外部关闭下拉） |

**设计规格：** 胶囊圆角 36rpx (PC 22px)，白色背景，边框 #e8e8ed，焦点态边框 #4285f4 + 蓝色阴影，移动端与 PC 端均已适配。