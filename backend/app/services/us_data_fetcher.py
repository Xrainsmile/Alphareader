"""Alphareader — 美股数据获取模块（异步版，多源架构）。

职责：
  - 通过 **腾讯财经** 获取美股前复权日线行情（OHLCV）— 主力数据源
  - 通过 **yfinance** 作为 fallback（仅海外服务器可用）
  - 数据自洽性校验（写入 DB 前自动检查）
  - 持久化到 PostgreSQL（stock_daily_quote 表，market='US'）
  - 智能缓存：当天已有数据则跳过下载

数据源优先级：
  1. 腾讯财经 API — 主力源（国内 CDN，需要带交易所后缀 .OQ/.N）
  2. yfinance — fallback（国内服务器无法访问 Yahoo Finance）
  3. 新浪财经 — 最后一天实时行情抽样验证

内存优化：
  - 分批拉取 + 分批写入 DB（与 A 股 data_fetcher 相同策略）
  - 4GB 服务器友好
"""

from __future__ import annotations

import asyncio
import gc
import json
import logging
import random
import re
import urllib.request
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy import func, select, text as sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import async_session
from app.models.stock import StockDailyQuote

logger = logging.getLogger("alphareader.us_data_fetcher")

# ────────── 配置 ──────────
LOOKBACK_DAYS = 365             # 回溯天数（约 252 个交易日）
MAX_RETRIES = 3                 # 单只股票最大重试次数
RETRY_DELAY = 2                 # 重试间隔（秒）
BATCH_SIZE = 100                # 每批写入 DB 的股票数量

# 交叉验证配置
CROSS_VALIDATE_SAMPLE_SIZE = 10  # 每次增量更新后，抽样验证的股票数量
CROSS_VALIDATE_TOLERANCE = 0.02  # 收盘价偏差容忍度（2%）
SANITY_MAX_PCT_CHANGE = 50.0     # 单日涨跌幅上限（50%，美股无涨跌停但过大则异常）
SANITY_MIN_PRICE = 0.001         # 最低合理价格

# 美股活跃标的列表
US_UNIVERSE_URL = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/all/all_tickers.txt"


# ============================================================
# 1. 获取美股股票列表
# ============================================================

def _sync_fetch_us_stock_list() -> pd.DataFrame:
    """获取美股活跃标的列表。

    策略：直接使用内置的 S&P500 全量成分股列表（~503 只）。
    容器内无法访问 Wikipedia 等境外网站，因此改为本地内置。
    """
    return _get_sp500_tickers()


