# coding=utf-8
"""
经济数据获取模块

数据源分工：
    - 腾讯财经 qt.gtimg.cn（A股指数/A股行业/港股指数）：免认证、批量、稳定，
      在 GitHub Actions 美国 runner 上可达，是国内行情的主路径。
    - AKShare（中国宏观 CPI/PMI/M2、中债 10Y）：仅用于月度宏观指标。
      东财行情链路在境外节点会被掐，所以行情不再走 akshare。
    - yfinance（美股/美债/商品/汇率）：海外行情，可达性高。

依赖说明：
    - requests 是必装项（项目本来就用）。
    - akshare 与 yfinance 是可选依赖；缺失时对应数据源整段跳过。
    - yfinance 在国内访问 Yahoo Finance 通常需要代理；通过
      economic_analysis.use_proxy / proxy_url 配置控制。
"""

import os
import socket
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

# ---- 资产/指标白名单 ----------------------------------------------------------
# value: 腾讯财经 symbol（带 sh/sz 前缀）或 yfinance ticker。
# 修改此处需要同步 economic_analysis_prompt.txt 中的资产清单。
A_STOCK_INDICES = {
    "沪深300": "sh000300",
    "中证500": "sh000905",
    "中证1000": "sh000852",
}

A_STOCK_INDUSTRIES = {
    # 中证行业指数（细分行业）
    "半导体": "sh000827",
    "新能源车": "sz399976",
    "消费": "sh000932",
    "医药": "sh000933",
    "银行": "sh000934",
    "高股息红利": "sh000922",
}

HK_INDICES = {
    # 腾讯港股指数 symbol：hk + 大写代码
    "恒生科技": "hkHSTECH",
    "港股高股息": "hkHSCEI",  # 退而求其次：用国企指数代理"高股息"
}

TENCENT_QUOTE_URL = "https://qt.gtimg.cn/q={symbols}"
TENCENT_HEADERS = {
    "Referer": "https://stockapp.finance.qq.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
}

US_INDICES_YF = {
    "纳斯达克100": "^NDX",
    "标普500": "^GSPC",
}

BONDS_YF = {
    "美国国债10Y": "^TNX",
}

COMMODITIES_YF = {
    "黄金": "GC=F",
    "原油WTI": "CL=F",
    "比特币": "BTC-USD",
}

FX_YF = {
    # 名称与资产白名单中的"美元人民币现金"对齐：以汇率作为该现金类资产的参考价
    "美元人民币现金": "CNY=X",
}


@dataclass
class EconomicSnapshot:
    """单次抓取的经济数据快照"""
    snapshot_time: str = ""          # ISO 时间戳
    a_stock: Dict[str, Dict[str, Any]] = field(default_factory=dict)   # {资产: {price, change_pct, ...}}
    a_stock_industry: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    hk_stock: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    us_stock: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    bonds: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    commodities: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    fx: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    china_macro: Dict[str, Any] = field(default_factory=dict)
    fetch_errors: List[str] = field(default_factory=list)
    sources_used: List[str] = field(default_factory=list)


