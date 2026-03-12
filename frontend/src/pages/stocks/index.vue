<template>
  <view class="stocks-container">
    <!-- Tab Bar -->
    <StocksTabBar
      :active-tab="activeTab"
      @select-rs="onSelectRs"
      @select-vcp="onSelectVcp"
      @select-value="onSelectValue"
      @select-sandbox="switchToSandbox"
    />

    <!-- ═══════════════════════════════════════════════════════
         RS Rating Tab — 前端暂时隐藏，后端定时计算服务继续运行
         ═══════════════════════════════════════════════════════ -->
    <!-- RS Rating 前端模板已注释，恢复时取消注释即可
    <template v-if="activeTab === 'rs'">
      <view class="stocks-header">
        <text class="stocks-title">RS Rating</text>
        <text class="stocks-subtitle">相对强度排行 · RS Rating > 80</text>
      </view>
      <view class="vcp-filters">
        <view class="vcp-search-section">
          <view class="vcp-search-bar" :class="{ 'vcp-search-bar-focus': searchFocused }">
            <view class="vcp-search-input-wrap">
              <text class="vcp-search-icon">🔍</text>
              <input class="vcp-search-input" type="text" placeholder="搜索代码/名称/拼音首字母..." :value="searchQuery" @input="onSearchInput" @focus="onSearchFocus" @confirm="onSearchConfirm" confirm-type="search" />
              <view v-if="searchQuery" class="vcp-search-clear" @click="onClearSearch"><text class="vcp-search-clear-icon">×</text></view>
            </view>
            <view v-if="searchMode" class="rs-search-cancel" @click="onExitSearch"><text class="rs-search-cancel-text">取消</text></view>
          </view>
        </view>
      </view>
      <template v-if="searchMode && searchSubmitted">
        <EmptyState v-if="searchLoading" text="搜索中..." bg="#ffffff" radius="0 0 16rpx 16rpx" />
        <EmptyState v-else-if="searchMessage" :text="searchMessage" bg="#ffffff" radius="0 0 16rpx 16rpx" />
        <template v-else-if="searchList.length > 0">
          <view class="info-bar"><text class="info-date">找到 {{ searchList.length }} 条结果</text></view>
          <view class="table-header">
            <text class="th th-rank">#</text><text class="th th-name">名称/代码</text>
            <text class="th th-close">收盘价</text><text class="th th-pct">涨跌幅</text><text class="th th-rs">RS</text>
          </view>
          <view class="stock-list">
            <view v-for="(item, idx) in searchList" :key="item.ts_code" class="stock-row" :class="{ 'stock-row-alt': idx % 2 === 1 }">
              <view class="col col-rank"><text class="rank-num">{{ idx + 1 }}</text></view>
              <view class="col col-name"><text class="stock-name">{{ item.name }}</text><text class="stock-code">{{ item.ts_code }}</text></view>
              <view class="col col-close"><text class="close-price">{{ formatPrice(item.close) }}</text></view>
              <view class="col col-pct"><view class="change-badge" :class="changeClass(item.pct_change)"><text class="change-text">{{ formatPct(item.pct_change) }}</text></view><text class="change-abs">{{ formatChange(item.change) }}</text></view>
              <view class="col col-rs"><view class="rs-badge" :class="rsClass(item.rs_rating)"><text class="rs-value">{{ item.rs_rating }}</text></view></view>
            </view>
          </view>
        </template>
      </template>
      <template v-if="!searchMode">
        <view class="info-bar">
          <text class="info-date">数据日期: {{ dataDate || '--' }}</text>
          <view v-if="isTrading" class="trading-badge"><text class="trading-dot">●</text><text class="trading-text">盘中</text></view>
        </view>
        <view class="table-header">
          <text class="th th-rank">#</text><text class="th th-name">名称/代码</text>
          <text class="th th-close">收盘价</text><text class="th th-pct">涨跌幅</text><text class="th th-rs">RS</text>
        </view>
        <EmptyState v-if="loading" text="加载中..." bg="#ffffff" radius="0 0 16rpx 16rpx" />
        <EmptyState v-else-if="stockList.length === 0" text="暂无数据" bg="#ffffff" radius="0 0 16rpx 16rpx" />
        <view v-else class="stock-list">
          <view v-for="(item, idx) in stockList" :key="item.ts_code" class="stock-row" :class="{ 'stock-row-alt': idx % 2 === 1 }">
            <view class="col col-rank"><text class="rank-num" :class="rankClass(idx)">{{ idx + 1 }}</text></view>
            <view class="col col-name"><text class="stock-name">{{ item.name }}</text><text class="stock-code">{{ item.ts_code }}</text></view>
            <view class="col col-close"><text class="close-price">{{ formatPrice(item.close) }}</text></view>
            <view class="col col-pct"><view class="change-badge" :class="changeClass(item.pct_change)"><text class="change-text">{{ formatPct(item.pct_change) }}</text></view><text class="change-abs">{{ formatChange(item.change) }}</text></view>
            <view class="col col-rs"><view class="rs-badge" :class="rsClass(item.rs_rating)"><text class="rs-value">{{ item.rs_rating }}</text></view></view>
          </view>
        </view>
      </template>
    </template>
    -->

    <!-- ═══════════════════════════════════════════════════════
         VCP 策略 Tab
         ═══════════════════════════════════════════════════════ -->
    <template v-if="activeTab === 'vcp'">
      <view class="stocks-header">
        <text class="stocks-title">VCP 策略</text>
        <text class="stocks-subtitle">波动收缩形态 · Volatility Contraction Pattern</text>
      </view>

      <view class="info-bar">
        <text class="info-date">数据日期: {{ vcpDate || '--' }}</text>
        <text class="info-date">共 {{ vcpFilteredList.length }}/{{ vcpList.length }} 只</text>
      </view>

      <!-- VCP 筛选器 -->
      <!-- 点击外部关闭下拉的遮罩 -->
      <view v-if="vcpIndDropdown || vcpConDropdown" class="vcp-overlay" @click="vcpIndDropdown = false; vcpConDropdown = false"></view>

      <view class="vcp-filters">
        <!-- 行业搜索栏 -->
        <view class="vcp-search-section">
          <view class="vcp-search-bar" :class="{ 'vcp-search-bar-focus': vcpIndDropdown }" @click.stop="vcpIndDropdown = !vcpIndDropdown; vcpConDropdown = false">
            <view class="vcp-search-input-wrap">
              <text class="vcp-search-icon">🔍</text>
              <input
                class="vcp-search-input"
                type="text"
                v-model="vcpIndSearch"
                placeholder="搜索行业..."
                @focus="vcpIndDropdown = true; vcpConDropdown = false"
                @click.stop
              />
              <text v-if="vcpSelIndustries.length > 0" class="vcp-search-badge">{{ vcpSelIndustries.length }}</text>
              <view v-if="vcpIndSearch" class="vcp-search-clear" @click.stop="vcpIndSearch = ''">
                <text class="vcp-search-clear-icon">×</text>
              </view>
            </view>
          </view>
          <!-- 行业下拉列表 -->
          <view v-if="vcpIndDropdown" class="vcp-dropdown" @click.stop>
            <scroll-view scroll-y class="vcp-dropdown-scroll">
              <view
                v-for="ind in filteredIndustries"
                :key="ind"
                class="vcp-dropdown-item"
                :class="{ 'vcp-dropdown-item-active': vcpSelIndustries.includes(ind) }"
                @click.stop="toggleIndustry(ind)"
              >
                <text class="vcp-dropdown-check">{{ vcpSelIndustries.includes(ind) ? '✓' : '' }}</text>
                <text class="vcp-dropdown-text">{{ ind }}</text>
              </view>
              <view v-if="filteredIndustries.length === 0" class="vcp-dropdown-empty">
                <text>无匹配行业</text>
              </view>
            </scroll-view>
          </view>
          <!-- 行业已选标签 -->
          <view v-if="vcpSelIndustries.length > 0" class="vcp-tags">
            <text
              v-for="ind in vcpSelIndustries"
              :key="ind"
              class="vcp-tag"
              @click.stop="toggleIndustry(ind)"
            >{{ ind }} ✕</text>
          </view>
        </view>

        <!-- 概念搜索栏 -->
        <view class="vcp-search-section">
          <view class="vcp-search-bar" :class="{ 'vcp-search-bar-focus': vcpConDropdown }" @click.stop="vcpConDropdown = !vcpConDropdown; vcpIndDropdown = false">
            <view class="vcp-search-input-wrap">
              <text class="vcp-search-icon">🔍</text>
              <input
                class="vcp-search-input"
                type="text"
                v-model="vcpConSearch"
                placeholder="搜索概念板块..."
                @focus="vcpConDropdown = true; vcpIndDropdown = false"
                @click.stop
              />
              <text v-if="vcpSelConcepts.length > 0" class="vcp-search-badge">{{ vcpSelConcepts.length }}</text>
              <view v-if="vcpConSearch" class="vcp-search-clear" @click.stop="vcpConSearch = ''">
                <text class="vcp-search-clear-icon">×</text>
              </view>
            </view>
          </view>
          <!-- 概念下拉列表 -->
          <view v-if="vcpConDropdown" class="vcp-dropdown" @click.stop>
            <scroll-view scroll-y class="vcp-dropdown-scroll">
              <view
                v-for="con in filteredConcepts"
                :key="con"
                class="vcp-dropdown-item"
                :class="{ 'vcp-dropdown-item-active': vcpSelConcepts.includes(con) }"
                @click.stop="toggleConcept(con)"
              >
                <text class="vcp-dropdown-check">{{ vcpSelConcepts.includes(con) ? '✓' : '' }}</text>
                <text class="vcp-dropdown-text">{{ con }}</text>
              </view>
              <view v-if="filteredConcepts.length === 0" class="vcp-dropdown-empty">
                <text>无匹配概念</text>
              </view>
            </scroll-view>
          </view>
          <!-- 概念已选标签 -->
          <view v-if="vcpSelConcepts.length > 0" class="vcp-tags">
            <text
              v-for="con in vcpSelConcepts"
              :key="con"
              class="vcp-tag"
              @click.stop="toggleConcept(con)"
            >{{ con }} ✕</text>
          </view>
        </view>

        <!-- 清除全部按钮 -->
        <view v-if="vcpSelIndustries.length + vcpSelConcepts.length > 0" class="vcp-clear-all" @click="clearVcpFilters">
          <text class="vcp-clear-all-text">清除全部筛选 ({{ vcpSelIndustries.length + vcpSelConcepts.length }})</text>
        </view>
      </view>

      <!-- VCP 表格头 -->
      <view class="vcp-table-header">
        <text class="vth vth-rank">#</text>
        <text class="vth vth-name">名称/代码</text>
        <text class="vth vth-price">收盘价</text>
        <text class="vth vth-vcp">VCP</text>
        <text class="vth vth-flow">资金流入</text>
        <text class="vth vth-action">交易</text>
      </view>

      <EmptyState v-if="vcpLoading" text="加载中..." bg="#ffffff" radius="0 0 16rpx 16rpx" />
      <EmptyState v-else-if="vcpFilteredList.length === 0" :text="vcpList.length === 0 ? '暂无白名单数据' : '无匹配结果，请调整筛选条件'" bg="#ffffff" radius="0 0 16rpx 16rpx" />
      <view v-else class="stock-list">
        <view
          v-for="(item, idx) in vcpFilteredList"
          :key="item.ts_code"
          class="vcp-row"
          :class="{ 'stock-row-alt': idx % 2 === 1 }"
          @click="vcpExpandedIdx = vcpExpandedIdx === idx ? -1 : idx"
        >
          <!-- 主行第一行：核心指标 -->
          <view class="vcp-row-main">
            <view class="col vcp-col-rank"><text class="rank-num" :class="rankClass(idx)">{{ idx + 1 }}</text></view>
            <view class="col vcp-col-name">
              <text class="stock-name">{{ item.name || item.ts_code }}</text>
              <text class="stock-code">{{ item.ts_code }}{{ item.industry ? ' · ' + item.industry : '' }}</text>
            </view>
            <view class="col vcp-col-price"><text class="close-price">{{ formatPrice(item.current_price) }}</text></view>
            <view class="col vcp-col-vcp">
              <view class="vcp-badge" :class="vcpClass(item.vcp_score)">
                <text class="vcp-val">{{ formatVcp(item.vcp_score) }}</text>
              </view>
            </view>
            <view class="col vcp-col-flow">
              <text class="flow-val" :class="pctValClass(item.fund_flow_net)">
                {{ item.fund_flow_net != null ? (item.fund_flow_net >= 0 ? '+' : '') + item.fund_flow_net.toFixed(0) + '万' : '--' }}
              </text>
            </view>
            <view class="col vcp-col-action">
              <!-- #ifdef H5 -->
              <a :href="item.futu_url" class="futu-link" @click.stop>
                <text class="futu-icon">📈</text>
              </a>
              <!-- #endif -->
            </view>
          </view>

          <!-- 主行第二行：题材标签 -->
          <view v-if="item.concepts" class="vcp-row-concepts">
            <text
              v-for="tag in item.concepts.split(', ').slice(0, 4)"
              :key="tag"
              class="concept-tag"
            >{{ tag }}</text>
          </view>

          <!-- 展开行：完整详情 -->
          <view v-if="vcpExpandedIdx === idx" class="vcp-expand">
            <view class="vcp-expand-row">
              <text class="vcp-expand-label">行业</text>
              <text class="vcp-expand-val">{{ item.industry || '--' }}</text>
            </view>
            <view class="vcp-expand-row">
              <text class="vcp-expand-label">题材</text>
              <text class="vcp-expand-val vcp-concepts">{{ item.concepts || '--' }}</text>
            </view>
            <view class="vcp-expand-row">
              <text class="vcp-expand-label">主力净流入</text>
              <text class="vcp-expand-val" :class="pctValClass(item.fund_flow_net)">
                {{ item.fund_flow_net != null ? (item.fund_flow_net >= 0 ? '+' : '') + item.fund_flow_net.toFixed(2) + '万' : '--' }}
              </text>
            </view>
            <view class="vcp-expand-row">
              <text class="vcp-expand-label">EPS增长</text>
              <text class="vcp-expand-val" :class="pctValClass(item.eps_growth)">{{ formatPctVal(item.eps_growth) }}</text>
            </view>
            <view class="vcp-expand-row">
              <text class="vcp-expand-label">营收同比</text>
              <text class="vcp-expand-val" :class="pctValClass(item.revenue_yoy)">{{ formatPctVal(item.revenue_yoy) }}</text>
            </view>
            <view class="vcp-expand-row">
              <text class="vcp-expand-label">主营业务</text>
              <text class="vcp-expand-val vcp-business">{{ item.main_business || '--' }}</text>
            </view>
            <view class="vcp-expand-row">
              <text class="vcp-expand-label">EMA</text>
              <text class="vcp-expand-val">20d: {{ formatPrice(item.ema20) }}　50d: {{ formatPrice(item.ema50) }}　120d: {{ formatPrice(item.ema120) }}</text>
            </view>
          </view>
        </view>
      </view>
    </template>

    <!-- ═══════════════════════════════════════════════════════
         价投策略 Tab
         ═══════════════════════════════════════════════════════ -->
    <template v-if="activeTab === 'value'">
      <view class="stocks-header">
        <view class="value-header-row">
          <view>
            <text class="stocks-title">价投策略</text>
            <text class="stocks-subtitle">巴菲特式价值投资 · Value Investing</text>
          </view>
          <view class="value-add-btn" @click="showValueAddModal = true">
            <text class="value-add-icon">+</text>
            <text class="value-add-text">添加标的</text>
          </view>
        </view>
      </view>

      <view class="info-bar">
        <text class="info-date">共 {{ valueFilteredList.length }}/{{ valueList.length }} 只</text>
      </view>

      <!-- 价投筛选器 — 行业搜索 -->
      <view v-if="valueIndDropdown" class="vcp-overlay" @click="valueIndDropdown = false"></view>

      <view class="vcp-filters">
        <view class="vcp-search-section">
          <view class="vcp-search-bar" :class="{ 'vcp-search-bar-focus': valueIndDropdown }" @click.stop="valueIndDropdown = !valueIndDropdown">
            <view class="vcp-search-input-wrap">
              <text class="vcp-search-icon">🔍</text>
              <input
                class="vcp-search-input"
                type="text"
                v-model="valueSearch"
                placeholder="搜索代码/名称..."
                @focus="valueIndDropdown = false"
                @click.stop
              />
              <view v-if="valueSearch" class="vcp-search-clear" @click.stop="valueSearch = ''">
                <text class="vcp-search-clear-icon">×</text>
              </view>
            </view>
          </view>
        </view>
      </view>

      <!-- 价投表格头 -->
      <view class="vcp-table-header">
        <text class="vth vth-rank">#</text>
        <text class="vth vth-name">名称/代码</text>
        <text class="vth vth-price">收盘价</text>
        <text class="vth vth-flow">状态</text>
        <text class="vth vth-action">交易</text>
      </view>

      <EmptyState v-if="valueLoading" text="加载中..." bg="#ffffff" radius="0 0 16rpx 16rpx" />
      <EmptyState v-else-if="valueFilteredList.length === 0" :text="valueList.length === 0 ? '暂无价投标的' : '无匹配结果'" bg="#ffffff" radius="0 0 16rpx 16rpx" />
      <view v-else class="stock-list">
        <view
          v-for="(item, idx) in valueFilteredList"
          :key="item.ts_code"
          class="vcp-row"
          :class="{ 'stock-row-alt': idx % 2 === 1 }"
          @click="valueExpandedIdx = valueExpandedIdx === idx ? -1 : idx"
        >
          <!-- 主行：核心信息 -->
          <view class="vcp-row-main">
            <view class="col vcp-col-rank"><text class="rank-num" :class="rankClass(idx)">{{ idx + 1 }}</text></view>
            <view class="col vcp-col-name">
              <text class="stock-name">{{ item.name || item.ts_code }}</text>
              <text class="stock-code">{{ item.ts_code }}{{ item.industry ? ' · ' + item.industry : '' }}</text>
            </view>
            <view class="col vcp-col-price"><text class="close-price">{{ formatPrice(item.current_price) }}</text></view>
            <view class="col vcp-col-flow">
              <view class="value-status-badge" :class="'value-status-' + item.status">
                <text class="value-status-text">{{ item.status === 'holding' ? '持仓' : '观察' }}</text>
              </view>
            </view>
            <view class="col vcp-col-action">
              <!-- #ifdef H5 -->
              <a :href="item.futu_url" class="futu-link" @click.stop>
                <text class="futu-icon">📈</text>
              </a>
              <!-- #endif -->
            </view>
          </view>

          <!-- 题材标签行 -->
          <view v-if="item.concepts" class="vcp-row-concepts">
            <text
              v-for="tag in item.concepts.split(', ').slice(0, 4)"
              :key="tag"
              class="concept-tag"
            >{{ tag }}</text>
          </view>

          <!-- 展开行：详情 -->
          <view v-if="valueExpandedIdx === idx" class="vcp-expand">
            <view class="vcp-expand-row">
              <text class="vcp-expand-label">行业</text>
              <text class="vcp-expand-val">{{ item.industry || '--' }}</text>
            </view>
            <view class="vcp-expand-row">
              <text class="vcp-expand-label">题材</text>
              <text class="vcp-expand-val vcp-concepts">{{ item.concepts || '--' }}</text>
            </view>
            <view v-if="item.reason" class="vcp-expand-row">
              <text class="vcp-expand-label">投资理由</text>
              <text class="vcp-expand-val vcp-business">{{ item.reason }}</text>
            </view>
            <view class="vcp-expand-row">
              <text class="vcp-expand-label">加入时间</text>
              <text class="vcp-expand-val">{{ item.added_at ? item.added_at.split('T')[0] : '--' }}</text>
            </view>
            <view class="value-remove-row" @click.stop="onRemoveValue(item)">
              <text class="value-remove-text">移除此标的</text>
            </view>
          </view>
        </view>
      </view>
    </template>

    <!-- ═══════════════════════════════════════════════════════
         模拟仓 Tab
         ═══════════════════════════════════════════════════════ -->
    <template v-if="activeTab === 'sandbox'">
      <!-- 净值概览卡 -->
      <view class="sb-hero-card">
        <view class="sb-hero-top">
          <text class="sb-hero-since">成立于 2026.02.13</text>
        </view>
        <view class="sb-hero-body">
          <view class="sb-hero-left">
            <text class="sb-nav-big" :class="sbSummary.total_pnl >= 0 ? '' : 'sb-nav-down'">
              {{ sbSummary.latest_nav?.toFixed(4) || '1.0000' }}
            </text>
            <text class="sb-nav-sub">当前单位净值</text>
          </view>
        </view>
        <!-- 圆滑净值曲线 SVG -->
        <view v-if="navSeries.length > 1" class="sb-nav-chart">
          <view class="sb-nav-chart-inner" :style="{ height: '160rpx' }">
            <!-- #ifdef H5 -->
            <svg xmlns="http://www.w3.org/2000/svg" :viewBox="`0 0 ${navChartWidth} ${navChartHeight}`" class="sb-svg-chart">
              <defs>
                <linearGradient id="navFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" :stop-color="navTrendColor" stop-opacity="0.2" />
                  <stop offset="100%" :stop-color="navTrendColor" stop-opacity="0.02" />
                </linearGradient>
              </defs>
              <!-- 面积填充 -->
              <path :d="navAreaPath" fill="url(#navFill)" />
              <!-- 曲线 -->
              <path :d="navCurvePath" fill="none" :stroke="navTrendColor" stroke-width="2" stroke-linecap="round" />
              <!-- 基准线 -->
              <line x1="0" :y1="navBaseY" :x2="navChartWidth" :y2="navBaseY" stroke="#d0d0d8" stroke-width="0.5" stroke-dasharray="4,3" />
            </svg>
            <!-- #endif -->
          </view>
        </view>
        <!-- 收益率指标行 -->
        <view class="sb-metric-row">
          <view class="sb-metric-item">
            <text class="sb-metric-label">成立以来</text>
            <text class="sb-metric-val" :class="pnlClass(sbSummary.pnl_since_inception)">
              {{ formatPnlVal(sbSummary.pnl_since_inception) }}
            </text>
          </view>
          <view class="sb-metric-item">
            <text class="sb-metric-label">近一年</text>
            <text class="sb-metric-val" :class="pnlClass(sbSummary.pnl_1y)">
              {{ formatPnlVal(sbSummary.pnl_1y) }}
            </text>
          </view>
          <view class="sb-metric-item">
            <text class="sb-metric-label">近三月</text>
            <text class="sb-metric-val" :class="pnlClass(sbSummary.pnl_3m)">
              {{ formatPnlVal(sbSummary.pnl_3m) }}
            </text>
          </view>
          <view class="sb-metric-item">
            <text class="sb-metric-label">今年以来</text>
            <text class="sb-metric-val" :class="pnlClass(sbSummary.pnl_ytd)">
              {{ formatPnlVal(sbSummary.pnl_ytd) }}
            </text>
          </view>
        </view>
      </view>

      <!-- 持仓分布环状图 -->
      <view v-if="holdingsPie.length > 1" class="sb-pie-card">
        <view class="sb-pie-header">
          <text class="sb-pie-title">持仓分布</text>
          <text class="sb-pie-sub">仓位 {{ holdingsPositionPct }}%</text>
        </view>
        <view class="sb-pie-body">
          <!-- #ifdef H5 -->
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" class="sb-pie-svg">
            <circle cx="100" cy="100" r="70" fill="none" stroke="#f0f2f5" stroke-width="28" />
            <circle
              v-for="(seg, i) in pieSegments"
              :key="i"
              cx="100" cy="100" r="70"
              fill="none"
              :stroke="seg.color"
              stroke-width="28"
              :stroke-dasharray="seg.dash"
              :stroke-dashoffset="seg.offset"
              style="transition: stroke-dasharray 0.5s, stroke-dashoffset 0.5s"
            />
            <text x="100" y="94" text-anchor="middle" font-size="22" font-weight="800" fill="#1a1a2e">
              {{ sbSummary.holding_count || 0 }}
            </text>
            <text x="100" y="116" text-anchor="middle" font-size="11" fill="#8c8c9a">只持仓</text>
          </svg>
          <!-- #endif -->
          <view class="sb-pie-legend">
            <view
              v-for="(item, i) in holdingsPie"
              :key="i"
              class="sb-legend-item"
            >
              <view class="sb-legend-dot" :style="{ background: pieColors[i % pieColors.length] }"></view>
              <text class="sb-legend-name">{{ item.name }}</text>
              <text class="sb-legend-pct">{{ item.pct }}%</text>
            </view>
          </view>
        </view>
      </view>

      <!-- 观察池快照 -->
      <view class="sb-snapshot">
        <view class="sb-snapshot-header">
          <text class="sb-snapshot-title">观察池快照 ({{ sbSummary.total_active || 0 }}支)</text>
          <text class="sb-snapshot-time">{{ sbSummary.latest_date || '' }}</text>
        </view>
        <view class="sb-snapshot-tags">
          <view
            class="sb-tag sb-tag-retain"
            :class="{ 'sb-tag-active': sbFilter === 'watching' }"
            @click="toggleStatusFilter('watching')"
          >
            <text class="sb-tag-label">观察中</text>
            <text class="sb-tag-num">{{ sbSummary.watching_count || 0 }}支</text>
          </view>
          <view
            class="sb-tag sb-tag-gray"
            :class="{ 'sb-tag-active': sbFilter === 'holding' }"
            @click="toggleStatusFilter('holding')"
          >
            <text class="sb-tag-label">持仓中</text>
            <text class="sb-tag-num">{{ sbSummary.holding_count || 0 }}支</text>
          </view>
        </view>

        <!-- 筛选 + 搜索栏 -->
        <view class="sb-filter-bar">
          <view
            class="sb-filter-chip"
            :class="{ 'sb-filter-chip-active': sbHoldingOnly }"
            @click="toggleHoldingOnly"
          >
            <text class="sb-filter-chip-text">持仓票</text>
          </view>
          <view class="sb-search-wrap">
            <text class="sb-search-icon">🔍</text>
            <input
              class="sb-search-input"
              type="text"
              placeholder="代码 / 名称"
              :value="sbSearchQuery"
              @input="onSbSearchInput"
              @confirm="onSbSearchConfirm"
            />
            <text v-if="sbSearchQuery" class="sb-search-clear" @click="onSbClearSearch">✕</text>
          </view>
        </view>
      </view>

      <!-- 加载 / 空态 -->
      <EmptyState v-if="sbLoading" text="加载中..." bg="#ffffff" radius="16rpx" style="margin-top: 12rpx;" />
      <EmptyState v-else-if="sbStocks.length === 0" text="暂无数据" bg="#ffffff" radius="16rpx" style="margin-top: 12rpx;" />

      <!-- 股票列表 -->
      <view v-else class="sb-stock-list">
        <view
          v-for="item in sbStocks"
          :key="item.id"
          class="sb-stock-card"
          :class="{ 'sb-card-highlight': isHoldingRetain(item) }"
          @click="goToDetail(item.id)"
        >
          <!-- 持仓+留存 特殊标识条 -->
          <view v-if="isHoldingRetain(item)" class="sb-highlight-bar">
            <text class="sb-highlight-icon">●</text>
            <text class="sb-highlight-text">持仓中</text>
          </view>

          <!-- 头部: 名称 + 状态 -->
          <view class="sb-card-top">
            <view class="sb-card-name-row">
              <text class="sb-stock-name">{{ item.name }}</text>
              <text class="sb-stock-code">（{{ item.ts_code }}）</text>
            </view>
            <view class="sb-status-badge" :class="'sb-status-' + item.status">
              <text class="sb-status-text">{{ statusLabel(item.status) }}</text>
            </view>
          </view>

          <!-- 推演摘要 -->
          <template v-if="item.latest_analysis">
            <!-- 评分 -->
            <view class="sb-score-row">
              <text class="sb-score-label">综合评分：</text>
              <text class="sb-score-big" :class="scoreClass(item.latest_analysis.score)">{{ item.latest_analysis.score.toFixed(1) }}</text>
              <text class="sb-score-max">/ 5.0</text>
            </view>

            <!-- 哨子 Verdict -->
            <text class="sb-verdict">{{ item.latest_analysis.verdict }}</text>

            <!-- 推演统计 -->
            <view class="sb-action-row">
              <view class="sb-meta-info">
                <text class="sb-analysis-count">{{ item.analysis_count || 0 }}条记录</text>
                <text class="sb-analysis-dot">·</text>
                <text class="sb-analysis-date">{{ formatShortDate(item.analysis_latest_at || item.latest_analysis.created_at) }}</text>
              </view>
            </view>
          </template>

          <view v-if="item.position_pct > 0" class="sb-card-bottom">
            <view class="sb-position-bar-wrap">
              <view class="sb-position-bar" :style="{ width: item.position_pct + '%' }"></view>
            </view>
            <text class="sb-shares">持仓 {{ item.position_pct }}%</text>
          </view>

          <view class="sb-card-arrow">
            <text class="arrow-icon">›</text>
          </view>
        </view>
      </view>
    </template>

    <!-- Footer -->
    <SiteFooter />

    <!-- 模拟仓密码验证弹窗 -->
    <SandboxPasswordModal
      :visible="showPwdModal"
      :password="pwdValue"
      :error="pwdError"
      @update:visible="showPwdModal = $event"
      @update:password="pwdValue = $event"
      @confirm="onPwdConfirm"
    />

    <!-- 价投标的添加弹窗 -->
    <ValueStockAddModal
      :visible="showValueAddModal"
      @update:visible="showValueAddModal = $event"
      @added="onValueStockAdded"
    />
  </view>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import StocksTabBar from '@/components/stocks/StocksTabBar.vue'