def _get_sp500_tickers() -> pd.DataFrame:
    """内置 S&P500 成分股列表（2026-02 基准，~503 只）。"""
    tickers = {
        # --- A ---
        "MMM": "3M",
        "AOS": "A. O. Smith",
        "ABT": "Abbott Laboratories",
        "ABBV": "AbbVie",
        "ACN": "Accenture",
        "ADBE": "Adobe Inc.",
        "AMD": "Advanced Micro Devices",
        "AES": "AES Corporation",
        "AFL": "Aflac",
        "A": "Agilent Technologies",
        "APD": "Air Products",
        "ABNB": "Airbnb",
        "AKAM": "Akamai Technologies",
        "ALB": "Albemarle Corporation",
        "ARE": "Alexandria Real Estate Equities",
        "ALGN": "Align Technology",
        "ALLE": "Allegion",
        "LNT": "Alliant Energy",
        "ALL": "Allstate",
        "GOOGL": "Alphabet Inc. (Class A)",
        "GOOG": "Alphabet Inc. (Class C)",
        "MO": "Altria",
        "AMZN": "Amazon.com",
        "AMCR": "Amcor",
        "AEE": "Ameren",
        "AEP": "American Electric Power",
        "AXP": "American Express",
        "AIG": "American International Group",
        "AMT": "American Tower",
        "AWK": "American Water Works",
        "AMP": "Ameriprise Financial",
        "AME": "Ametek",
        "AMGN": "Amgen",
        "APH": "Amphenol",
        "ADI": "Analog Devices",
        "AON": "Aon plc",
        "APA": "APA Corporation",
        "APO": "Apollo Global Management",
        "AAPL": "Apple Inc.",
        "AMAT": "Applied Materials",
        "APP": "AppLovin",
        "APTV": "Aptiv",
        "ACGL": "Arch Capital Group",
        "ADM": "Archer Daniels Midland",
        "ARES": "Ares Management",
        "ANET": "Arista Networks",
        "AJG": "Arthur J. Gallagher & Co.",
        "AIZ": "Assurant",
        "T": "AT&T",
        "ATO": "Atmos Energy",
        "ADSK": "Autodesk",
        "ADP": "Automatic Data Processing",
        "AZO": "AutoZone",
        "AVB": "AvalonBay Communities",
        "AVY": "Avery Dennison",
        "AXON": "Axon Enterprise",
        # --- B ---
        "BKR": "Baker Hughes",
        "BALL": "Ball Corporation",
        "BAC": "Bank of America",
        "BAX": "Baxter International",
        "BDX": "Becton Dickinson",
        "BRK-B": "Berkshire Hathaway",
        "BBY": "Best Buy",
        "TECH": "Bio-Techne",
        "BIIB": "Biogen",
        "BLK": "BlackRock",
        "BX": "Blackstone Inc.",
        "XYZ": "Block, Inc.",
        "BK": "BNY Mellon",
        "BA": "Boeing",
        "BKNG": "Booking Holdings",
        "BSX": "Boston Scientific",
        "BMY": "Bristol Myers Squibb",
        "AVGO": "Broadcom Inc.",
        "BR": "Broadridge Financial Solutions",
        "BRO": "Brown & Brown",
        "BF-B": "Brown-Forman",
        "BLDR": "Builders FirstSource",
        "BG": "Bunge Global",
        "BXP": "BXP, Inc.",
        # --- C ---
        "CHRW": "C.H. Robinson",
        "CDNS": "Cadence Design Systems",
        "CPT": "Camden Property Trust",
        "CPB": "Campbell's Company",
        "COF": "Capital One",
        "CAH": "Cardinal Health",
        "CCL": "Carnival",
        "CARR": "Carrier Global",
        "CVNA": "Carvana",
        "CAT": "Caterpillar Inc.",
        "CBOE": "Cboe Global Markets",
        "CBRE": "CBRE Group",
        "CDW": "CDW Corporation",
        "COR": "Cencora",
        "CNC": "Centene Corporation",
        "CNP": "CenterPoint Energy",
        "CF": "CF Industries",
        "CRL": "Charles River Laboratories",
        "SCHW": "Charles Schwab Corporation",
        "CHTR": "Charter Communications",
        "CVX": "Chevron Corporation",
        "CMG": "Chipotle Mexican Grill",
        "CB": "Chubb Limited",
        "CHD": "Church & Dwight",
        "CIEN": "Ciena",
        "CI": "Cigna",
        "CINF": "Cincinnati Financial",
        "CTAS": "Cintas",
        "CSCO": "Cisco",
        "C": "Citigroup",
        "CFG": "Citizens Financial Group",
        "CLX": "Clorox",
        "CME": "CME Group",
        "CMS": "CMS Energy",
        "KO": "Coca-Cola Company",
        "CTSH": "Cognizant",
        "COIN": "Coinbase",
        "CL": "Colgate-Palmolive",
        "CMCSA": "Comcast",
        "FIX": "Comfort Systems USA",
        "CAG": "Conagra Brands",
        "COP": "ConocoPhillips",
        "ED": "Consolidated Edison",
        "STZ": "Constellation Brands",
        "CEG": "Constellation Energy",
        "COO": "Cooper Companies",
        "CPRT": "Copart",
        "GLW": "Corning Inc.",
        "CPAY": "Corpay",
        "CTVA": "Corteva",
        "CSGP": "CoStar Group",
        "COST": "Costco",
        "CTRA": "Coterra",
        "CRH": "CRH plc",
        "CRWD": "CrowdStrike",
        "CCI": "Crown Castle",
        "CSX": "CSX Corporation",
        "CMI": "Cummins",
        "CVS": "CVS Health",
        # --- D ---
        "DHR": "Danaher Corporation",
        "DRI": "Darden Restaurants",
        "DDOG": "Datadog",
        "DVA": "DaVita",
        "DECK": "Deckers Brands",
        "DE": "Deere & Company",
        "DELL": "Dell Technologies",
        "DAL": "Delta Air Lines",
        "DVN": "Devon Energy",
        "DXCM": "Dexcom",
        "FANG": "Diamondback Energy",
        "DLR": "Digital Realty",
        "DG": "Dollar General",
        "DLTR": "Dollar Tree",
        "D": "Dominion Energy",
        "DPZ": "Domino's",
        "DASH": "DoorDash",
        "DOV": "Dover Corporation",
        "DOW": "Dow Inc.",
        "DHI": "D. R. Horton",
        "DTE": "DTE Energy",
        "DUK": "Duke Energy",
        "DD": "DuPont",
        # --- E ---
        "ETN": "Eaton Corporation",
        "EBAY": "eBay Inc.",
        "ECL": "Ecolab",
        "EIX": "Edison International",
        "EW": "Edwards Lifesciences",
        "EA": "Electronic Arts",
        "ELV": "Elevance Health",
        "EME": "Emcor",
        "EMR": "Emerson Electric",
        "ETR": "Entergy",
        "EOG": "EOG Resources",
        "EPAM": "EPAM Systems",
        "EQT": "EQT Corporation",
        "EFX": "Equifax",
        "EQIX": "Equinix",
        "EQR": "Equity Residential",
        "ERIE": "Erie Indemnity",
        "ESS": "Essex Property Trust",
        "EL": "Estee Lauder Companies",
        "EG": "Everest Group",
        "EVRG": "Evergy",
        "ES": "Eversource Energy",
        "EXC": "Exelon",
        "EXE": "Expand Energy",
        "EXPE": "Expedia Group",
        "EXPD": "Expeditors International",
        "EXR": "Extra Space Storage",
        "XOM": "ExxonMobil",
        # --- F ---
        "FFIV": "F5, Inc.",
        "FDS": "FactSet",
        "FICO": "Fair Isaac",
        "FAST": "Fastenal",
        "FRT": "Federal Realty Investment Trust",
        "FDX": "FedEx",
        "FIS": "Fidelity National Information Services",
        "FITB": "Fifth Third Bancorp",
        "FSLR": "First Solar",
        "FE": "FirstEnergy",
        "FISV": "Fiserv",
        "F": "Ford Motor Company",
        "FTNT": "Fortinet",
        "FTV": "Fortive",
        "FOXA": "Fox Corporation (Class A)",
        "FOX": "Fox Corporation (Class B)",
        "BEN": "Franklin Resources",
        "FCX": "Freeport-McMoRan",
        # --- G ---
        "GRMN": "Garmin",
        "IT": "Gartner",
        "GE": "GE Aerospace",
        "GEHC": "GE HealthCare",
        "GEV": "GE Vernova",
        "GEN": "Gen Digital",
        "GNRC": "Generac",
        "GD": "General Dynamics",
        "GIS": "General Mills",
        "GM": "General Motors",
        "GPC": "Genuine Parts Company",
        "GILD": "Gilead Sciences",
        "GPN": "Global Payments",
        "GL": "Globe Life",
        "GDDY": "GoDaddy",
        "GS": "Goldman Sachs",
        # --- H ---
        "HAL": "Halliburton",
        "HIG": "Hartford (The)",
        "HAS": "Hasbro",
        "HCA": "HCA Healthcare",
        "DOC": "Healthpeak Properties",
        "HSIC": "Henry Schein",
        "HSY": "Hershey Company",
        "HPE": "Hewlett Packard Enterprise",
        "HLT": "Hilton Worldwide",
        "HOLX": "Hologic",
        "HD": "Home Depot",
        "HON": "Honeywell",
        "HRL": "Hormel Foods",
        "HST": "Host Hotels & Resorts",
        "HWM": "Howmet Aerospace",
        "HPQ": "HP Inc.",
        "HUBB": "Hubbell Incorporated",
        "HUM": "Humana",
        "HBAN": "Huntington Bancshares",
        "HII": "Huntington Ingalls Industries",
        # --- I ---
        "IBM": "IBM",
        "IEX": "IDEX Corporation",
        "IDXX": "Idexx Laboratories",
        "ITW": "Illinois Tool Works",
        "INCY": "Incyte",
        "IR": "Ingersoll Rand",
        "PODD": "Insulet Corporation",
        "INTC": "Intel",
        "IBKR": "Interactive Brokers",
        "ICE": "Intercontinental Exchange",
        "IFF": "International Flavors & Fragrances",
        "IP": "International Paper",
        "INTU": "Intuit",
        "ISRG": "Intuitive Surgical",
        "IVZ": "Invesco",
        "INVH": "Invitation Homes",
        "IQV": "IQVIA",
        "IRM": "Iron Mountain",
        # --- J ---
        "JBHT": "J.B. Hunt",
        "JBL": "Jabil",
        "JKHY": "Jack Henry & Associates",
        "J": "Jacobs Solutions",
        "JNJ": "Johnson & Johnson",
        "JCI": "Johnson Controls",
        "JPM": "JPMorgan Chase",
        # --- K ---
        "KVUE": "Kenvue",
        "KDP": "Keurig Dr Pepper",
        "KEY": "KeyCorp",
        "KEYS": "Keysight Technologies",
        "KMB": "Kimberly-Clark",
        "KIM": "Kimco Realty",
        "KMI": "Kinder Morgan",
        "KKR": "KKR & Co.",
        "KLAC": "KLA Corporation",
        "KHC": "Kraft Heinz",
        "KR": "Kroger",
        # --- L ---
        "LHX": "L3Harris",
        "LH": "Labcorp",
        "LRCX": "Lam Research",
        "LW": "Lamb Weston",
        "LVS": "Las Vegas Sands",
        "LDOS": "Leidos",
        "LEN": "Lennar",
        "LII": "Lennox International",
        "LLY": "Eli Lilly and Company",
        "LIN": "Linde plc",
        "LYV": "Live Nation Entertainment",
        "LMT": "Lockheed Martin",
        "L": "Loews Corporation",
        "LOW": "Lowe's",
        "LULU": "Lululemon Athletica",
        "LYB": "LyondellBasell",
        # --- M ---
        "MTB": "M&T Bank",
        "MPC": "Marathon Petroleum",
        "MAR": "Marriott International",
        "MRSH": "Marsh McLennan",
        "MLM": "Martin Marietta Materials",
        "MAS": "Masco",
        "MA": "Mastercard",
        "MTCH": "Match Group",
        "MKC": "McCormick & Company",
        "MCD": "McDonald's",
        "MCK": "McKesson Corporation",
        "MDT": "Medtronic",
        "MRK": "Merck & Co.",
        "META": "Meta Platforms",
        "MET": "MetLife",
        "MTD": "Mettler Toledo",
        "MGM": "MGM Resorts",
        "MCHP": "Microchip Technology",
        "MU": "Micron Technology",
        "MSFT": "Microsoft",
        "MAA": "Mid-America Apartment Communities",
        "MRNA": "Moderna",
        "MOH": "Molina Healthcare",
        "TAP": "Molson Coors Beverage Company",
        "MDLZ": "Mondelez International",
        "MPWR": "Monolithic Power Systems",
        "MNST": "Monster Beverage",
        "MCO": "Moody's Corporation",
        "MS": "Morgan Stanley",
        "MOS": "Mosaic Company",
        "MSI": "Motorola Solutions",
        "MSCI": "MSCI Inc.",
        # --- N ---
        "NDAQ": "Nasdaq, Inc.",
        "NTAP": "NetApp",
        "NFLX": "Netflix",
        "NEM": "Newmont",
        "NWSA": "News Corp (Class A)",
        "NWS": "News Corp (Class B)",
        "NEE": "NextEra Energy",
        "NKE": "Nike, Inc.",
        "NI": "NiSource",
        "NDSN": "Nordson Corporation",
        "NSC": "Norfolk Southern",
        "NTRS": "Northern Trust",
        "NOC": "Northrop Grumman",
        "NCLH": "Norwegian Cruise Line Holdings",
        "NRG": "NRG Energy",
        "NUE": "Nucor",
        "NVDA": "Nvidia",
        "NVR": "NVR, Inc.",
        "NXPI": "NXP Semiconductors",
        # --- O ---
        "ORLY": "O'Reilly Automotive",
        "OXY": "Occidental Petroleum",
        "ODFL": "Old Dominion",
        "OMC": "Omnicom Group",
        "ON": "ON Semiconductor",
        "OKE": "Oneok",
        "ORCL": "Oracle Corporation",
        "OTIS": "Otis Worldwide",
        # --- P ---
        "PCAR": "Paccar",
        "PKG": "Packaging Corporation of America",
        "PLTR": "Palantir Technologies",
        "PANW": "Palo Alto Networks",
        "PSKY": "Paramount Skydance Corporation",
        "PH": "Parker Hannifin",
        "PAYX": "Paychex",
        "PAYC": "Paycom",
        "PYPL": "PayPal",
        "PNR": "Pentair",
        "PEP": "PepsiCo",
        "PFE": "Pfizer",
        "PCG": "PG&E Corporation",
        "PM": "Philip Morris International",
        "PSX": "Phillips 66",
        "PNW": "Pinnacle West Capital",
        "PNC": "PNC Financial Services",
        "POOL": "Pool Corporation",
        "PPG": "PPG Industries",
        "PPL": "PPL Corporation",
        "PFG": "Principal Financial Group",
        "PG": "Procter & Gamble",
        "PGR": "Progressive Corporation",
        "PLD": "Prologis",
        "PRU": "Prudential Financial",
        "PEG": "Public Service Enterprise Group",
        "PTC": "PTC Inc.",
        "PSA": "Public Storage",
        "PHM": "PulteGroup",
        "PWR": "Quanta Services",
        "QCOM": "Qualcomm",
        "DGX": "Quest Diagnostics",
        "Q": "Qnity Electronics",
        # --- R ---
        "RL": "Ralph Lauren Corporation",
        "RJF": "Raymond James Financial",
        "RTX": "RTX Corporation",
        "O": "Realty Income",
        "REG": "Regency Centers",
        "REGN": "Regeneron Pharmaceuticals",
        "RF": "Regions Financial Corporation",
        "RSG": "Republic Services",
        "RMD": "ResMed",
        "RVTY": "Revvity",
        "HOOD": "Robinhood Markets",
        "ROK": "Rockwell Automation",
        "ROL": "Rollins, Inc.",
        "ROP": "Roper Technologies",
        "ROST": "Ross Stores",
        "RCL": "Royal Caribbean Group",
        # --- S ---
        "SPGI": "S&P Global",
        "CRM": "Salesforce",
        "SNDK": "Sandisk",
        "SBAC": "SBA Communications",
        "SLB": "Schlumberger",
        "STX": "Seagate Technology",
        "SRE": "Sempra",
        "NOW": "ServiceNow",
        "SHW": "Sherwin-Williams",
        "SPG": "Simon Property Group",
        "SWKS": "Skyworks Solutions",
        "SJM": "J.M. Smucker Company",
        "SW": "Smurfit Westrock",
        "SNA": "Snap-on",
        "SOLV": "Solventum",
        "SO": "Southern Company",
        "LUV": "Southwest Airlines",
        "SWK": "Stanley Black & Decker",
        "SBUX": "Starbucks",
        "STT": "State Street Corporation",
        "STLD": "Steel Dynamics",
        "STE": "Steris",
        "SYK": "Stryker Corporation",
        "SMCI": "Supermicro",
        "SYF": "Synchrony Financial",
        "SNPS": "Synopsys",
        "SYY": "Sysco",
        # --- T ---
        "TMUS": "T-Mobile US",
        "TROW": "T. Rowe Price",
        "TTWO": "Take-Two Interactive",
        "TPR": "Tapestry, Inc.",
        "TRGP": "Targa Resources",
        "TGT": "Target Corporation",
        "TEL": "TE Connectivity",
        "TDY": "Teledyne Technologies",
        "TER": "Teradyne",
        "TSLA": "Tesla, Inc.",
        "TXN": "Texas Instruments",
        "TPL": "Texas Pacific Land Corporation",
        "TXT": "Textron",
        "TMO": "Thermo Fisher Scientific",
        "TJX": "TJX Companies",
        "TKO": "TKO Group Holdings",
        "TTD": "Trade Desk",
        "TSCO": "Tractor Supply",
        "TT": "Trane Technologies",
        "TDG": "TransDigm Group",
        "TRV": "Travelers Companies",
        "TRMB": "Trimble Inc.",
        "TFC": "Truist Financial",
        "TYL": "Tyler Technologies",
        "TSN": "Tyson Foods",
        # --- U ---
        "USB": "U.S. Bancorp",
        "UBER": "Uber",
        "UDR": "UDR, Inc.",
        "ULTA": "Ulta Beauty",
        "UNP": "Union Pacific Corporation",
        "UAL": "United Airlines Holdings",
        "UPS": "United Parcel Service",
        "URI": "United Rentals",
        "UNH": "UnitedHealth Group",
        "UHS": "Universal Health Services",
        # --- V ---
        "VLO": "Valero Energy",
        "VTR": "Ventas",
        "VLTO": "Veralto",
        "VRSN": "Verisign",
        "VRSK": "Verisk Analytics",
        "VZ": "Verizon",
        "VRTX": "Vertex Pharmaceuticals",
        "VTRS": "Viatris",
        "VICI": "Vici Properties",
        "V": "Visa Inc.",
        "VST": "Vistra Corp",
        "VMC": "Vulcan Materials Company",
        # --- W ---
        "WRB": "W. R. Berkley Corporation",
        "GWW": "W. W. Grainger",
        "WAB": "Wabtec",
        "WMT": "Walmart",
        "DIS": "Walt Disney Company",
        "WBD": "Warner Bros. Discovery",
        "WM": "Waste Management",
        "WAT": "Waters Corporation",
        "WEC": "WEC Energy Group",
        "WFC": "Wells Fargo",
        "WELL": "Welltower",
        "WST": "West Pharmaceutical Services",
        "WDC": "Western Digital",
        "WY": "Weyerhaeuser",
        "WSM": "Williams-Sonoma, Inc.",
        "WMB": "Williams Companies",
        "WTW": "Willis Towers Watson",
        "WDAY": "Workday, Inc.",
        "WYNN": "Wynn Resorts",
        # --- X/Y/Z ---
        "XEL": "Xcel Energy",
        "XYL": "Xylem Inc.",
        "YUM": "Yum! Brands",
        "ZBRA": "Zebra Technologies",
        "ZBH": "Zimmer Biomet",
        "ZTS": "Zoetis",
    }
    logger.info("使用内置 S&P500 列表，共 %d 只", len(tickers))
    return pd.DataFrame(
        [{"代码": k, "名称": v} for k, v in tickers.items()]
    )


