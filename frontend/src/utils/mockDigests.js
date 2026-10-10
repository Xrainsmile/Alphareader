// ─────────────────────────────────────────────────────────────
// 本地静态预览用 Mock 数据（仅 VITE_MOCK=1 时生效）
// 用途：不启动后端/数据库，直接预览 reports 页面的时间标题与筛选交互
// 上线前无需删除：生产构建不设置 VITE_MOCK，此分支不会被打包生效
// ─────────────────────────────────────────────────────────────

function toDateStr(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function dayOffset(n) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return toDateStr(d)
}

function at(dateStr, hour, minute = 0) {
  return `${dateStr}T${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}:00`
}

// 时段定义：label / 显示名 / 起止小时
const PERIODS = [
  { label: 'morning', display: '早间简报', from: [6, 0], to: [11, 0] },
  { label: 'midday', display: '午间简报', from: [11, 0], to: [14, 0] },
  { label: 'evening', display: '晚间简报', from: [14, 0], to: [20, 0] },
  { label: 'night', display: '夜间简报', from: [20, 0], to: [24, 0] },
]

// 各时段的内容模板（按日期错开，制造真实感）
const TEMPLATES = {
  morning: {
    period_summary: '隔夜海外风险偏好回升，美股科技板块领涨；国内早间政策面平稳，市场关注点在流动性边际变化与产业链订单验证。',
    what_changed: '美联储官员表态偏鸽，人民币中间价上调，A50 期指高开。',
    cross_event_signals: [
      { title: '海外流动性预期边际转松', summary: '美债 10Y 回落至 3.9% 下方，美元指数走弱，外资对新兴市场配置意愿回升。' },
      { title: 'AI 算力订单持续验证', summary: '两家北美云厂商上修资本开支指引，光模块与液冷链条订单能见度延长至明年上半年。' },
    ],
    must_know: [
      {
        event_id: 1001,
        title: '美联储 9 月会议纪要：多数委员支持年内再降息一次',
        confidence: 'high',
        latest_change: '新增：纪要显示分歧收窄，两名此前偏鹰的委员转为中性。',
        why_important: '直接决定四季度美元流动性，对 A 股外资流向与港股估值有领先意义。',
        watch_next: '关注本周 PCE 数据与非农修正值。',
        sources: ['Reuters', 'Bloomberg', 'Wind'],
      },
      {
        event_id: 1002,
        title: '北美云厂商 Q3 资本开支指引上修，AI 算力链受益',
        confidence: 'medium',
        latest_change: '资本开支同比指引由 28% 上修至 35%。',
        why_important: '确认算力景气度未见顶，映射至国内光模块、PCB、液冷环节。',
        watch_next: '跟踪国内厂商三季度订单与产能利用率披露。',
        sources: ['公司公告', '第一财经'],
      },
      {
        event_id: 1003,
        title: '央行公开市场净投放 1200 亿元，跨季资金面平稳',
        confidence: 'high',
        latest_change: '7 天逆回购利率维持不变。',
        why_important: '季末流动性无虞，短端利率稳定利好高股息与银行板块。',
        watch_next: '关注下旬税期资金面波动。',
        sources: ['中国人民银行', '财新'],
      },
    ],
    worth_watching: [
      { event_id: 1004, title: '9 月出口数据超预期，机电产品贡献主要增量', sources: ['海关总署'] },
      { event_id: 1005, title: '光伏行业协会召开反内卷座谈会', sources: ['证券时报'] },
      { event_id: 1006, title: '某新能源车企发布新一代平台，续航提升 12%', sources: ['公司发布会'] },
    ],
    ongoing_updates: [
      { event_id: 1007, title: '地产销售同环比继续磨底，政策效果待观察', note: '持续 6 天' },
    ],
    quiet_topics: [
      { event_id: 1008, title: '欧盟对华电动车反补贴谈判', note: '2 天无进展' },
    ],
    upcoming: [
      { time: '09:30', item: '9 月 CPI / PPI 公布' },
      { time: '10:00', item: '国新办就外贸情况举行发布会' },
      { time: '20:30', item: '美国 9 月 PCE 物价指数' },
    ],
  },
  midday: {
    period_summary: '上午市场分化，指数小幅收涨但个股赚钱效应一般；半导体与算力方向活跃，消费与地产链条继续调整。',
    what_changed: '算力租赁概念快速拉升，盘中多股涨停；两市成交额环比缩量 8%。',
    cross_event_signals: [
      { title: '资金向 AI 主线进一步集中', summary: '成交额前 20 个股中 AI 相关占 9 席，虹吸效应明显。' },
      { title: '顺周期板块缺乏催化', summary: '商品期货多数回落，钢铁、建材板块资金净流出。' },
    ],
    must_know: [
      {
        event_id: 1010,
        title: '两部门发文推进算力基础设施互联互通',
        confidence: 'high',
        latest_change: '新增：明确 2027 年建成全国一体化算力网目标。',
        why_important: '政策性订单落地，直接利好 IDC、算力调度与网络设备商。',
        watch_next: '关注后续地方配套补贴细则。',
        sources: ['国家发改委', '工信部'],
      },
      {
        event_id: 1011,
        title: '算力租赁龙头盘中涨停，板块成交额创年内新高',
        confidence: 'medium',
        latest_change: '板块单日成交额较 20 日均值放大 2.3 倍。',
        why_important: '情绪指标进入过热区间，短期波动风险上升。',
        watch_next: '观察次日是否放量滞涨。',
        sources: ['东方财富', '同花顺'],
      },
    ],
    worth_watching: [
      { event_id: 1012, title: '北向资金半日净流入 32 亿元，集中于电力设备', sources: ['港交所'] },
      { event_id: 1013, title: '人民币兑美元中间价上调 86 点', sources: ['中国外汇交易中心'] },
    ],
    ongoing_updates: [
      { event_id: 1014, title: '消费复苏数据仍偏弱，白酒批价小幅下行', note: '持续 3 天' },
    ],
    quiet_topics: [],
    upcoming: [
      { time: '13:30', item: '某算力厂商三季度业绩说明会' },
      { time: '15:00', item: '商务部例行新闻发布会' },
    ],
  },
  evening: {
    period_summary: '下午市场冲高回落，成长板块涨幅收窄；尾盘金融股拉升护盘，指数勉强收红。港股同步走弱，南向资金转为净卖出。',
    what_changed: '成交额未能有效放大，题材接力失败；两融余额小幅回落。',
    cross_event_signals: [
      { title: '量能不足制约反弹高度', summary: '全市场成交额 1.62 万亿，较昨日缩量 6%，反弹缺乏增量资金。' },
      { title: '外部扰动再起', summary: '盘中传出台海相关消息，军工板块异动，风险偏好短暂承压。' },
    ],
    must_know: [
      {
        event_id: 1020,
        title: '9 月社融数据公布：新增 3.2 万亿，略超市场预期',
        confidence: 'high',
        latest_change: '政府债券为主要支撑，企业中长贷同比少增。',
        why_important: '信用扩张结构仍偏政策驱动，实体融资需求待强化。',
        watch_next: '关注 10 月信贷投放节奏与专项债使用进度。',
        sources: ['中国人民银行', 'Wind'],
      },
      {
        event_id: 1021,
        title: '证监会就程序化交易监管征求意见',
        confidence: 'medium',
        latest_change: '新增：拟对高频交易提高报单费。',
        why_important: '量化私募策略收益受影响，可能压低中小盘流动性。',
        watch_next: '关注正式稿落地时间与豁免范围。',
        sources: ['证监会', '财新'],
      },
    ],
    worth_watching: [
      { event_id: 1022, title: '南向资金由净买入转为净卖出 18 亿港元', sources: ['港交所'] },
      { event_id: 1023, title: '国际油价回落 2.1%，布伦特跌破 78 美元', sources: ['ICE'] },
      { event_id: 1024, title: '某地产龙头公告债务重组进展', sources: ['公司公告'] },
    ],
    ongoing_updates: [
      { event_id: 1025, title: '美国大选选情胶着，辩论后民调小幅波动', note: '持续 9 天' },
    ],
    quiet_topics: [
      { event_id: 1026, title: '医药集采第十批报量', note: '4 天无进展' },
    ],
    upcoming: [
      { time: '21:00', item: '欧洲央行行长讲话' },
      { time: '次日 04:00', item: '美联储官员密集发声' },
    ],
  },
  night: {
    period_summary: '夜间海外市场波动加大，美股三大指数低开后分化；中概股多数下跌，美元指数小幅走强，黄金回落。',
    what_changed: '费城半导体指数跌 1.4%，英伟达回调；避险情绪小幅升温。',
    cross_event_signals: [
      { title: '海外科技股高位震荡', summary: 'AI 权重股财报前资金趋于谨慎，隐含波动率抬升。' },
      { title: '大宗商品普跌', summary: '黄金、铜同步回落，反映实际利率上行预期。' },
    ],
    must_know: [
      {
        event_id: 1030,
        title: '美股科技巨头财报前瞻：市场预期营收增速放缓至 14%',
        confidence: 'medium',
        latest_change: '分析师近一周下修盈利预测 1.2 个百分点。',
        why_important: '将检验 AI 商业化兑现节奏，影响全球科技估值锚。',
        watch_next: '关注资本开支与云业务增速两项指引。',
        sources: ['FactSet', 'Bloomberg'],
      },
      {
        event_id: 1031,
        title: '国际金价回落至 2580 美元/盎司，避险需求降温',
        confidence: 'low',
        latest_change: '单日跌幅 1.1%，为近三周最大。',
        why_important: '贵金属板块短期承压，关注实际利率路径。',
        watch_next: '关注美国实际利率与央行购金数据。',
        sources: ['LBMA', 'Wind'],
      },
    ],
    worth_watching: [
      { event_id: 1032, title: '美债 10Y 收益率回升至 3.97%', sources: ['Bloomberg'] },
      { event_id: 1033, title: '中概股指数跌 1.8%，教育股领跌', sources: ['纳斯达克'] },
    ],
    ongoing_updates: [],
    quiet_topics: [
      { event_id: 1034, title: '中东局势', note: '1 天无进展' },
    ],
    upcoming: [
      { time: '次日 07:00', item: '日本央行议息会议纪要' },
      { time: '次日 09:00', item: '中国 9 月贸易数据' },
    ],
  },
}