import SandboxPasswordModal from '@/components/stocks/SandboxPasswordModal.vue'
import ValueStockAddModal from '@/components/stocks/ValueStockAddModal.vue'
import SiteFooter from '@/components/common/SiteFooter.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { fetchRSRating, searchStocks, fetchVCPWatchlist, fetchVCPFilters, fetchValueWatchlist, removeValueStock, fetchSandboxOverview, fetchSandboxStocks as apiFetchSandboxStocks, verifySandboxAccess } from '@/utils/api'

const activeTab = ref('vcp')
const onSelectRs = () => { activeTab.value = 'rs' }
const onSelectVcp = () => { activeTab.value = 'vcp'; if (!vcpLoaded) { vcpLoaded = true; loadVCPData(); loadVCPFilters() } }
const onSelectValue = () => { activeTab.value = 'value'; if (!valueLoaded) { valueLoaded = true; loadValueData() } }

// ═══════════════════════════════════════════════════════
// RS Rating
// ═══════════════════════════════════════════════════════

const stockList = ref([])
const dataDate = ref('')
const loading = ref(true)

const searchMode = ref(false)
const searchFocused = ref(false)
const searchQuery = ref('')
const searchSubmitted = ref(false)
const searchList = ref([])
const searchLoading = ref(false)
const searchMessage = ref('')