def _get_core_us_tickers() -> pd.DataFrame:
    """备用接口，直接返回完整 S&P500 列表。"""
    return _get_sp500_tickers()


async def fetch_us_stock_list() -> pd.DataFrame:
    """异步包装：获取美股股票列表。"""
    logger.info("正在获取美股股票列表...")
    df = await asyncio.to_thread(_sync_fetch_us_stock_list)
    logger.info("共获取到 %d 只美股", len(df))
    return df


async def fetch_us_stock_list_from_db() -> pd.DataFrame:
    """从数据库中获取已有的美股代码列表。"""
    sql = sa_text("""
        SELECT DISTINCT ON (ts_code) ts_code, name
        FROM stock_daily_quote
        WHERE market = 'US'
        ORDER BY ts_code,
                 CASE WHEN name IS NOT NULL AND name != '' THEN 0 ELSE 1 END,
                 trade_date DESC
    """)

    async with async_session() as session:
        result = await session.execute(sql)
        rows = result.all()

    if not rows:
        return pd.DataFrame(columns=["代码", "名称"])

    data = [{"代码": r[0], "名称": r[1] or ""} for r in rows]
    df = pd.DataFrame(data)
    logger.info("从数据库获取到 %d 只美股代码", len(df))
    return df


# ============================================================
# 2. 腾讯财经 — 主力数据源
# ============================================================