// 每天包含的时段：今天 4 个全天、昨天 3 个、前天 2 个、大前天 1 个
const DAY_PLAN = [
  { offset: 0, periods: ['morning', 'midday', 'evening', 'night'] },
  { offset: 1, periods: ['morning', 'midday', 'evening'] },
  { offset: 2, periods: ['morning', 'evening'] },
  { offset: 3, periods: ['morning', 'midday'] },
  { offset: 4, periods: ['evening'] },
]

let seq = 1

function buildDigest(dateStr, period) {
  const t = TEMPLATES[period]
  const meta = PERIODS.find((p) => p.label === period)
  const id = seq++
  // 事件数 / 变化数按日期时段做小幅扰动，避免所有卡片完全一致
  const jitter = (id * 7) % 5
  return {
    id,
    digest_date: dateStr,
    period_label: period,
    period_display: meta.display,
    period_start: at(dateStr, meta.from[0], meta.from[1]),
    period_end: at(dateStr, meta.to[0] === 24 ? 23 : meta.to[0], meta.to[0] === 24 ? 59 : meta.to[1]),
    event_count: (t.must_know.length + t.worth_watching.length + t.ongoing_updates.length) + jitter,
    material_update_count: 3 + jitter,
    schema_version: 2,
    structured_content: {
      period_summary: t.period_summary,
      what_changed: t.what_changed,
      cross_event_signals: t.cross_event_signals,
      must_know: t.must_know.map((e) => ({ ...e, event_id: e.event_id + jitter * 100 })),
      worth_watching: t.worth_watching,
      ongoing_updates: t.ongoing_updates,
      quiet_topics: t.quiet_topics,
      upcoming: t.upcoming,
    },
  }
}

const ALL = []
for (const day of DAY_PLAN) {
  const dateStr = dayOffset(day.offset)
  for (const p of day.periods) {
    ALL.push(buildDigest(dateStr, p))
  }
}
// 时间倒序（与后端一致）
ALL.sort((a, b) => (a.period_start < b.period_start ? 1 : -1))

/**
 * 模拟后端 GET /api/v1/digests/ 的返回体（已解包的 items 数组）
 * @param {number} days 最近 N 天
 * @param {string} targetDate 精确日期 YYYY-MM-DD，留空按 days 过滤
 */
export function mockDigests(days = 7, targetDate = '') {
  const list = targetDate
    ? ALL.filter((d) => d.digest_date === targetDate)
    : (() => {
        const since = dayOffset(days - 1)
        return ALL.filter((d) => d.digest_date >= since)
      })()
  return Promise.resolve(list)
}