const isTrading = computed(() => {
  const now = new Date()
  const day = now.getDay()
  if (day === 0 || day === 6) return false
  const h = now.getHours()
  const m = now.getMinutes()
  const t = h * 60 + m
  return t >= 570 && t <= 900
})

onMounted(async () => {
  // 默认 tab 是 VCP，直接加载 VCP 数据
  vcpLoaded = true
  loadVCPData()
  loadVCPFilters()

  // RS Rating 前端已隐藏，不再加载数据
  // try {
  //   const data = await fetchRSRating({ min_rating: 80, top_n: 5000 })
  //   stockList.value = data.items || []
  //   dataDate.value = data.date || ''
  // } catch (e) {
  //   console.error('加载 RS Rating 失败:', e)
  //   uni.showToast({ title: '加载失败', icon: 'none' })
  // } finally {
  //   loading.value = false
  // }
})

const onSearchFocus = () => { searchFocused.value = true; searchMode.value = true }
const onSearchInput = (e) => { searchQuery.value = e.detail.value; searchSubmitted.value = false; searchMessage.value = '' }
const onSearchConfirm = () => { if (searchQuery.value.trim()) doSearch() }
const onClearSearch = () => { searchQuery.value = ''; searchSubmitted.value = false; searchList.value = []; searchMessage.value = '' }
const onExitSearch = () => { searchMode.value = false; searchFocused.value = false; onClearSearch() }