def _tencent_us_code(ticker: str) -> str:
    """将美股 ticker 转为腾讯财经格式（含交易所后缀）。

    腾讯美股格式: usAAPL.OQ (NASDAQ) / usJPM.N (NYSE)
    **必须带交易所后缀**，否则只返回 2 条数据。

    策略：
      1. 核心股票用硬编码映射（保证正确）
      2. 其他股票默认用 .OQ（NASDAQ），如果失败再试 .N（NYSE）
    """
    # BRK-B → BRK.B（腾讯用 . 而非 -）
    tc_ticker = ticker.replace("-", ".")

    # NYSE 上市股票列表（.N 后缀），覆盖 S&P500 中的 NYSE 成分股
    # 其余默认 NASDAQ（.OQ 后缀）
    NYSE_TICKERS = {
        # 原核心列表
        "BRK.B", "UNH", "JNJ", "V", "XOM", "JPM", "WMT", "MA", "PG", "HD",
        "CVX", "MRK", "ABBV", "LLY", "PEP", "KO", "TMO", "MCD", "ACN", "ABT",
        "DHR", "NKE", "TXN", "NEE", "PM", "DIS", "BA", "GE", "CAT", "GS",
        # S&P500 扩展 — NYSE 上市
        "MMM", "AOS", "AES", "AFL", "A", "APD", "ALB", "ARE", "ALLE", "LNT",
        "ALL", "MO", "AMCR", "AEE", "AEP", "AXP", "AIG", "AMT", "AWK", "AMP",
        "AME", "APH", "AON", "APA", "APO", "ADM", "AJG", "AIZ", "T", "ATO",
        "AVB", "AVY",
        "BKR", "BALL", "BAC", "BAX", "BDX", "BBY", "BLK", "BX", "BK",
        "BSX", "BMY", "BR", "BRO", "BF.B", "BG", "BXP",
        "CHRW", "CPT", "COF", "CAH", "CCL", "CARR", "CBOE", "CBRE", "COR",
        "CNC", "CNP", "CF", "CRL", "CB", "CHD", "CI", "CINF", "CTAS",
        "C", "CFG", "CLX", "CME", "CMS", "CL", "FIX", "CAG", "COP", "ED",
        "STZ", "CEG", "COO", "GLW", "CPAY", "CTVA", "CRH", "CCI", "CSX", "CMI", "CVS",
        "DRI", "DVA", "DE", "DAL", "DVN", "DLR", "DG", "DLTR", "D", "DPZ",
        "DOV", "DOW", "DHI", "DTE", "DUK", "DD",
        "ETN", "ECL", "EIX", "EW", "ELV", "EME", "EMR", "ETR", "EOG", "EQT",
        "EFX", "EQIX", "EQR", "ERIE", "ESS", "EL", "EG", "EVRG", "ES", "EXC",
        "EXE", "EXR",
        "FRT", "FDX", "FIS", "FITB", "FE", "F", "FTV", "FOXA", "FOX",
        "BEN", "FCX",
        "IT", "GEHC", "GEV", "GD", "GIS", "GM", "GPC", "GILD", "GPN", "GL",
        "HAL", "HIG", "HAS", "HCA", "DOC", "HSIC", "HSY", "HPE", "HLT",
        "HON", "HRL", "HST", "HWM", "HPQ", "HUBB", "HUM", "HBAN", "HII",
        "IBM", "IEX", "ITW", "IR", "ICE", "IFF", "IP", "IVZ", "INVH", "IQV", "IRM",
        "JBHT", "JBL", "J", "JCI",
        "KVUE", "KDP", "KEY", "KMB", "KIM", "KMI", "KKR", "KHC", "KR",
        "LHX", "LH", "LW", "LVS", "LDOS", "LEN", "LII", "LIN",
        "LYV", "LMT", "L", "LOW", "LYB",
        "MTB", "MPC", "MAR", "MRSH", "MLM", "MAS", "MKC", "MCK", "MDT",
        "MET", "MTD", "MGM", "MU", "MAA", "MOH", "TAP", "MDLZ", "MCO", "MS",
        "MOS", "MSI",
        "NTAP", "NEM", "NWSA", "NWS", "NI", "NSC", "NTRS", "NOC", "NCLH",
        "NRG", "NUE", "NVR",
        "OXY", "OMC", "OKE", "OTIS",
        "PCAR", "PKG", "PH", "PAYX", "PNR", "PFE", "PCG", "PSX", "PNW", "PNC",
        "POOL", "PPG", "PPL", "PFG", "PGR", "PLD", "PRU", "PEG", "PSA", "PHM", "PWR",
        "DGX",
        "RL", "RJF", "RTX", "O", "REG", "RF", "RSG", "RMD", "ROK", "ROL",
        "ROP", "RCL",
        "SPGI", "SLB", "SRE", "SHW", "SPG", "SJM", "SW", "SNA", "SO", "LUV",
        "SWK", "STT", "STLD", "STE", "SYK", "SYF", "SYY",
        "TROW", "TPR", "TRGP", "TGT", "TEL", "TDY", "TER", "TXT",
        "TJX", "TKO", "TSCO", "TT", "TDG", "TRV", "TFC", "TYL", "TSN",
        "USB", "UDR", "UNP", "UAL", "UPS", "URI", "UHS",
        "VLO", "VTR", "VLTO", "VZ", "VTRS", "VICI", "VST", "VMC",
        "WRB", "GWW", "WAB", "WBD", "WM", "WAT", "WEC", "WFC", "WELL",
        "WST", "WY", "WMB", "WTW", "WYNN",
        "XEL",
        "YUM",
        "ZBH", "ZTS",
    }

    exchange = "N" if tc_ticker in NYSE_TICKERS else "OQ"
    return f"us{tc_ticker}.{exchange}"


def _sync_fetch_tencent_us_kline(ticker: str, days: int = 320) -> pd.DataFrame | None:
    """通过腾讯财经 API 获取单只美股的前复权日K线数据。

    API: http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{days},qfq
    返回: [日期, 开盘, 收盘, 最高, 最低, 成交量]

    如果默认交易所后缀失败（数据太少），自动尝试另一个交易所。
    """
    tc_code = _tencent_us_code(ticker)

    df = _try_tencent_kline(tc_code, ticker, days)

    # 如果数据太少（<10 条），尝试另一个交易所后缀
    if (df is None or len(df) < 10) and "." in tc_code:
        alt_exchange = "N" if tc_code.endswith(".OQ") else "OQ"
        alt_code = tc_code.rsplit(".", 1)[0] + "." + alt_exchange
        logger.debug("腾讯美股 %s 数据不足，尝试 %s", tc_code, alt_code)
        alt_df = _try_tencent_kline(alt_code, ticker, days)
        if alt_df is not None and (df is None or len(alt_df) > len(df)):
            df = alt_df

    return df