class EconomicDataFetcher:
    """
    抓取宏观与行情数据，输出标准化快照。

    所有外部库都是 try-import；缺失时该数据源整段跳过，并把错误记录在
    snapshot.fetch_errors 中。调用方可基于此判断快照可用性。
    """

    def __init__(
        self,
        use_proxy: bool = False,
        proxy_url: str = "",
        get_time_func: Optional[Callable[[], datetime]] = None,
        debug: bool = False,
        request_timeout: float = 10.0,
    ):
        self.use_proxy = use_proxy
        self.proxy_url = proxy_url.strip()
        self.get_time_func = get_time_func or datetime.now
        self.debug = debug
        self.request_timeout = request_timeout

        # 配置 yfinance 的代理（akshare 走国内站不需要）
        if self.use_proxy and self.proxy_url:
            os.environ.setdefault("HTTPS_PROXY", self.proxy_url)
            os.environ.setdefault("HTTP_PROXY", self.proxy_url)

        # 提高 socket 默认超时下限，避免裸 socket 调用堵塞数十秒
        # （仅在比当前默认更短时才设置，避免覆盖用户全局配置）
        if socket.getdefaulttimeout() is None or socket.getdefaulttimeout() > self.request_timeout * 2:
            socket.setdefaulttimeout(self.request_timeout * 2)

    # ---- 公共入口 ----------------------------------------------------------
    def fetch_snapshot(self) -> EconomicSnapshot:
        snap = EconomicSnapshot(
            snapshot_time=self.get_time_func().strftime("%Y-%m-%d %H:%M:%S"),
        )

        # 腾讯：A股 + 港股 行情。免依赖，必跑。
        try:
            self._fetch_tencent_quotes(snap)
            snap.sources_used.append("tencent")
        except Exception as e:
            snap.fetch_errors.append(f"[腾讯] 整段失败: {type(e).__name__}: {e}")

        # AKShare：仅宏观指标（CPI/PMI/M2/中债10Y）。可选依赖。
        akshare = self._try_import("akshare")
        if akshare is not None:
            snap.sources_used.append("akshare")
            self._fetch_china_bonds(akshare, snap)
            self._fetch_china_macro(akshare, snap)

        # yfinance：海外行情。可选依赖。
        yfinance = self._try_import("yfinance")
        if yfinance is not None:
            snap.sources_used.append("yfinance")
            self._fetch_us_stock(yfinance, snap)
            self._fetch_us_bonds(yfinance, snap)
            self._fetch_commodities(yfinance, snap)
            self._fetch_fx(yfinance, snap)

        if not snap.sources_used:
            snap.fetch_errors.append(
                "所有数据源均不可用。请检查网络，或安装 akshare / yfinance。"
            )

        return snap

    # ---- 腾讯财经 qt.gtimg.cn ----------------------------------------------
    def _fetch_tencent_quotes(self, snap: EconomicSnapshot) -> None:
        """
        一次性批量拉取所有 A 股指数 + 行业指数 + 港股指数。

        响应是 GBK 编码的多行 JS 变量赋值，每行形如：
            v_sh000300="1~沪深300~000300~4941.60~4931.39~...";
        字段按 ~ 分割，下标：
            [3]  现价
            [4]  昨收
            [5]  今开
            [30] 时间戳（A股: 20260618161407 / 港股: 2026/06/18 16:08:28）
            [31] 涨跌额
            [32] 涨跌幅%
        """
        all_symbols: List[Tuple[str, str, Dict[str, Dict[str, Any]]]] = []
        for name, sym in A_STOCK_INDICES.items():
            all_symbols.append((name, sym, snap.a_stock))
        for name, sym in A_STOCK_INDUSTRIES.items():
            all_symbols.append((name, sym, snap.a_stock_industry))
        for name, sym in HK_INDICES.items():
            all_symbols.append((name, sym, snap.hk_stock))

        symbols_param = ",".join(s for _, s, _ in all_symbols)
        url = TENCENT_QUOTE_URL.format(symbols=symbols_param)

        text = self._run_with_timeout(
            "腾讯-批量行情",
            lambda: self._http_get_text(url, encoding="gb18030"),
            snap,
        )
        if not text:
            return

        parsed = self._parse_tencent_payload(text)
        for name, sym, target in all_symbols:
            row = parsed.get(sym)
            if row is None:
                snap.fetch_errors.append(f"[腾讯] {name} ({sym}) 未在响应中")
                continue
            try:
                price = float(row[3]) if row[3] else 0.0
                prev = float(row[4]) if row[4] else 0.0
                change_pct = float(row[32]) if len(row) > 32 and row[32] else (
                    ((price - prev) / prev * 100) if prev else 0.0
                )
                as_of = row[30] if len(row) > 30 else ""
                target[name] = {
                    "symbol": sym,
                    "price": round(price, 4),
                    "prev_close": round(prev, 4),
                    "change_pct": round(change_pct, 2),
                    "as_of": as_of,
                }
            except (ValueError, IndexError) as e:
                snap.fetch_errors.append(f"[腾讯] {name} ({sym}) 解析失败: {e}")

    def _http_get_text(self, url: str, encoding: str = "utf-8") -> str:
        resp = requests.get(
            url,
            headers=TENCENT_HEADERS,
            timeout=self.request_timeout,
        )
        resp.encoding = encoding
        resp.raise_for_status()
        return resp.text

    @staticmethod
    def _parse_tencent_payload(text: str) -> Dict[str, List[str]]:
        """把 v_xxx="...";  多行响应解析成 {symbol: [fields...]}"""
        out: Dict[str, List[str]] = {}
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("v_") or "=" not in line:
                continue
            head, _, rest = line.partition("=")
            symbol = head[2:]  # 去掉 "v_"
            payload = rest.strip().rstrip(";").strip('"')
            out[symbol] = payload.split("~")
        return out

    # ---- AKShare 数据源（仅宏观）-------------------------------------------
    def _fetch_china_bonds(self, ak, snap: EconomicSnapshot) -> None:
        df = self._run_with_timeout("中债收益率", ak.bond_zh_us_rate, snap)
        if df is None:
            return
        try:
            if df.empty:
                snap.fetch_errors.append("[中债] 收益率为空")
                return
            last = df.iloc[-1]
            cn10 = last.get("中国国债收益率10年")
            if cn10 is not None:
                snap.bonds["中国国债10Y"] = {
                    "yield_pct": float(cn10),
                    "as_of": str(last.get("日期", "")),
                }
        except Exception as e:
            snap.fetch_errors.append(f"[中债] 解析失败: {type(e).__name__}: {e}")

    def _fetch_china_macro(self, ak, snap: EconomicSnapshot) -> None:
        # 国家统计局数据更新频率低（月度），抓最新一期即可
        macro_calls = [
            ("CPI同比", lambda: ak.macro_china_cpi_yearly()),
            ("PMI制造业", lambda: ak.macro_china_pmi_yearly()),
            ("M2同比", lambda: ak.macro_china_m2_yearly()),
        ]
        for name, fn in macro_calls:
            df = self._run_with_timeout(f"宏观-{name}", fn, snap)
            if df is None:
                continue
            try:
                if df.empty:
                    continue
                last = df.iloc[-1]
                value = last.get("今值") if "今值" in df.columns else last.iloc[-1]
                snap.china_macro[name] = {
                    "value": float(value) if value not in (None, "") else None,
                    "as_of": str(last.get("日期", last.get("商品", ""))),
                }
            except Exception as e:
                snap.fetch_errors.append(f"[宏观] {name} 解析失败: {type(e).__name__}")

    # ---- yfinance 数据源 ---------------------------------------------------
    def _fetch_us_stock(self, yf, snap: EconomicSnapshot) -> None:
        for name, ticker in US_INDICES_YF.items():
            self._safe_fetch_yf(yf, name, ticker, snap.us_stock, snap)

    def _fetch_us_bonds(self, yf, snap: EconomicSnapshot) -> None:
        for name, ticker in BONDS_YF.items():
            self._safe_fetch_yf(yf, name, ticker, snap.bonds, snap, is_yield=True)

    def _fetch_commodities(self, yf, snap: EconomicSnapshot) -> None:
        for name, ticker in COMMODITIES_YF.items():
            self._safe_fetch_yf(yf, name, ticker, snap.commodities, snap)

    def _fetch_fx(self, yf, snap: EconomicSnapshot) -> None:
        for name, ticker in FX_YF.items():
            self._safe_fetch_yf(yf, name, ticker, snap.fx, snap)

    def _safe_fetch_yf(
        self, yf, name: str, ticker: str, target: Dict, snap: EconomicSnapshot, is_yield: bool = False
    ) -> None:
        hist = self._run_with_timeout(
            f"yfinance-{name}",
            lambda: yf.Ticker(ticker).history(period="5d"),
            snap,
        )
        if hist is None:
            return
        try:
            if hist.empty or len(hist) < 1:
                snap.fetch_errors.append(f"[yfinance] {name} ({ticker}) 数据为空")
                return
            close = float(hist["Close"].iloc[-1])
            prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else close
            change_pct = ((close - prev_close) / prev_close * 100) if prev_close else 0.0
            entry = {
                "symbol": ticker,
                "price": round(close, 4),
                "prev_close": round(prev_close, 4),
                "change_pct": round(change_pct, 2),
                "as_of": str(hist.index[-1].date()),
            }
            if is_yield:
                # ^TNX 报价 = 实际收益率 * 10，需要除以 10 换成百分比
                entry["yield_pct"] = round(close / 10, 3)
            target[name] = entry
        except Exception as e:
            snap.fetch_errors.append(f"[yfinance] {name} ({ticker}) 解析失败: {type(e).__name__}: {e}")

    # ---- 工具 --------------------------------------------------------------
    @staticmethod
    def _try_import(module_name: str):
        try:
            return __import__(module_name)
        except ImportError:
            print(f"[Economic] 可选依赖 {module_name} 未安装，跳过相关数据源")
            return None

    def _run_with_timeout(self, label: str, fn: Callable[[], Any], snap: "EconomicSnapshot") -> Any:
        """
        在独立线程中执行 fn，最多等待 self.request_timeout 秒。
        超时返回 None 并把错误记录到 snap.fetch_errors（线程仍会在后台跑完，
        但我们不再关心它的结果）。
        """
        result_box: Dict[str, Any] = {"value": None, "error": None}

        def runner() -> None:
            try:
                result_box["value"] = fn()
            except BaseException as e:  # noqa: BLE001 - 捕获所有以避免线程吞错
                result_box["error"] = f"{type(e).__name__}: {e}"

        t = threading.Thread(target=runner, daemon=True, name=f"econ-fetch-{label}")
        t.start()
        t.join(self.request_timeout)

        if t.is_alive():
            snap.fetch_errors.append(f"[{label}] 超时（>{self.request_timeout}s）")
            if self.debug:
                print(f"[Economic][debug] {label} timeout")
            return None
        if result_box["error"]:
            snap.fetch_errors.append(f"[{label}] {result_box['error']}")
            if self.debug:
                print(f"[Economic][debug] {label} error: {result_box['error']}")
            return None
        return result_box["value"]