const doSearch = async () => {
  const q = searchQuery.value.trim()
  if (!q) return
  searchSubmitted.value = true
  searchLoading.value = true
  searchList.value = []
  searchMessage.value = ''
  try {
    const data = await searchStocks({ q })
    searchList.value = data.items || []
    searchMessage.value = data.message || ''
  } catch (e) {
    console.error('搜索失败:', e)
    uni.showToast({ title: '搜索失败', icon: 'none' })
  } finally {
    searchLoading.value = false
  }
}

const formatPrice = (v) => v == null ? '--' : Number(v).toFixed(2)
const formatPct = (v) => {
  if (v == null) return '--'
  const n = Number(v)
  return (n >= 0 ? '+' : '') + n.toFixed(2) + '%'
}
const formatChange = (v) => {
  if (v == null) return ''
  const n = Number(v)
  return (n >= 0 ? '+' : '') + n.toFixed(2)
}
const changeClass = (v) => v == null ? 'change-flat' : v > 0 ? 'change-up' : v < 0 ? 'change-down' : 'change-flat'
const rankClass = (idx) => idx < 3 ? 'rank-top' : idx < 10 ? 'rank-high' : ''
const rsClass = (rating) => rating >= 90 ? 'rs-hot' : rating >= 70 ? 'rs-warm' : rating >= 50 ? 'rs-normal' : 'rs-cool'

// ═══════════════════════════════════════════════════════
// VCP 策略
// ═══════════════════════════════════════════════════════

const vcpList = ref([])
const vcpDate = ref('')
const vcpLoading = ref(false)
const vcpExpandedIdx = ref(-1)
let vcpLoaded = false

// ── VCP 筛选器 ──
const vcpIndustryOptions = ref([])   // 行业枚举
const vcpConceptOptions = ref([])    // 概念枚举
const vcpSelIndustries = ref([])     // 已选行业
const vcpSelConcepts = ref([])       // 已选概念
const vcpIndSearch = ref('')         // 行业搜索关键字
const vcpConSearch = ref('')         // 概念搜索关键字
const vcpIndDropdown = ref(false)    // 行业下拉展开
const vcpConDropdown = ref(false)    // 概念下拉展开

// 筛选后的行业选项（搜索过滤）
const filteredIndustries = computed(() => {
  const kw = vcpIndSearch.value.trim().toLowerCase()
  if (!kw) return vcpIndustryOptions.value
  return vcpIndustryOptions.value.filter(i => i.toLowerCase().includes(kw))
})

// 筛选后的概念选项（搜索过滤）
const filteredConcepts = computed(() => {
  const kw = vcpConSearch.value.trim().toLowerCase()
  if (!kw) return vcpConceptOptions.value
  return vcpConceptOptions.value.filter(c => c.toLowerCase().includes(kw))
})

// 筛选后的 VCP 列表
const vcpFilteredList = computed(() => {
  let list = vcpList.value
  if (vcpSelIndustries.value.length > 0) {
    list = list.filter(item => item.industry && vcpSelIndustries.value.includes(item.industry))
  }
  if (vcpSelConcepts.value.length > 0) {
    list = list.filter(item => {
      if (!item.concepts) return false
      return vcpSelConcepts.value.some(c => item.concepts.includes(c))
    })
  }
  return list
})

const toggleIndustry = (ind) => {
  const idx = vcpSelIndustries.value.indexOf(ind)
  if (idx >= 0) vcpSelIndustries.value.splice(idx, 1)
  else vcpSelIndustries.value.push(ind)
}

const toggleConcept = (con) => {
  const idx = vcpSelConcepts.value.indexOf(con)
  if (idx >= 0) vcpSelConcepts.value.splice(idx, 1)
  else vcpSelConcepts.value.push(con)
}

const clearVcpFilters = () => {
  vcpSelIndustries.value = []
  vcpSelConcepts.value = []
  vcpIndSearch.value = ''
  vcpConSearch.value = ''
}

const loadVCPFilters = async () => {
  try {
    const data = await fetchVCPFilters()
    vcpIndustryOptions.value = data.industries || []
    vcpConceptOptions.value = data.concepts || []
  } catch (e) {
    console.error('加载 VCP 筛选项失败:', e)
  }
}

const loadVCPData = async () => {
  vcpLoading.value = true
  try {
    const data = await fetchVCPWatchlist({})
    vcpList.value = data.items || []
    vcpDate.value = data.date || ''
  } catch (e) {
    console.error('加载 VCP 白名单失败:', e)
    uni.showToast({ title: '加载失败', icon: 'none' })
  } finally {
    vcpLoading.value = false
  }
}

const formatVcp = (v) => v == null ? '--' : Number(v).toFixed(3)
const vcpClass = (v) => {
  if (v == null) return 'vcp-level-none'
  return v >= 0.50 ? 'vcp-level-hot' : v >= 0.30 ? 'vcp-level-warm' : v >= 0.10 ? 'vcp-level-normal' : 'vcp-level-cool'
}
const formatPctVal = (v) => {
  if (v == null) return '--'
  const n = Number(v)
  return (n >= 0 ? '+' : '') + n.toFixed(1) + '%'
}
const pctValClass = (v) => v == null ? '' : v > 0 ? 'val-up' : v < 0 ? 'val-down' : ''

// ═══════════════════════════════════════════════════════
// 价投策略
// ═══════════════════════════════════════════════════════

const valueList = ref([])
const valueLoading = ref(false)
const valueExpandedIdx = ref(-1)
const valueSearch = ref('')
const valueIndDropdown = ref(false)
const showValueAddModal = ref(false)
let valueLoaded = false

const valueFilteredList = computed(() => {
  const kw = valueSearch.value.trim().toLowerCase()
  if (!kw) return valueList.value
  return valueList.value.filter(item => {
    const code = (item.ts_code || '').toLowerCase()
    const name = (item.name || '').toLowerCase()
    return code.includes(kw) || name.includes(kw)
  })
})

const loadValueData = async () => {
  valueLoading.value = true
  try {
    const data = await fetchValueWatchlist()
    valueList.value = data.items || []
  } catch (e) {
    console.error('加载价投白名单失败:', e)
    uni.showToast({ title: '加载失败', icon: 'none' })
  } finally {
    valueLoading.value = false
  }
}

const onValueStockAdded = () => {
  // 添加成功后刷新列表
  loadValueData()
}

const onRemoveValue = (item) => {
  uni.showModal({
    title: '移除确认',
    content: `确定移除「${item.name || item.ts_code}」吗？`,
    confirmText: '移除',
    confirmColor: '#ef4444',
    success: async (res) => {
      if (!res.confirm) return
      // 使用缓存密码
      let pwd = ''
      try { pwd = uni.getStorageSync('value_pwd') || '' } catch (_) {}
      try {
        await removeValueStock(item.id, pwd)
        valueExpandedIdx.value = -1
        loadValueData()
        uni.showToast({ title: '已移除', icon: 'success' })
      } catch (e) {
        const msg = e.message || ''
        if (msg.includes('403')) {
          uni.showToast({ title: '请先通过「添加标的」验证密码', icon: 'none' })
        } else {
          uni.showToast({ title: '移除失败', icon: 'none' })
        }
      }
    }
  })
}

// ═══════════════════════════════════════════════════════
// 模拟仓
// ═══════════════════════════════════════════════════════

const sbLoading = ref(false)
const sbStocks = ref([])
const sbSummary = ref({})
const navSeries = ref([])
const holdingsPie = ref([])
const sbFilter = ref('')
const sbHoldingOnly = ref(false)
const sbSearchQuery = ref('')
let sbLoaded = false
const sbUnlocked = ref(false)
const showPwdModal = ref(false)
const pwdValue = ref('')
const pwdError = ref(false)

// 环状图配色
const pieColors = ['#3b82f6', '#f59e0b', '#22c55e', '#a855f7', '#ef4444', '#06b6d4', '#ec4899', '#8b5cf6', '#14b8a6', '#f97316', '#d0d0d8']

// 仓位百分比（100% - 现金占比）
const holdingsPositionPct = computed(() => {
  const data = holdingsPie.value
  if (!data || data.length === 0) return 0
  const cashItem = data.find(d => d.ts_code === '')
  const cashPct = cashItem ? cashItem.pct : 0
  return (100 - cashPct).toFixed(1)
})

// 环状图弧段计算（纯 SVG stroke-dasharray 实现）
const pieSegments = computed(() => {
  const data = holdingsPie.value
  if (!data || data.length === 0) return []
  const circumference = 2 * Math.PI * 70 // r=70
  const segments = []
  let accumulated = 0
  for (let i = 0; i < data.length; i++) {
    const arc = (data[i].pct / 100) * circumference
    segments.push({
      color: pieColors[i % pieColors.length],
      dash: `${arc} ${circumference - arc}`,
      offset: -(circumference * 0.25 + accumulated),
    })
    accumulated += arc
  }
  return segments
})