def _try_tencent_kline(tc_code: str, ticker: str, days: int) -> pd.DataFrame | None:
    """尝试从腾讯 API 获取指定代码的K线数据（内部实现）。"""
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={tc_code},day,,,{days},qfq"

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode("utf-8")
        data = json.loads(text)

        # 解析数据：data -> data -> {code} -> qfqday 或 day
        stock_data = data.get("data", {}).get(tc_code, {})
        kline = stock_data.get("qfqday") or stock_data.get("day")
        if not kline:
            # 腾讯有时用不同的 key，尝试遍历
            for key in data.get("data", {}):
                sub = data["data"][key]
                if isinstance(sub, dict):
                    kline = sub.get("qfqday") or sub.get("day")
                    if kline:
                        break

        if not kline:
            return None

        rows = []
        for item in kline:
            # [日期, 开盘, 收盘, 最高, 最低, 成交量]
            if len(item) >= 6:
                try:
                    rows.append({
                        "trade_date": item[0],
                        "open": float(item[1]),
                        "close": float(item[2]),
                        "high": float(item[3]),
                        "low": float(item[4]),
                        "volume": float(item[5]),
                        "ts_code": ticker,
                    })
                except (ValueError, TypeError):
                    continue

        if not rows:
            return None

        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        df.sort_values("trade_date", inplace=True)
        df["change"] = df["close"].diff()
        df["pct_change"] = df["close"].pct_change() * 100
        df["amount"] = ((df["open"] + df["close"]) / 2 * df["volume"]).round(2)

        return df

    except Exception as e:
        logger.debug("腾讯美股K线 %s 失败: %s", tc_code, e)
        return None


# ============================================================
# 3. yfinance — Fallback 数据源
# ============================================================

def _sync_fetch_yf_single(
    ticker: str,
    start_date: str,
    end_date: str,
) -> pd.DataFrame | None:
    """通过 yfinance 获取单只美股的前复权日线数据（fallback 用）。"""
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance 未安装，跳过 fallback")
        return None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            stock = yf.Ticker(ticker)
            df = stock.history(start=start_date, end=end_date, auto_adjust=False)

            if df is None or df.empty:
                return None

            df = df.reset_index()
            df = df.rename(columns={
                "Date": "trade_date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Adj Close": "adj_close",
                "Volume": "volume",
            })

            # 使用前复权价格
            if "adj_close" in df.columns and "close" in df.columns:
                adj_factor = df["adj_close"] / df["close"]
                adj_factor = adj_factor.fillna(1.0)
                df["open"] = df["open"] * adj_factor
                df["high"] = df["high"] * adj_factor
                df["low"] = df["low"] * adj_factor
                df["close"] = df["adj_close"]

            df["ts_code"] = ticker
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
            df = df.sort_values("trade_date")
            df["change"] = df["close"].diff()
            df["pct_change"] = df["close"].pct_change() * 100
            df["amount"] = ((df["open"] + df["close"]) / 2 * df["volume"]).round(2)
            df = df.drop(columns=["adj_close"], errors="ignore")

            return df

        except Exception as e:
            if attempt < MAX_RETRIES:
                import time
                time.sleep(RETRY_DELAY + random.uniform(0, 1))
            else:
                logger.warning("yfinance %s 经 %d 次重试仍失败: %s", ticker, MAX_RETRIES, e)
                return None
    return None


def _sync_fetch_yf_batch(
    tickers: list[str],
    start_date: str,
    end_date: str,
) -> dict[str, pd.DataFrame]:
    """通过 yfinance 批量获取多只美股历史数据（fallback 用）。"""
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("yfinance 未安装，跳过 fallback")
        return {}

    try:
        data = yf.download(
            tickers=tickers,
            start=start_date,
            end=end_date,
            auto_adjust=True,
            group_by="ticker",
            threads=True,
            progress=False,
        )

        if data is None or data.empty:
            return {}

        result = {}

        if len(tickers) == 1:
            ticker = tickers[0]
            df = data.reset_index()
            df.columns = [c.lower() if isinstance(c, str) else c for c in df.columns]
            if "date" in df.columns:
                df = df.rename(columns={"date": "trade_date"})
            df["ts_code"] = ticker
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
            df = df.sort_values("trade_date")
            df["change"] = df["close"].diff()
            df["pct_change"] = df["close"].pct_change() * 100
            df["amount"] = ((df["open"] + df["close"]) / 2 * df["volume"]).round(2)
            result[ticker] = df
        else:
            for ticker in tickers:
                try:
                    if ticker not in data.columns.get_level_values(0):
                        continue
                    df = data[ticker].dropna(how="all").reset_index()
                    if df.empty:
                        continue
                    df.columns = [c.lower() if isinstance(c, str) else c for c in df.columns]
                    if "date" in df.columns:
                        df = df.rename(columns={"date": "trade_date"})
                    df["ts_code"] = ticker
                    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
                    df = df.sort_values("trade_date")
                    df["change"] = df["close"].diff()
                    df["pct_change"] = df["close"].pct_change() * 100
                    df["amount"] = ((df["open"] + df["close"]) / 2 * df["volume"]).round(2)
                    result[ticker] = df
                except Exception as e:
                    logger.debug("解析 yfinance %s 批量数据失败: %s", ticker, e)

        return result
    except Exception as e:
        logger.warning("yfinance 批量下载失败: %s", e)
        return {}


# ============================================================
# 4. 数据自洽性校验
# ============================================================

def validate_sanity(df: pd.DataFrame) -> pd.DataFrame:
    """数据自洽性校验 — 写入 DB 前自动检查，剔除不合理的记录。

    校验规则：
      1. close ∈ [low, high]
      2. open > 0, close > 0, high > 0, low > 0
      3. volume >= 0
      4. low <= high
      5. pct_change 在合理范围内（-50% ~ +50%）
      6. 价格不能为 NaN

    Returns:
        清洗后的 DataFrame（剔除异常行，记录日志）
    """
    if df.empty:
        return df

    original_len = len(df)

    # 基础非空校验
    df = df.dropna(subset=["open", "close", "high", "low"])

    # 价格必须为正
    price_mask = (
        (df["open"] > SANITY_MIN_PRICE)
        & (df["close"] > SANITY_MIN_PRICE)
        & (df["high"] > SANITY_MIN_PRICE)
        & (df["low"] > SANITY_MIN_PRICE)
    )
    df = df[price_mask].copy()

    # low <= high
    df = df[df["low"] <= df["high"]].copy()

    # close ∈ [low, high]（允许 0.1% 的浮点误差）
    epsilon = 0.001
    close_in_range = (
        (df["close"] >= df["low"] * (1 - epsilon))
        & (df["close"] <= df["high"] * (1 + epsilon))
    )
    df = df[close_in_range].copy()

    # pct_change 合理范围
    if "pct_change" in df.columns:
        pct_ok = df["pct_change"].isna() | (df["pct_change"].abs() <= SANITY_MAX_PCT_CHANGE)
        df = df[pct_ok].copy()

    # volume >= 0
    if "volume" in df.columns:
        df = df[df["volume"] >= 0].copy()

    removed = original_len - len(df)
    if removed > 0:
        logger.warning("数据自洽性校验: 剔除 %d 条异常记录（原 %d 条）", removed, original_len)

    return df


def detect_stale_data(df: pd.DataFrame, max_identical_days: int = 5) -> list[str]:
    """检测数据冻结 — 连续 N 天 OHLCV 完全相同的股票（可能数据源故障）。

    Returns:
        疑似冻结的股票代码列表
    """
    stale_tickers = []
    for ticker, group in df.groupby("ts_code"):
        if len(group) < max_identical_days:
            continue
        group = group.sort_values("trade_date")
        # 检查连续 N 天 close 完全相同
        closes = group["close"].values
        for i in range(len(closes) - max_identical_days + 1):
            window = closes[i:i + max_identical_days]
            if len(set(window)) == 1:
                stale_tickers.append(str(ticker))
                break

    if stale_tickers:
        logger.warning("检测到 %d 只股票疑似数据冻结: %s", len(stale_tickers), stale_tickers[:10])

    return stale_tickers