def snapshot_to_prompt_text(snap: EconomicSnapshot) -> str:
    """将快照渲染为给 LLM 的紧凑文本，节省 token。"""
    lines = [f"快照时间: {snap.snapshot_time}"]
    if snap.sources_used:
        lines.append(f"数据源: {', '.join(snap.sources_used)}")

    def render_section(title: str, data: Dict[str, Dict[str, Any]]) -> None:
        if not data:
            return
        lines.append(f"\n## {title}")
        for name, d in data.items():
            parts = [name]
            if "price" in d:
                parts.append(f"价={d['price']}")
            if "yield_pct" in d:
                parts.append(f"收益率={d['yield_pct']}%")
            if "change_pct" in d:
                parts.append(f"日涨跌={d['change_pct']}%")
            if d.get("as_of"):
                parts.append(f"@ {d['as_of']}")
            lines.append("- " + " ".join(parts))

    render_section("A股核心指数", snap.a_stock)
    render_section("A股行业", snap.a_stock_industry)
    render_section("港股", snap.hk_stock)
    render_section("美股", snap.us_stock)
    render_section("债券", snap.bonds)
    render_section("商品/数字货币", snap.commodities)
    render_section("汇率", snap.fx)

    if snap.china_macro:
        lines.append("\n## 中国宏观")
        for name, d in snap.china_macro.items():
            v = d.get("value")
            v_str = f"{v}" if v is not None else "N/A"
            lines.append(f"- {name}={v_str} @ {d.get('as_of', '')}")

    if snap.fetch_errors:
        lines.append(f"\n## 数据抓取异常（{len(snap.fetch_errors)}条）")
        for err in snap.fetch_errors[:10]:
            lines.append(f"- {err}")

    return "\n".join(lines)