const statusLabel = (s) => ({ holding: '持仓', watching: '观察', exited: '退出' }[s] || s)



const isHoldingRetain = (item) => {
  return item.status === 'holding'
}

const scoreClass = (score) => {
  if (score >= 4) return 'sb-score-high'
  if (score >= 2.5) return 'sb-score-mid'
  return 'sb-score-low'
}

const formatShortDate = (iso) => {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const isToday = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate()
  if (isToday) {
    return `今天 ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  return `${d.getMonth() + 1}/${d.getDate()}`
}

const pnlClass = (v) => {
  const n = v || 0
  return n > 0 ? 'metric-up' : n < 0 ? 'metric-down' : 'metric-neutral'
}

const formatPnlVal = (v) => {
  const n = v || 0
  return (n >= 0 ? '+' : '') + n.toFixed(2) + '%'
}

const toggleStatusFilter = (status) => {
  sbFilter.value = sbFilter.value === status ? '' : status
  loadSandboxStocks()
}

const toggleHoldingOnly = () => {
  sbHoldingOnly.value = !sbHoldingOnly.value
  loadSandboxStocks()
}

const onSbSearchInput = (e) => { sbSearchQuery.value = e.detail.value }
const onSbSearchConfirm = () => { loadSandboxStocks() }
const onSbClearSearch = () => { sbSearchQuery.value = ''; loadSandboxStocks() }

const switchToSandbox = () => {
  if (!sbUnlocked.value) {
    try {
      const cached = uni.getStorageSync('sb_unlocked')
      if (cached === 'true') sbUnlocked.value = true
    } catch (_) {}
  }

  if (sbUnlocked.value) {
    activeTab.value = 'sandbox'
    if (!sbLoaded) { sbLoaded = true; loadSandboxData() }
    return
  }

  pwdValue.value = ''
  pwdError.value = false
  showPwdModal.value = true
}

const onPwdConfirm = async () => {
  try {
    await verifySandboxAccess(pwdValue.value)
    sbUnlocked.value = true
    showPwdModal.value = false
    try { uni.setStorageSync('sb_unlocked', 'true') } catch (_) {}
    activeTab.value = 'sandbox'
    if (!sbLoaded) { sbLoaded = true; loadSandboxData() }
  } catch (_) {
    pwdError.value = true
    setTimeout(() => { pwdError.value = false }, 1500)
  }
}

const loadSandboxData = async () => {
  sbLoading.value = true
  try {
    const [overview, stocks] = await Promise.all([
      fetchSandboxOverview(90),
      apiFetchSandboxStocks('', sbFilter.value, sbSearchQuery.value, sbHoldingOnly.value),
    ])
    sbSummary.value = overview.summary || {}
    navSeries.value = overview.nav_series || []
    holdingsPie.value = overview.holdings_pie || []
    sbStocks.value = stocks.items || []
  } catch (e) {
    console.error('加载模拟仓失败:', e)
  } finally {
    sbLoading.value = false
  }
}

const loadSandboxStocks = async () => {
  try {
    const data = await apiFetchSandboxStocks('', sbFilter.value, sbSearchQuery.value, sbHoldingOnly.value)
    sbStocks.value = data.items || []
  } catch (e) {
    console.error(e)
  }
}

// 净值 SVG 曲线计算
const navChartWidth = 400
const navChartHeight = 100

const navTrendColor = computed(() => {
  const series = navSeries.value
  if (series.length < 2) return '#3b82f6'
  return series[series.length - 1].nav >= 1.0 ? '#3b82f6' : '#22c55e'
})

const navSvgPoints = computed(() => {
  const series = navSeries.value
  if (series.length < 2) return []
  const navs = series.map(s => s.nav)
  const min = Math.min(...navs, 1) - 0.005
  const max = Math.max(...navs, 1) + 0.005
  const range = max - min || 1
  const pad = 4
  return series.map((s, i) => ({
    x: pad + (i / (series.length - 1)) * (navChartWidth - pad * 2),
    y: pad + (1 - (s.nav - min) / range) * (navChartHeight - pad * 2),
  }))
})

const navBaseY = computed(() => {
  const series = navSeries.value
  if (series.length < 2) return navChartHeight / 2
  const navs = series.map(s => s.nav)
  const min = Math.min(...navs, 1) - 0.005
  const max = Math.max(...navs, 1) + 0.005
  const pad = 4
  return pad + (1 - (1.0 - min) / (max - min || 1)) * (navChartHeight - pad * 2)
})

// Catmull-Rom → SVG cubic Bezier 平滑曲线
const navCurvePath = computed(() => {
  const pts = navSvgPoints.value
  if (pts.length < 2) return ''
  if (pts.length === 2) return `M${pts[0].x},${pts[0].y} L${pts[1].x},${pts[1].y}`

  let d = `M${pts[0].x},${pts[0].y}`
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(i - 1, 0)]
    const p1 = pts[i]
    const p2 = pts[i + 1]
    const p3 = pts[Math.min(i + 2, pts.length - 1)]
    const t = 0.3
    const cp1x = p1.x + (p2.x - p0.x) * t
    const cp1y = p1.y + (p2.y - p0.y) * t
    const cp2x = p2.x - (p3.x - p1.x) * t
    const cp2y = p2.y - (p3.y - p1.y) * t
    d += ` C${cp1x.toFixed(1)},${cp1y.toFixed(1)} ${cp2x.toFixed(1)},${cp2y.toFixed(1)} ${p2.x.toFixed(1)},${p2.y.toFixed(1)}`
  }
  return d
})

const navAreaPath = computed(() => {
  const curve = navCurvePath.value
  if (!curve) return ''
  const pts = navSvgPoints.value
  return `${curve} L${pts[pts.length - 1].x},${navChartHeight} L${pts[0].x},${navChartHeight} Z`
})

const goToDetail = (id) => {
  uni.navigateTo({ url: `/pages/stocks/detail?id=${id}` })
}

</script>

<style scoped>
.stocks-container {
  min-height: 100vh;
  background: #f0f2f5;
  padding: 0 24rpx;
}

/* ── Header ── */
.stocks-header {
  padding: 28rpx 0 16rpx;
}
.stocks-title {
  font-size: 44rpx;
  font-weight: 800;
  color: #1a1a2e;
  letter-spacing: 1rpx;
  display: block;
  font-family: 'SF Pro Display', 'PingFang SC', -apple-system, sans-serif;
}
.stocks-subtitle {
  font-size: 24rpx;
  color: #8c8c9a;
  margin-top: 6rpx;
  letter-spacing: 1rpx;
  display: block;
}

/* ── RS Search Cancel (取消按钮) ── */
.rs-search-cancel { flex-shrink: 0; padding: 8rpx 12rpx; cursor: pointer; margin-left: 12rpx; }
.rs-search-cancel-text { font-size: 28rpx; color: #4285f4; font-weight: 500; }

/* ── Info Bar ── */
.info-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12rpx 0 16rpx;
}
.info-date { font-size: 24rpx; color: #8c8c9a; }
.trading-badge {
  display: flex;
  align-items: center;
  gap: 6rpx;
  padding: 4rpx 16rpx;
  background: rgba(255, 59, 48, 0.08);
  border-radius: 20rpx;
}
.trading-dot { font-size: 16rpx; color: #ff3b30; animation: pulse 1.5s infinite; }
.trading-text { font-size: 22rpx; color: #ff3b30; font-weight: 500; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }

/* ── Table Header ── */
.table-header {
  display: flex;
  align-items: center;
  padding: 18rpx 20rpx;
  background: #ffffff;
  border-radius: 16rpx 16rpx 0 0;
  border-bottom: 2rpx solid #f0f0f2;
}
.th { font-size: 22rpx; color: #8c8c9a; font-weight: 600; }
.th-rank { width: 60rpx; text-align: center; }
.th-name { flex: 1; padding-left: 12rpx; }
.th-close { width: 140rpx; text-align: right; }
.th-pct { width: 160rpx; text-align: right; }
.th-rs { width: 80rpx; text-align: center; }

/* ── Stock List ── */
.stock-list {
  background: #ffffff;
  border-radius: 0 0 16rpx 16rpx;
  overflow: hidden;
  box-shadow: 0 2rpx 16rpx rgba(0, 0, 0, 0.04);
}
.stock-row {
  display: flex;
  align-items: center;
  padding: 22rpx 20rpx;
  border-bottom: 1rpx solid #f8f8fa;
}
.stock-row-alt { background: #fafbfc; }
.stock-row:last-child { border-bottom: none; }
.col { display: flex; flex-direction: column; justify-content: center; }
.col-rank { width: 60rpx; align-items: center; }
.col-name { flex: 1; padding-left: 12rpx; }
.col-close { width: 140rpx; align-items: flex-end; }
.col-pct { width: 160rpx; align-items: flex-end; }
.col-rs { width: 80rpx; align-items: center; }

.rank-num {
  font-size: 24rpx; color: #8c8c9a; font-weight: 600;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.rank-top { color: #ff3b30; font-weight: 800; }
.rank-high { color: #ff9500; font-weight: 700; }

.stock-name {
  font-size: 28rpx; font-weight: 600; color: #1a1a2e; line-height: 1.3;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.stock-code { font-size: 22rpx; color: #b0b0be; margin-top: 4rpx; font-family: 'SF Mono', 'Menlo', monospace; }

.close-price {
  font-size: 28rpx; font-weight: 600; color: #1a1a2e;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}

.change-badge {
  padding: 4rpx 14rpx; border-radius: 8rpx;
  display: inline-flex; align-items: center; justify-content: center;
}
.change-text {
  font-size: 24rpx; font-weight: 600;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.change-up { background: rgba(255, 59, 48, 0.1); }
.change-up .change-text { color: #ff3b30; }
.change-down { background: rgba(52, 199, 89, 0.1); }
.change-down .change-text { color: #34c759; }
.change-flat { background: rgba(142, 142, 147, 0.1); }
.change-flat .change-text { color: #8e8e93; }
.change-abs { font-size: 20rpx; color: #b0b0be; margin-top: 2rpx; text-align: right; }

.rs-badge {
  width: 60rpx; height: 44rpx; border-radius: 10rpx;
  display: flex; align-items: center; justify-content: center;
}
.rs-value {
  font-size: 24rpx; font-weight: 700; color: #ffffff;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.rs-hot { background: linear-gradient(135deg, #ff3b30, #ff6b5a); }
.rs-warm { background: linear-gradient(135deg, #ff9500, #ffb340); }
.rs-normal { background: linear-gradient(135deg, #f0b429, #d4981e); }
.rs-cool { background: linear-gradient(135deg, #8e8e93, #a8a8ae); }

/* ═══════════════════════════════════════════════════════
   VCP 策略样式
   ═══════════════════════════════════════════════════════ */

/* VCP 筛选器 — 胶囊搜索栏风格 */
.vcp-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 50;
  background: transparent;
}
.vcp-filters {
  margin: 8rpx 0 12rpx;
  position: relative;
  z-index: 60;
}
.vcp-search-section {
  margin-bottom: 12rpx;
  position: relative;
}
.vcp-search-section:last-of-type { margin-bottom: 0; }
.vcp-search-bar {
  display: flex;
  align-items: center;
}
.vcp-search-input-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  background: #ffffff;
  border-radius: 36rpx;
  padding: 16rpx 24rpx;
  border: 2rpx solid #e8e8ed;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.vcp-search-bar-focus .vcp-search-input-wrap {
  border-color: #4285f4;
  box-shadow: 0 2rpx 12rpx rgba(66, 133, 244, 0.15);
}
.vcp-search-icon { font-size: 28rpx; margin-right: 12rpx; flex-shrink: 0; }
.vcp-search-input {
  flex: 1;
  font-size: 28rpx;
  color: #1a1a2e;
  background: transparent;
  border: none;
  outline: none;
  line-height: 1.4;
}
.vcp-search-badge {
  background: #007aff;
  color: #fff;
  font-size: 20rpx;
  min-width: 32rpx;
  height: 32rpx;
  line-height: 32rpx;
  text-align: center;
  border-radius: 16rpx;
  padding: 0 8rpx;
  font-weight: 600;
  margin-left: 8rpx;
  flex-shrink: 0;
}
.vcp-search-clear { padding: 4rpx 8rpx; margin-left: 8rpx; flex-shrink: 0; cursor: pointer; }
.vcp-search-clear-icon { font-size: 32rpx; color: #b0b0be; font-weight: 500; }

/* 下拉选项列表 */
.vcp-dropdown {
  position: absolute;
  left: 0;
  right: 0;
  top: 100%;
  z-index: 100;
  margin-top: 8rpx;
  background: #ffffff;
  border: 2rpx solid #e8e8ed;
  border-radius: 16rpx;
  box-shadow: 0 8rpx 32rpx rgba(0, 0, 0, 0.1);
  overflow: hidden;
}
.vcp-dropdown-scroll {
  max-height: 400rpx;
}
.vcp-dropdown-item {
  display: flex;
  align-items: center;
  gap: 12rpx;
  padding: 18rpx 24rpx;
  cursor: pointer;
  transition: background 0.15s;
}
.vcp-dropdown-item:active { background: #f0f0f5; }
.vcp-dropdown-item-active { background: #f0f5ff; }
.vcp-dropdown-item-active .vcp-dropdown-text { color: #007aff; font-weight: 500; }
.vcp-dropdown-check {
  width: 36rpx;
  font-size: 26rpx;
  color: #007aff;
  font-weight: 700;
  text-align: center;
  flex-shrink: 0;
}
.vcp-dropdown-text { font-size: 28rpx; color: #3c3c43; }
.vcp-dropdown-empty {
  padding: 24rpx;
  text-align: center;
  font-size: 26rpx;
  color: #8e8e93;
}

/* 已选标签 */
.vcp-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10rpx;
  margin-top: 10rpx;
  padding: 0 8rpx;
}
.vcp-tag {
  display: inline-flex;
  align-items: center;
  padding: 8rpx 18rpx;
  background: #e8f0fe;
  color: #007aff;
  font-size: 24rpx;
  border-radius: 20rpx;
  cursor: pointer;
  font-weight: 500;
  transition: background 0.15s;
}
.vcp-tag:active { background: #d0e0f8; }

/* 清除全部 */
.vcp-clear-all {
  display: flex;
  justify-content: center;
  margin-top: 12rpx;
  padding: 8rpx 0;
}
.vcp-clear-all-text {
  font-size: 24rpx;
  color: #007aff;
  cursor: pointer;
  font-weight: 500;
}

/* VCP 表头 */
.vcp-table-header {
  display: flex;
  align-items: center;
  padding: 18rpx 16rpx;
  background: #ffffff;
  border-radius: 16rpx 16rpx 0 0;
  border-bottom: 2rpx solid #f0f0f2;
}
.vth { font-size: 22rpx; color: #8c8c9a; font-weight: 600; }
.vth-rank { width: 50rpx; text-align: center; }
.vth-name { flex: 1; padding-left: 8rpx; }
.vth-price { width: 120rpx; text-align: right; }
.vth-vcp { width: 110rpx; text-align: center; }
.vth-flow { width: 140rpx; text-align: right; }
.vth-action { width: 60rpx; text-align: center; }

/* VCP 行 */
.vcp-row {
  background: #ffffff;
  border-bottom: 1rpx solid #f8f8fa;
  cursor: pointer;
  transition: background-color 0.15s;
}
.vcp-row:last-child { border-bottom: none; }
.vcp-row-main {
  display: flex;
  align-items: center;
  padding: 18rpx 16rpx;
}
.vcp-col-rank { width: 50rpx; align-items: center; }
.vcp-col-name { flex: 1; padding-left: 8rpx; }
.vcp-col-price { width: 120rpx; align-items: flex-end; }
.vcp-col-vcp { width: 110rpx; align-items: center; }
.vcp-col-flow { width: 140rpx; align-items: flex-end; }
.vcp-col-action { width: 60rpx; align-items: center; }

/* 题材标签行 */
.vcp-row-concepts {
  display: flex;
  flex-wrap: wrap;
  gap: 8rpx;
  padding: 0 16rpx 14rpx 66rpx;
}
.concept-tag {
  font-size: 20rpx;
  color: #1677ff;
  background: rgba(22, 119, 255, 0.08);
  padding: 4rpx 14rpx;
  border-radius: 6rpx;
  line-height: 1.4;
}
.flow-val {
  font-size: 24rpx;
  font-weight: 500;
  font-family: 'SF Mono', 'Roboto Mono', 'Menlo', monospace;
}

/* VCP badge */
.vcp-badge {
  padding: 4rpx 12rpx; border-radius: 8rpx;
  display: inline-flex; align-items: center; justify-content: center;
}
.vcp-val {
  font-size: 22rpx; font-weight: 700; color: #ffffff;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.vcp-level-hot { background: linear-gradient(135deg, #ff3b30, #ff6b5a); }
.vcp-level-warm { background: linear-gradient(135deg, #ff9500, #ffb340); }
.vcp-level-normal { background: linear-gradient(135deg, #34c759, #5dd67a); }
.vcp-level-cool { background: linear-gradient(135deg, #8e8e93, #a8a8ae); }
.vcp-level-none { background: #e8e8ed; }
.vcp-level-none .vcp-val { color: #8c8c9a; }

/* EPS / 营收 数值 */
.eps-val {
  font-size: 24rpx; font-weight: 600; color: #1a1a2e;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.val-up { color: #ff3b30; }
.val-down { color: #34c759; }

/* 富途链接 */
.futu-link {
  display: inline-flex; align-items: center; justify-content: center;
  width: 52rpx; height: 44rpx; border-radius: 8rpx;
  background: rgba(66, 133, 244, 0.08);
  text-decoration: none;
  transition: background 0.15s;
}
.futu-link:hover { background: rgba(66, 133, 244, 0.18); }
.futu-icon { font-size: 24rpx; }

/* 展开行 */
.vcp-expand {
  padding: 12rpx 20rpx 18rpx 66rpx;
  background: #f8fafc;
  border-top: 1rpx solid #f0f0f2;
}
.vcp-expand-row {
  display: flex; gap: 12rpx; margin-bottom: 10rpx; align-items: baseline;
}
.vcp-expand-row:last-child { margin-bottom: 0; }
.vcp-expand-label {
  font-size: 22rpx; color: #8c8c9a; font-weight: 500; white-space: nowrap; min-width: 120rpx;
}
.vcp-expand-val {
  font-size: 22rpx; color: #4a4a5a; line-height: 1.5; flex: 1;
}
.vcp-concepts {
  overflow: hidden; text-overflow: ellipsis; display: -webkit-box;
  -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.vcp-business {
  overflow: hidden; text-overflow: ellipsis; display: -webkit-box;
  -webkit-line-clamp: 3; -webkit-box-orient: vertical;
}

/* 价投状态徽章 */
.value-status-badge {
  padding: 4rpx 14rpx; border-radius: 10rpx;
  display: inline-flex; align-items: center; justify-content: center;
}
.value-status-text { font-size: 22rpx; font-weight: 600; }
.value-status-holding { background: rgba(52, 199, 89, 0.12); }
.value-status-holding .value-status-text { color: #34c759; }
.value-status-watching { background: rgba(59, 130, 246, 0.1); }
.value-status-watching .value-status-text { color: #3b82f6; }

/* 价投 header — 标题和添加按钮 */
.value-header-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}
.value-add-btn {
  display: flex;
  align-items: center;
  gap: 6rpx;
  padding: 14rpx 24rpx;
  background: #1a1a2e;
  border-radius: 32rpx;
  cursor: pointer;
  transition: opacity 0.15s;
  flex-shrink: 0;
  margin-top: 8rpx;
}
.value-add-btn:active { opacity: 0.7; }
.value-add-icon {
  font-size: 28rpx; color: #ffffff; font-weight: 700;
  line-height: 1;
}
.value-add-text {
  font-size: 24rpx; color: #ffffff; font-weight: 600;
}

/* 价投展开行 — 删除按钮 */
.value-remove-row {
  margin-top: 16rpx;
  padding-top: 14rpx;
  border-top: 1rpx solid #f0f0f2;
  text-align: center;
  cursor: pointer;
}
.value-remove-text {
  font-size: 24rpx;
  color: #ef4444;
  font-weight: 500;
}

/* ═══════════════════════════════════════════════════════
   模拟仓样式
   ═══════════════════════════════════════════════════════ */

/* ── 净值概览卡 ── */
.sb-hero-card {
  background: #ffffff;
  border-radius: 20rpx;
  padding: 28rpx 28rpx 24rpx;
  margin: 16rpx 0 0;
  box-shadow: 0 2rpx 16rpx rgba(0, 0, 0, 0.05);
}
.sb-hero-top { margin-bottom: 8rpx; }
.sb-hero-since {
  font-size: 22rpx; color: #8c8c9a; font-weight: 500;
}
.sb-hero-body {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 24rpx;
}
.sb-hero-left { display: flex; flex-direction: column; }
.sb-nav-big {
  font-size: 64rpx; font-weight: 900; color: #1a1a2e; line-height: 1.1;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
  letter-spacing: -1rpx;
}
.sb-nav-down { color: #22c55e; }
.sb-nav-sub {
  font-size: 22rpx; color: #8c8c9a; margin-top: 6rpx; font-weight: 500;
}

/* 迷你净值曲线 → SVG 圆滑曲线 */
.sb-nav-chart {
  margin: 16rpx 0 24rpx;
}
.sb-nav-chart-inner {
  width: 100%; position: relative; overflow: hidden; border-radius: 12rpx;
  background: #fafbfc;
}
.sb-svg-chart {
  width: 100%; height: 100%; display: block;
}

/* 指标行 */
.sb-metric-row {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12rpx;
}
.sb-metric-item {
  background: #f5f7fa; border-radius: 14rpx;
  padding: 18rpx 20rpx;
  display: flex; flex-direction: column; gap: 4rpx;
}
.sb-metric-label { font-size: 22rpx; color: #8c8c9a; font-weight: 500; }
.sb-metric-val {
  font-size: 32rpx; font-weight: 800;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.metric-up { color: #ef4444; }
.metric-down { color: #22c55e; }
.metric-neutral { color: #1a1a2e; }

/* ── 观察池快照 ── */
.sb-snapshot {
  margin-top: 24rpx; padding: 0 4rpx;
}

/* ── 持仓分布环状图 ── */
.sb-pie-card {
  background: #ffffff;
  border-radius: 20rpx;
  padding: 24rpx 28rpx;
  margin-top: 24rpx;
  box-shadow: 0 2rpx 16rpx rgba(0, 0, 0, 0.05);
}
.sb-pie-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 20rpx;
}
.sb-pie-title { font-size: 30rpx; font-weight: 700; color: #1a1a2e; }
.sb-pie-sub { font-size: 22rpx; color: #8c8c9a; font-weight: 500; }
.sb-pie-body {
  display: flex; align-items: center; gap: 28rpx;
}
.sb-pie-svg {
  width: 240rpx; height: 240rpx; flex-shrink: 0;
}
.sb-pie-legend {
  flex: 1; display: flex; flex-direction: column; gap: 12rpx;
}
.sb-legend-item {
  display: flex; align-items: center; gap: 10rpx;
}
.sb-legend-dot {
  width: 16rpx; height: 16rpx; border-radius: 4rpx; flex-shrink: 0;
}
.sb-legend-name {
  font-size: 24rpx; color: #4a4a5a; flex: 1;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.sb-legend-pct {
  font-size: 24rpx; color: #1a1a2e; font-weight: 700;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}

/* ── 筛选+搜索栏 ── */
.sb-filter-bar {
  display: flex; align-items: center; gap: 12rpx;
  margin-top: 16rpx;
}
.sb-filter-chip {
  padding: 12rpx 24rpx;
  border-radius: 32rpx;
  background: #f5f7fa;
  border: 2rpx solid transparent;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}
.sb-filter-chip-active {
  background: #1a1a2e; border-color: #1a1a2e;
}
.sb-filter-chip-text {
  font-size: 24rpx; font-weight: 600; color: #6a6a7a;
}
.sb-filter-chip-active .sb-filter-chip-text {
  color: #ffffff;
}
.sb-search-wrap {
  flex: 1;
  display: flex; align-items: center; gap: 8rpx;
  background: #f5f7fa;
  border-radius: 32rpx;
  padding: 10rpx 20rpx;
  border: 2rpx solid transparent;
  transition: border-color 0.2s;
}
.sb-search-wrap:focus-within {
  border-color: #3b82f6;
}
.sb-search-icon {
  font-size: 24rpx; flex-shrink: 0;
}
.sb-search-input {
  flex: 1; font-size: 24rpx; color: #1a1a2e; background: transparent;
  border: none; outline: none;
}
.sb-search-clear {
  font-size: 24rpx; color: #b0b0be; cursor: pointer; flex-shrink: 0;
  padding: 0 4rpx;
}
.sb-snapshot-header {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 16rpx;
}
.sb-snapshot-title { font-size: 30rpx; font-weight: 700; color: #1a1a2e; }
.sb-snapshot-time { font-size: 22rpx; color: #b0b0be; }
.sb-snapshot-tags {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12rpx;
}
.sb-tag {
  border-radius: 16rpx; padding: 20rpx 16rpx;
  display: flex; flex-direction: column; align-items: center; gap: 6rpx;
  cursor: pointer; transition: all 0.2s; border: 2rpx solid transparent;
}
.sb-tag-active { border-color: #1a1a2e; box-shadow: 0 2rpx 12rpx rgba(0, 0, 0, 0.1); }
.sb-tag-label { font-size: 22rpx; font-weight: 600; }
.sb-tag-num {
  font-size: 36rpx; font-weight: 800;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.sb-tag-retain { background: #eff6ff; }
.sb-tag-retain .sb-tag-label { color: #3b82f6; }
.sb-tag-retain .sb-tag-num { color: #1a1a2e; }
.sb-tag-gray { background: #f3f4f6; }
.sb-tag-gray .sb-tag-label { color: #6b7280; }
.sb-tag-gray .sb-tag-num { color: #1a1a2e; }
.sb-tag-research { background: #faf5ff; }
.sb-tag-research .sb-tag-label { color: #a855f7; }
.sb-tag-research .sb-tag-num { color: #1a1a2e; }
.sb-tag-churn { background: #fef2f2; }
.sb-tag-churn .sb-tag-label { color: #ef4444; }
.sb-tag-churn .sb-tag-num { color: #1a1a2e; }

/* ── 股票卡片 ── */
.sb-stock-list { margin-top: 16rpx; }
.sb-stock-card {
  background: #ffffff;
  border-radius: 16rpx;
  padding: 24rpx;
  margin-bottom: 16rpx;
  box-shadow: 0 1rpx 8rpx rgba(0, 0, 0, 0.04);
  position: relative;
  cursor: pointer;
  transition: box-shadow 0.15s;
}
.sb-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16rpx;
  padding-bottom: 14rpx;
  border-bottom: 1rpx solid #f0f0f2;
}
.sb-card-name-row {
  display: flex; align-items: baseline; gap: 4rpx;
}
.sb-stock-name { font-size: 32rpx; font-weight: 800; color: #1a1a2e; }
.sb-stock-code { font-size: 24rpx; color: #8c8c9a; font-weight: 500; }

.sb-status-badge {
  padding: 6rpx 16rpx;
  border-radius: 16rpx;
  display: inline-flex;
}
.sb-status-text { font-size: 22rpx; font-weight: 600; }
.sb-status-holding { background: #dcfce7; }
.sb-status-holding .sb-status-text { color: #16a34a; }
.sb-status-watching { background: #dbeafe; }
.sb-status-watching .sb-status-text { color: #2563eb; }
.sb-status-exited { background: #f3f4f6; }
.sb-status-exited .sb-status-text { color: #6b7280; }

/* 评分 */
.sb-score-row {
  display: flex; align-items: baseline; gap: 6rpx; margin-bottom: 10rpx;
}
.sb-score-label { font-size: 24rpx; color: #8c8c9a; font-weight: 500; }
.sb-score-big {
  font-size: 42rpx; font-weight: 900;
  font-family: 'SF Pro Display', 'DIN Alternate', -apple-system, sans-serif;
}
.sb-score-high { color: #1a1a2e; }
.sb-score-mid { color: #f59e0b; }
.sb-score-low { color: #ef4444; }
.sb-score-max { font-size: 24rpx; color: #b0b0be; font-weight: 500; }

/* Verdict */
.sb-verdict {
  font-size: 26rpx; color: #4a4a5a; line-height: 1.6; display: block;
  margin-bottom: 12rpx;
}

/* 动作标签行 */
.sb-action-row {
  display: flex; align-items: center; gap: 10rpx;
}
.sb-disc-badge { padding: 4rpx 14rpx; border-radius: 8rpx; }
.sb-disc-text { font-size: 22rpx; font-weight: 600; }
.sb-disc-retain { background: rgba(59, 130, 246, 0.1); }
.sb-disc-retain .sb-disc-text { color: #3b82f6; }
.sb-disc-gray { background: rgba(142, 142, 147, 0.1); }
.sb-disc-gray .sb-disc-text { color: #8e8e93; }
.sb-disc-research { background: rgba(168, 85, 247, 0.1); }
.sb-disc-research .sb-disc-text { color: #a855f7; }
.sb-disc-churn { background: rgba(239, 68, 68, 0.1); }
.sb-disc-churn .sb-disc-text { color: #ef4444; }
.sb-meta-info { display: flex; align-items: center; gap: 6rpx; }
.sb-analysis-count { font-size: 22rpx; color: #8c8c9a; font-weight: 500; }
.sb-analysis-dot { font-size: 22rpx; color: #d0d0d8; }
.sb-analysis-date { font-size: 22rpx; color: #b0b0be; }

.sb-card-bottom { margin-top: 10rpx; }
.sb-shares { font-size: 22rpx; color: #8c8c9a; }

/* 持仓比例进度条 */
.sb-position-bar-wrap {
  height: 6rpx;
  background: #f0f0f2;
  border-radius: 3rpx;
  overflow: hidden;
  margin-bottom: 8rpx;
}
.sb-position-bar {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #60a5fa);
  border-radius: 3rpx;
  min-width: 4rpx;
  transition: width 0.3s ease;
}

/* 持仓+留存 高亮卡片 */
.sb-card-highlight {
  border: 2rpx solid #3b82f6;
  background: linear-gradient(180deg, #f0f7ff 0%, #ffffff 40%);
  box-shadow: 0 2rpx 16rpx rgba(59, 130, 246, 0.12);
}
.sb-highlight-bar {
  display: flex;
  align-items: center;
  gap: 8rpx;
  margin-bottom: 12rpx;
  padding-bottom: 10rpx;
}
.sb-highlight-icon {
  font-size: 16rpx;
  color: #3b82f6;
  animation: pulse 1.5s infinite;
}
.sb-highlight-text {
  font-size: 22rpx;
  color: #3b82f6;
  font-weight: 600;
  letter-spacing: 1rpx;
}

.sb-card-arrow {
  position: absolute;
  right: 24rpx;
  top: 50%;
  transform: translateY(-50%);
}
.arrow-icon { font-size: 36rpx; color: #d0d0d8; font-weight: 300; }

/* ═══════════════════════════════════════════════════════════
   PC / Tablet 适配 (≥768px)
   ═══════════════════════════════════════════════════════════ */
@media screen and (min-width: 768px) {
  .stocks-container {
    max-width: 860px;
    margin: 0 auto;
    padding: 0 24px;
  }

  .stocks-header { padding: 24px 0 12px; }
  .stocks-title { font-size: 26px; letter-spacing: 0.5px; }
  .stocks-subtitle { font-size: 13px; margin-top: 4px; }

  .rs-search-cancel { padding: 5px 8px; margin-left: 8px; }
  .rs-search-cancel-text { font-size: 15px; }

  .info-bar { padding: 8px 0 12px; }
  .info-date { font-size: 13px; }
  .trading-badge { gap: 4px; padding: 2px 10px; border-radius: 12px; }
  .trading-dot { font-size: 9px; }
  .trading-text { font-size: 12px; }

  .table-header { padding: 12px 16px; border-radius: 12px 12px 0 0; border-bottom-width: 1px; }
  .th { font-size: 12px; }
  .th-rank { width: 36px; }
  .th-name { padding-left: 8px; }
  .th-close { width: 90px; }
  .th-pct { width: 110px; }
  .th-rs { width: 50px; }

  .stock-list { border-radius: 0 0 12px 12px; box-shadow: 0 1px 12px rgba(0, 0, 0, 0.05); }
  .stock-row { padding: 14px 16px; transition: background-color 0.15s; }
  .stock-row:hover { background-color: #f5f7fa; }

  .col-rank { width: 36px; }
  .col-name { padding-left: 8px; }
  .col-close { width: 90px; }
  .col-pct { width: 110px; }
  .col-rs { width: 50px; }

  .rank-num { font-size: 13px; }
  .stock-name { font-size: 15px; }
  .stock-code { font-size: 12px; margin-top: 2px; }
  .close-price { font-size: 15px; }
  .change-badge { padding: 2px 10px; border-radius: 6px; }
  .change-text { font-size: 13px; }
  .change-abs { font-size: 11px; }
  .rs-badge { width: 38px; height: 26px; border-radius: 6px; }
  .rs-value { font-size: 13px; }

  /* 模拟仓 PC 适配 */
  .sb-hero-card { padding: 20px 22px 18px; border-radius: 14px; margin-top: 12px; }
  .sb-hero-since { font-size: 12px; }
  .sb-nav-big { font-size: 40px; }
  .sb-nav-sub { font-size: 12px; }
  .sb-mini-chart, .sb-nav-chart-inner { height: 100px !important; }
  .sb-nav-chart { margin: 10px 0 18px; }
  .sb-metric-row { gap: 8px; grid-template-columns: 1fr 1fr 1fr 1fr; }
  .sb-metric-item { padding: 12px 16px; border-radius: 10px; }
  .sb-metric-label { font-size: 12px; }
  .sb-metric-val { font-size: 18px; }

  .sb-snapshot { margin-top: 18px; }
  .sb-snapshot-title { font-size: 16px; }
  .sb-snapshot-time { font-size: 12px; }
  .sb-snapshot-tags { gap: 8px; grid-template-columns: 1fr 1fr 1fr 1fr; }
  .sb-tag { padding: 14px 12px; border-radius: 10px; }
  .sb-tag-label { font-size: 12px; }
  .sb-tag-num { font-size: 22px; }

  /* 持仓分布环状图 PC */
  .sb-pie-card { padding: 18px 22px; border-radius: 14px; margin-top: 18px; }
  .sb-pie-title { font-size: 16px; }
  .sb-pie-sub { font-size: 12px; }
  .sb-pie-body { gap: 20px; }
  .sb-pie-svg { width: 140px; height: 140px; }
  .sb-pie-legend { gap: 8px; }
  .sb-legend-dot { width: 10px; height: 10px; border-radius: 3px; }
  .sb-legend-name { font-size: 13px; }
  .sb-legend-pct { font-size: 13px; }

  /* 筛选搜索栏 PC */
  .sb-filter-bar { gap: 8px; margin-top: 12px; }
  .sb-filter-chip { padding: 7px 16px; border-radius: 20px; border-width: 1px; }
  .sb-filter-chip-text { font-size: 13px; }
  .sb-search-wrap { padding: 7px 14px; border-radius: 20px; border-width: 1px; gap: 6px; }
  .sb-search-icon { font-size: 13px; }
  .sb-search-input { font-size: 13px; }
  .sb-search-clear { font-size: 13px; }

  .sb-stock-list { margin-top: 12px; }
  .sb-stock-card { padding: 18px; margin-bottom: 10px; border-radius: 12px; transition: box-shadow 0.15s; }
  .sb-stock-card:hover { box-shadow: 0 2px 16px rgba(0, 0, 0, 0.08); }
  .sb-card-top { margin-bottom: 12px; padding-bottom: 10px; }
  .sb-stock-name { font-size: 17px; }
  .sb-stock-code { font-size: 13px; }
  .sb-status-badge { padding: 3px 10px; border-radius: 10px; }
  .sb-status-text { font-size: 12px; }
  .sb-score-label { font-size: 13px; }
  .sb-score-big { font-size: 26px; }
  .sb-score-max { font-size: 13px; }
  .sb-verdict { font-size: 14px; }
  .sb-disc-badge { padding: 2px 10px; border-radius: 5px; }
  .sb-disc-text { font-size: 12px; }
  .sb-analysis-count { font-size: 12px; }
  .sb-analysis-dot { font-size: 12px; }
  .sb-analysis-date { font-size: 12px; }
  .sb-shares { font-size: 12px; }
  .sb-position-bar-wrap { height: 4px; margin-bottom: 6px; }
  .sb-card-highlight { border-width: 1px; }
  .sb-highlight-bar { margin-bottom: 8px; padding-bottom: 8px; gap: 5px; }
  .sb-highlight-icon { font-size: 9px; }
  .sb-highlight-text { font-size: 12px; }
  .arrow-icon { font-size: 22px; }

  /* VCP 策略 PC 适配 */
  .vcp-filters { margin: 6px 0 10px; }
  .vcp-search-section { margin-bottom: 8px; }
  .vcp-search-input-wrap { border-radius: 22px; padding: 10px 18px; border-width: 1px; }
  .vcp-search-bar-focus .vcp-search-input-wrap { box-shadow: 0 1px 8px rgba(66, 133, 244, 0.15); }
  .vcp-search-icon { font-size: 15px; margin-right: 8px; }
  .vcp-search-input { font-size: 14px; }
  .vcp-search-badge { font-size: 11px; min-width: 18px; height: 18px; line-height: 18px; padding: 0 5px; border-radius: 10px; margin-left: 6px; }
  .vcp-search-clear-icon { font-size: 18px; }
  .vcp-dropdown { margin-top: 4px; border-radius: 10px; border-width: 1px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1); }
  .vcp-dropdown-scroll { max-height: 220px; }
  .vcp-dropdown-item { padding: 10px 16px; gap: 8px; }
  .vcp-dropdown-item:hover { background: #f0f0f5; }
  .vcp-dropdown-check { width: 20px; font-size: 14px; }
  .vcp-dropdown-text { font-size: 14px; }
  .vcp-dropdown-empty { font-size: 13px; padding: 14px; }
  .vcp-tags { gap: 6px; margin-top: 6px; padding: 0 6px; }
  .vcp-tag { padding: 4px 12px; font-size: 12px; border-radius: 12px; }
  .vcp-tag:hover { background: #d0e0f8; }
  .vcp-clear-all { margin-top: 8px; }
  .vcp-clear-all-text { font-size: 13px; }

  .vcp-table-header { padding: 12px 12px; border-radius: 12px 12px 0 0; border-bottom-width: 1px; }
  .vth { font-size: 12px; }
  .vth-rank { width: 32px; }
  .vth-name { padding-left: 6px; }
  .vth-price { width: 80px; }
  .vth-vcp { width: 70px; }
  .vth-flow { width: 90px; }
  .vth-action { width: 40px; }

  .vcp-row-main { padding: 12px 12px; }
  .vcp-row:hover { background-color: #f5f7fa; }
  .vcp-col-rank { width: 32px; }
  .vcp-col-name { padding-left: 6px; }
  .vcp-col-price { width: 80px; }
  .vcp-col-vcp { width: 70px; }
  .vcp-col-flow { width: 90px; }
  .vcp-col-action { width: 40px; }

  .vcp-badge { padding: 2px 8px; border-radius: 5px; }
  .vcp-val { font-size: 12px; }
  .flow-val { font-size: 13px; }
  .eps-val { font-size: 13px; }
  .futu-link { width: 32px; height: 26px; border-radius: 5px; }
  .futu-icon { font-size: 14px; }
  .vcp-row-concepts { padding: 0 12px 10px 44px; gap: 5px; }
  .concept-tag { font-size: 11px; padding: 2px 8px; border-radius: 4px; }
  .vcp-expand { padding: 8px 14px 12px 46px; }
  .vcp-expand-label { font-size: 12px; min-width: 72px; }
  .vcp-expand-val { font-size: 12px; }

  /* 价投状态徽章 PC */
  .value-status-badge { padding: 2px 10px; border-radius: 6px; }
  .value-status-text { font-size: 12px; }

  /* 价投添加按钮 PC */
  .value-add-btn { padding: 8px 16px; border-radius: 20px; gap: 4px; margin-top: 4px; }
  .value-add-icon { font-size: 15px; }
  .value-add-text { font-size: 13px; }

  /* 价投删除行 PC */
  .value-remove-row { margin-top: 10px; padding-top: 10px; }
  .value-remove-text { font-size: 13px; }

}

</style>