# ============================================================
# 5. 多源交叉验证
# ============================================================

def _sync_cross_validate_with_yfinance(
    tickers: list[str],
    tencent_data: dict[str, pd.DataFrame],
) -> dict[str, dict]:
    """用 yfinance 对腾讯数据做最后一天收盘价交叉验证（同步，在线程中运行）。

    只抽样验证最近 5 天的数据，轻量不影响性能。

    Returns:
        {ticker: {"tencent_close": x, "yf_close": y, "diff_pct": z, "match": bool}}
    """
    try:
        import yfinance as yf
    except ImportError:
        logger.info("yfinance 未安装，跳过交叉验证")
        return {}

    if not tickers or not tencent_data:
        return {}

    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

    results = {}
    for ticker in tickers:
        tc_df = tencent_data.get(ticker)
        if tc_df is None or tc_df.empty:
            continue

        tc_last = tc_df.sort_values("trade_date").iloc[-1]
        tc_close = float(tc_last["close"])
        tc_date = tc_last["trade_date"]

        try:
            stock = yf.Ticker(ticker)
            yf_df = stock.history(start=start_date, end=end_date, auto_adjust=True)
            if yf_df is None or yf_df.empty:
                continue

            yf_df = yf_df.reset_index()
            yf_df["Date"] = pd.to_datetime(yf_df["Date"]).dt.date

            # 匹配同一天
            yf_row = yf_df[yf_df["Date"] == tc_date]
            if yf_row.empty:
                # 尝试匹配最后一天
                yf_row = yf_df.iloc[[-1]]

            yf_close = float(yf_row.iloc[0]["Close"])

            if tc_close > 0 and yf_close > 0:
                diff_pct = abs(tc_close - yf_close) / yf_close
                match = diff_pct <= CROSS_VALIDATE_TOLERANCE
                results[ticker] = {
                    "tencent_close": round(tc_close, 2),
                    "yf_close": round(yf_close, 2),
                    "diff_pct": round(diff_pct * 100, 2),
                    "match": match,
                    "date": str(tc_date),
                }
                if not match:
                    logger.warning(
                        "交叉验证不匹配 %s@%s: 腾讯=%.2f, yfinance=%.2f, 偏差=%.2f%%",
                        ticker, tc_date, tc_close, yf_close, diff_pct * 100,
                    )

        except Exception as e:
            logger.debug("yfinance 交叉验证 %s 失败: %s", ticker, e)

    return results


def _sync_cross_validate_with_sina(tickers: list[str]) -> dict[str, float]:
    """用新浪财经获取美股实时行情，作为最新价抽样验证。

    接口: https://hq.sinajs.cn/list=gb_aapl,gb_msft,...
    返回: {ticker: latest_price}
    """
    if not tickers:
        return {}

    # ticker → 新浪格式: AAPL → gb_aapl
    sina_codes = []
    code_map = {}  # sina_code → ticker
    for t in tickers:
        sc = f"gb_{t.lower().replace('-', '')}"
        sina_codes.append(sc)
        code_map[sc] = t

    url = f"https://hq.sinajs.cn/list={','.join(sina_codes)}"

    try:
        req = urllib.request.Request(url, headers={
            "Referer": "https://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode("gbk", errors="replace")
    except Exception as e:
        logger.debug("新浪美股实时行情请求失败: %s", e)
        return {}

    prices: dict[str, float] = {}
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or '="' not in line:
            continue
        # var hq_str_gb_aapl="Apple Inc,...,最新价,...";
        m = re.match(r'var hq_str_(gb_\w+)="(.+)"', line)
        if not m:
            continue
        sina_sym = m.group(1)
        fields = m.group(2).split(",")
        # 新浪美股格式: fields[1] = 最新价
        if len(fields) >= 2:
            try:
                price = float(fields[1])
                if price > 0:
                    ticker = code_map.get(sina_sym)
                    if ticker:
                        prices[ticker] = price
            except (ValueError, IndexError):
                pass

    return prices


async def cross_validate_latest(
    tencent_data: dict[str, pd.DataFrame],
    sample_size: int = CROSS_VALIDATE_SAMPLE_SIZE,
) -> dict:
    """综合交叉验证入口 — 抽样验证腾讯数据的准确性。

    流程：
      1. 从成功获取的股票中随机抽样
      2. 用 yfinance 对比最后一天收盘价
      3. 用新浪行情对比最新价（如果是交易时段）
      4. 汇总验证报告

    Returns:
        {
            "sample_size": int,
            "yf_results": {...},
            "sina_results": {...},
            "yf_match_rate": float,  # yfinance 匹配率
            "alerts": [...]          # 告警信息
        }
    """
    available_tickers = [t for t, df in tencent_data.items() if df is not None and not df.empty]
    if not available_tickers:
        return {"sample_size": 0, "alerts": ["无可验证数据"]}

    # 随机抽样
    sample = random.sample(available_tickers, min(sample_size, len(available_tickers)))
    logger.info("交叉验证: 抽样 %d 只股票 %s", len(sample), sample)

    # 并发执行 yfinance 和 新浪验证
    yf_results = await asyncio.to_thread(
        _sync_cross_validate_with_yfinance, sample, tencent_data,
    )
    sina_prices = await asyncio.to_thread(_sync_cross_validate_with_sina, sample)

    # 汇总
    alerts = []
    yf_matched = sum(1 for r in yf_results.values() if r.get("match"))
    yf_total = len(yf_results)
    yf_match_rate = yf_matched / yf_total if yf_total > 0 else 0.0

    if yf_total > 0 and yf_match_rate < 0.7:
        alert = f"⚠️ yfinance 交叉验证匹配率偏低: {yf_match_rate:.0%} ({yf_matched}/{yf_total})"
        alerts.append(alert)
        logger.warning(alert)

    # 新浪价格对比
    sina_alerts = []
    for ticker in sample:
        sina_price = sina_prices.get(ticker)
        tc_df = tencent_data.get(ticker)
        if sina_price and tc_df is not None and not tc_df.empty:
            tc_close = float(tc_df.sort_values("trade_date").iloc[-1]["close"])
            if tc_close > 0:
                diff = abs(sina_price - tc_close) / tc_close
                if diff > CROSS_VALIDATE_TOLERANCE:
                    msg = f"新浪 vs 腾讯偏差 {ticker}: 新浪={sina_price:.2f}, 腾讯={tc_close:.2f}, 偏差={diff:.1%}"
                    sina_alerts.append(msg)
                    logger.warning(msg)

    alerts.extend(sina_alerts)

    report = {
        "sample_size": len(sample),
        "yf_results": yf_results,
        "sina_prices": sina_prices,
        "yf_match_rate": round(yf_match_rate, 2),
        "alerts": alerts,
    }

    if alerts:
        logger.warning("交叉验证报告: %d 条告警\n%s", len(alerts), "\n".join(alerts))
    else:
        logger.info("交叉验证通过 ✅ yfinance 匹配率=%.0f%%, 新浪无偏差", yf_match_rate * 100)

    return report


# ============================================================
# 6. 数据持久化（复用 A 股的 upsert 逻辑，标记 market='US'）
# ============================================================

def _us_df_to_records(df: pd.DataFrame) -> list[dict]:
    """将美股 DataFrame 转换为 ORM 兼容的 dict 列表。"""
    records = []
    required_cols = {"ts_code", "trade_date", "open", "close", "high", "low", "volume"}
    if not required_cols.issubset(set(df.columns)):
        logger.warning("DataFrame 缺少必要列: %s", required_cols - set(df.columns))
        return []

    for _, row in df.iterrows():
        rec = {
            "ts_code": str(row["ts_code"]),
            "name": str(row.get("name", "") or ""),
            "trade_date": row["trade_date"] if isinstance(row["trade_date"], date) else pd.to_datetime(row["trade_date"]).date(),
            "market": "US",
            "open": float(row["open"]) if pd.notna(row["open"]) else None,
            "close": float(row["close"]) if pd.notna(row["close"]) else None,
            "high": float(row["high"]) if pd.notna(row["high"]) else None,
            "low": float(row["low"]) if pd.notna(row["low"]) else None,
            "volume": int(row["volume"]) if pd.notna(row["volume"]) else None,
            "amount": float(row.get("amount", 0) or 0) if pd.notna(row.get("amount")) else None,
            "turnover": None,
            "amplitude": None,
            "pct_change": float(row["pct_change"]) if pd.notna(row.get("pct_change")) else None,
            "change": float(row["change"]) if pd.notna(row.get("change")) else None,
        }
        records.append(rec)
    return records


async def save_us_to_db(df: pd.DataFrame) -> int:
    """将美股 DataFrame 批量 upsert 到 PostgreSQL stock_daily_quote 表（market='US'）。

    写入前自动执行数据自洽性校验。

    Returns:
        写入/更新的记录数。
    """
    # ── 写入前校验 ──
    df = validate_sanity(df)
    if df.empty:
        return 0

    records = _us_df_to_records(df)
    if not records:
        return 0

    batch_size = 2000
    total_written = 0

    async with async_session() as session:
        for i in range(0, len(records), batch_size):
            batch = records[i : i + batch_size]
            stmt = pg_insert(StockDailyQuote).values(batch)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_quote_code_date",
                set_={
                    "name": func.coalesce(
                        func.nullif(stmt.excluded.name, ""),
                        StockDailyQuote.name,
                    ),
                    "market": stmt.excluded.market,
                    "open": stmt.excluded.open,
                    "close": stmt.excluded.close,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "volume": stmt.excluded.volume,
                    "amount": stmt.excluded.amount,
                    "pct_change": stmt.excluded.pct_change,
                    "change": stmt.excluded.change,
                },
            )
            await session.execute(stmt)
            total_written += len(batch)
        await session.commit()

    logger.info("美股数据已写入 PostgreSQL，共 %d 条记录", total_written)
    return total_written


# ============================================================
# 7. 主入口 — 全量获取美股行情（腾讯主力 + yfinance fallback）
# ============================================================

async def get_all_us_stock_data(force_refresh: bool = False) -> pd.DataFrame:
    """获取全部美股过去一年前复权日线数据（异步主入口）。

    流程：
      1. 检查 PostgreSQL 是否已有当天美股数据
      2. 若有效则直接从数据库加载返回
      3. 优先使用腾讯财经 API 逐只获取日K线（带交易所后缀）
      4. 腾讯失败的股票用 yfinance 批量兜底
      5. 数据自洽性校验 → 写入 PostgreSQL
      6. 数据冻结检测 + 新浪抽样交叉验证

    Args:
        force_refresh: 为 True 时强制重新下载。

    Returns:
        清洗后的完整 DataFrame。
    """
    if not force_refresh and await has_us_today_data():
        logger.info("美股当天数据已存在，从 PostgreSQL 加载")
        return await load_us_from_db()

    # 获取股票列表
    db_list = await fetch_us_stock_list_from_db()
    if db_list.empty or force_refresh:
        stock_list = await fetch_us_stock_list()
    else:
        stock_list = db_list

    codes = stock_list["代码"].tolist()
    names = dict(zip(stock_list["代码"], stock_list["名称"]))
    total = len(codes)

    logger.info("开始获取美股行情（腾讯主力 + yfinance fallback），共 %d 只...", total)

    total_records = 0
    total_stocks = 0
    tencent_ok = 0
    tencent_fail_tickers: list[str] = []
    all_tencent_data: dict[str, pd.DataFrame] = {}

    # ── 阶段 1: 腾讯财经逐只获取 ──
    TENCENT_BATCH = 200
    batch_dfs: list[pd.DataFrame] = []

    for idx, ticker in enumerate(codes, 1):
        if idx % 50 == 0:
            logger.info("腾讯美股K线进度: %d/%d (%.1f%%), 成功=%d, 失败=%d",
                         idx, total, idx / total * 100, tencent_ok, len(tencent_fail_tickers))

        df = await asyncio.to_thread(_sync_fetch_tencent_us_kline, ticker, 320)
        if df is not None and len(df) >= 10:
            df["name"] = names.get(ticker, "")
            batch_dfs.append(df)
            all_tencent_data[ticker] = df
            tencent_ok += 1
        else:
            tencent_fail_tickers.append(ticker)

        # 每 TENCENT_BATCH 只写入一次 DB
        if len(batch_dfs) >= TENCENT_BATCH:
            combined = pd.concat(batch_dfs, ignore_index=True)
            combined = combined[combined["volume"] > 0].copy()
            combined.drop_duplicates(subset=["ts_code", "trade_date"], inplace=True)
            if not combined.empty:
                written = await save_us_to_db(combined)
                total_records += written
                total_stocks += combined["ts_code"].nunique()
                logger.info("腾讯批次写入 DB: +%d 条（累计 %d 条，%d 只）",
                            written, total_records, total_stocks)
            del batch_dfs, combined
            batch_dfs = []
            gc.collect()

        # 腾讯 API 间隔
        await asyncio.sleep(0.3 + random.uniform(0, 0.2))

    # 处理最后一批
    if batch_dfs:
        combined = pd.concat(batch_dfs, ignore_index=True)
        combined = combined[combined["volume"] > 0].copy()
        combined.drop_duplicates(subset=["ts_code", "trade_date"], inplace=True)
        if not combined.empty:
            written = await save_us_to_db(combined)
            total_records += written
            total_stocks += combined["ts_code"].nunique()
        del batch_dfs, combined
        gc.collect()

    logger.info("腾讯财经阶段完成: 成功=%d, 失败=%d", tencent_ok, len(tencent_fail_tickers))

    # ── 阶段 2: yfinance fallback（腾讯失败的股票）──
    if tencent_fail_tickers:
        logger.info("开始 yfinance fallback，补全 %d 只腾讯失败的股票...", len(tencent_fail_tickers))

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

        YF_BATCH = 20
        yf_ok = 0
        yf_fail = 0

        for i in range(0, len(tencent_fail_tickers), YF_BATCH):
            batch_tickers = tencent_fail_tickers[i : i + YF_BATCH]

            batch_data = await asyncio.to_thread(
                _sync_fetch_yf_batch, batch_tickers, start_date, end_date
            )

            if batch_data:
                all_dfs = []
                for ticker, df in batch_data.items():
                    df["name"] = names.get(ticker, "")
                    all_dfs.append(df)
                    yf_ok += 1

                if all_dfs:
                    combined = pd.concat(all_dfs, ignore_index=True)
                    combined = combined[combined["volume"] > 0].copy()
                    combined.drop_duplicates(subset=["ts_code", "trade_date"], inplace=True)
                    if not combined.empty:
                        written = await save_us_to_db(combined)
                        total_records += written
                        total_stocks += combined["ts_code"].nunique()
                    del all_dfs, combined
                    gc.collect()

            yf_fail += len(batch_tickers) - len(batch_data)
            await asyncio.sleep(1.0 + random.uniform(0, 0.5))

        logger.info("yfinance fallback 完成: 补全=%d, 仍失败=%d", yf_ok, yf_fail)

    # ── 阶段 3: 数据冻结检测 ──
    all_data = await load_us_from_db()
    if not all_data.empty:
        stale = detect_stale_data(all_data)
        if stale:
            logger.warning("全量下载后发现 %d 只股票疑似数据冻结", len(stale))

    # ── 阶段 4: 新浪抽样交叉验证（不阻塞主流程）──
    if all_tencent_data:
        try:
            report = await cross_validate_latest(all_tencent_data)
            logger.info("交叉验证报告: 抽样=%d, yf匹配率=%.0f%%, 告警=%d",
                         report.get("sample_size", 0),
                         report.get("yf_match_rate", 0) * 100,
                         len(report.get("alerts", [])))
        except Exception as e:
            logger.warning("交叉验证异常（不影响主流程）: %s", e)

    yf_fallback_count = len(tencent_fail_tickers)
    logger.info("美股行情获取完成 ✅ 共 %d 条记录，涉及 %d 只股票（腾讯成功=%d, yfinance尝试补全=%d）",
                total_records, total_stocks, tencent_ok, yf_fallback_count)

    return await load_us_from_db()


# ============================================================
# 8. 增量更新（腾讯主力 + yfinance fallback）
# ============================================================

async def incremental_update_us_quotes(days: int = 10) -> int:
    """增量更新美股行情数据。

    策略：腾讯主力 → yfinance fallback → 自洽性校验。

    Args:
        days: 回溯天数，默认 10

    Returns:
        新增/更新的记录数
    """
    if await has_us_today_data():
        logger.info("美股增量更新跳过：今天的行情数据已存在")
        return 0

    db_list = await fetch_us_stock_list_from_db()
    if db_list.empty:
        logger.warning("美股增量更新失败：数据库中无美股列表")
        return 0

    codes = db_list["代码"].tolist()
    names = dict(zip(db_list["代码"], db_list["名称"]))
    total = len(codes)

    logger.info("开始美股增量更新（最近 %d 天），共 %d 只...", days, total)

    total_records = 0
    tencent_ok = 0
    tencent_fail_tickers: list[str] = []

    # ── 腾讯财经逐只获取 ──
    batch_dfs: list[pd.DataFrame] = []
    BATCH_WRITE = 500

    for idx, ticker in enumerate(codes, 1):
        df = await asyncio.to_thread(_sync_fetch_tencent_us_kline, ticker, days + 5)
        if df is not None and len(df) >= 1:
            df["name"] = names.get(ticker, "")
            batch_dfs.append(df)
            tencent_ok += 1
        else:
            tencent_fail_tickers.append(ticker)

        if len(batch_dfs) >= BATCH_WRITE:
            combined = pd.concat(batch_dfs, ignore_index=True)
            combined = combined[combined["volume"] > 0].copy()
            combined.drop_duplicates(subset=["ts_code", "trade_date"], inplace=True)
            if not combined.empty:
                written = await save_us_to_db(combined)
                total_records += written
            del batch_dfs, combined
            batch_dfs = []
            gc.collect()

        # 增量模式间隔更短
        await asyncio.sleep(0.15 + random.uniform(0, 0.1))

    # 处理最后一批
    if batch_dfs:
        combined = pd.concat(batch_dfs, ignore_index=True)
        combined = combined[combined["volume"] > 0].copy()
        combined.drop_duplicates(subset=["ts_code", "trade_date"], inplace=True)
        if not combined.empty:
            written = await save_us_to_db(combined)
            total_records += written
        del batch_dfs, combined
        gc.collect()

    # ── yfinance fallback ──
    if tencent_fail_tickers:
        logger.info("增量 yfinance fallback: %d 只...", len(tencent_fail_tickers))

        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        YF_BATCH = 50
        for i in range(0, len(tencent_fail_tickers), YF_BATCH):
            batch_tickers = tencent_fail_tickers[i : i + YF_BATCH]
            batch_data = await asyncio.to_thread(
                _sync_fetch_yf_batch, batch_tickers, start_date, end_date
            )
            if batch_data:
                all_dfs = []
                for ticker, df in batch_data.items():
                    df["name"] = names.get(ticker, "")
                    all_dfs.append(df)
                if all_dfs:
                    combined = pd.concat(all_dfs, ignore_index=True)
                    combined = combined[combined["volume"] > 0].copy()
                    combined.drop_duplicates(subset=["ts_code", "trade_date"], inplace=True)
                    if not combined.empty:
                        written = await save_us_to_db(combined)
                        total_records += written
                    del all_dfs, combined
                    gc.collect()
            await asyncio.sleep(0.5 + random.uniform(0, 0.3))

    logger.info("美股增量更新完成 ✅ 共 %d 条（腾讯=%d, yf_fallback=%d）",
                total_records, tencent_ok, len(tencent_fail_tickers))

    return total_records


# ============================================================
# 9. 辅助函数
# ============================================================

async def has_us_today_data(min_stocks: int = 100) -> bool:
    """检查是否已有最新交易日的美股数据。

    美股约 500+（S&P500）只活跃标的，阈值设为 100。

    逻辑：
      - 定时任务在北京时间 05:30 触发（≈美东 16:30 盘后）
      - 此时需要拉取的是 **美东前一个交易日** 的收盘数据
      - 通过计算「DB 最新日期」与「最近一个美股交易日」之间是否有
        缺失的交易日来判断，避免 gap<=2 在周末/长假期间误判
    """
    today = date.today()
    async with async_session() as session:
        max_date_result = await session.execute(
            select(func.max(StockDailyQuote.trade_date))
            .where(StockDailyQuote.market == "US")
        )
        max_date = max_date_result.scalar()
        if max_date is None:
            logger.info("has_us_today_data: 数据库无美股数据")
            return False

        gap_days = (today - max_date).days

        count_result = await session.execute(
            select(func.count(func.distinct(StockDailyQuote.ts_code)))
            .where(StockDailyQuote.trade_date == max_date)
            .where(StockDailyQuote.market == "US")
        )
        stock_count = count_result.scalar() or 0

    # 计算从 DB 最新日期的下一天到昨天之间有多少个美股交易日（周一~周五）
    # 定时任务 05:30 北京时间 ≈ 前一天美东收盘，所以目标日期是 today - 1
    target_date = today - timedelta(days=1)
    missing_trade_days = 0
    d = max_date + timedelta(days=1)
    while d <= target_date:
        if d.weekday() < 5:  # 周一~周五
            missing_trade_days += 1
        d += timedelta(days=1)

    logger.info(
        "has_us_today_data: DB最新日期=%s, 距今%d天, 该日%d只美股, "
        "目标日期=%s, 缺失交易日=%d（阈值: missing=0 且 stocks>=%d）",
        max_date, gap_days, stock_count, target_date, missing_trade_days, min_stocks,
    )
    # 没有缺失交易日，且最新日期有足够数据
    return missing_trade_days == 0 and stock_count >= min_stocks


async def load_us_from_db(min_date: date | None = None) -> pd.DataFrame:
    """从 PostgreSQL 加载美股行情数据。

    Returns:
        包含行情数据的 DataFrame（英文列名）。
    """
    if min_date is None:
        min_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).date()

    async with async_session() as session:
        result = await session.execute(
            select(StockDailyQuote)
            .where(StockDailyQuote.market == "US")
            .where(StockDailyQuote.trade_date >= min_date)
            .order_by(StockDailyQuote.ts_code, StockDailyQuote.trade_date)
        )
        rows = result.scalars().all()

    if not rows:
        return pd.DataFrame()

    data = []
    for r in rows:
        data.append({
            "ts_code": r.ts_code,
            "name": r.name,
            "trade_date": r.trade_date,
            "open": r.open,
            "close": r.close,
            "high": r.high,
            "low": r.low,
            "volume": r.volume,
            "amount": r.amount,
            "pct_change": r.pct_change,
            "change": r.change,
        })

    df = pd.DataFrame(data)
    logger.info("从 PostgreSQL 加载 %d 条美股记录（>= %s）", len(df), min_date)
    return df


# ============================================================
# 10. 直接运行入口（开发调试用）
# ============================================================

if __name__ == "__main__":
    import asyncio as _asyncio

    async def _main():
        df = await get_all_us_stock_data()
        if not df.empty:
            print("\n===== 美股数据预览 =====")
            print(df.head(10))
            print(f"\n股票数量: {df['ts_code'].nunique()}")
            print(f"记录总数: {len(df)}")
            print(f"日期范围: {df['trade_date'].min()} ~ {df['trade_date'].max()}")
        else:
            print("[ERROR] 未获取到有效美股数据。")

    _asyncio.run(_main())
