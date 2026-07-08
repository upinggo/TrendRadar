# coding=utf-8
"""
Treemap SVG → PNG 光栅化模块

将 report/helpers.py 与 ai/formatter.py 生成的 treemap SVG 转为 PNG 字节，
用于推送到支持图片的通知渠道（Telegram / Email / 企业微信）。

依赖 cairosvg（可选依赖）。缺失时打印一次警告并降级为文本推送。
"""

import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional

_SVG_RE = re.compile(r"(<svg\b[^>]*>)(.*?)(</svg>)", re.DOTALL)

# 优先级候选：按跨平台可用性由高到低排列
_CJK_FONT_CANDIDATES = (
    "Noto Sans CJK SC",
    "Noto Sans SC",
    "Source Han Sans SC",
    "PingFang SC",
    "Hiragino Sans GB",
    "Microsoft YaHei",
    "Heiti SC",
    "STHeiti",
    "Songti SC",
    "WenQuanYi Zen Hei",
    "WenQuanYi Micro Hei",
)


def _detect_installed_cjk_fonts() -> List[str]:
    """通过 fc-list 探测本机已安装的候选 CJK 字体，返回按 _CJK_FONT_CANDIDATES 顺序过滤后的列表。

    cairo 的字体选择不会像浏览器那样按 family list 逐个回退：只要首位 family 无法解析，
    往往就落到不含中文字形的默认 Latin sans，导致中文渲染成豆腐块。因此我们在生成 SVG 前
    把系统上真正存在的字体放到 font-family 列表最前面。
    """
    if not shutil.which("fc-list"):
        return []
    try:
        out = subprocess.run(
            ["fc-list", ":lang=zh"], capture_output=True, text=True, timeout=3
        ).stdout
    except Exception:
        return []
    installed = []
    for cand in _CJK_FONT_CANDIDATES:
        # fc-list 输出形如 "/path/font.ttf: Family Name,别名:style=..."
        if cand in out and cand not in installed:
            installed.append(cand)
    return installed


_DETECTED_FONTS = _detect_installed_cjk_fonts()
_FONT_FAMILY = ",".join(
    f'"{f}"' for f in (_DETECTED_FONTS or list(_CJK_FONT_CANDIDATES))
) + ",sans-serif"

_CJK_FONT_STYLE = f"<style>text{{font-family:{_FONT_FAMILY};}}</style>"

_warned_missing_dep = False


def _warn_once(msg: str) -> None:
    global _warned_missing_dep
    if not _warned_missing_dep:
        print(msg)
        _warned_missing_dep = True


_PRIMARY_FONT = (_DETECTED_FONTS or list(_CJK_FONT_CANDIDATES))[0]
_TEXT_TAG_RE = re.compile(r"<text\b(?![^>]*\bfont-family=)", re.IGNORECASE)


def _inject_font_style(svg: str) -> str:
    """确保 <text> 元素带上一个 cairosvg 能解析的 font-family。

    cairosvg 对 `<style>` 中的 CSS 支持并不完整（在某些环境下 <style> 里的 font-family
    不会应用到内联的 <text>），所以我们直接给每个未显式设置字体的 <text> 加上
    `font-family="<primary>"` 作为 SVG 呈现属性 —— 这是最兼容的做法。同时保留注入的
    <style> 作为浏览器端 fallback。
    """
    m = _SVG_RE.search(svg)
    if not m:
        return svg
    body = _TEXT_TAG_RE.sub(f'<text font-family=\'{_PRIMARY_FONT}\'', m.group(2))
    return f"{m.group(1)}{_CJK_FONT_STYLE}{body}{m.group(3)}"


def _extract_svg(html_wrapper: str) -> Optional[str]:
    """从 render_*_treemap_svg 返回的 HTML 包裹字符串中抽出 <svg>...</svg>。"""
    m = _SVG_RE.search(html_wrapper)
    if not m:
        return None
    return f"{m.group(1)}{m.group(2)}{m.group(3)}"


def _svg_to_png(html_wrapper: str, width: int = 1120, height: int = 640) -> Optional[bytes]:
    """把包裹了 HTML 的 SVG 光栅化为 PNG 字节。失败时返回 None，不抛异常。"""
    try:
        import cairosvg  # 延迟导入，可选依赖
    except ImportError:
        _warn_once(
            "[treemap] cairosvg 未安装，跳过图片推送。"
            "安装：pip install 'trendradar[image]' 并安装 libcairo 系统库。"
        )
        return None

    svg = _extract_svg(html_wrapper)
    if not svg:
        return None
    svg = _inject_font_style(svg)

    try:
        return cairosvg.svg2png(
            bytestring=svg.encode("utf-8"),
            output_width=width,
            output_height=height,
        )
    except Exception as e:
        print(f"[treemap] SVG 光栅化失败：{e}")
        return None


def render_treemap_pngs(
    report_data: Dict[str, Any],
    economic_analysis: Any = None,
    types: str = "both",
) -> Dict[str, bytes]:
    """
    渲染需要推送的 treemap PNG 集合。

    Args:
        report_data: 报告数据，可能包含 trending_ngrams 或 stats
        economic_analysis: 经济分析结果对象（含 snapshot_data 属性）
        types: 要生成的 treemap 类型（news | economic | both）

    Returns:
        {"news": bytes, "economic": bytes}，缺失/失败的类型不包含在结果里
    """
    out: Dict[str, bytes] = {}
    want = {"news", "economic"} if types == "both" else {types}

    if "news" in want:
        try:
            from trendradar.report.helpers import render_news_treemap_svg
            stats = (
                report_data.get("trending_ngrams")
                or report_data.get("stats")
                or []
            )
            if stats:
                html = render_news_treemap_svg(stats)
                png = _svg_to_png(html)
                if png:
                    out["news"] = png
        except Exception as e:
            print(f"[treemap] news treemap 生成失败：{e}")

    if "economic" in want and economic_analysis is not None:
        try:
            from trendradar.ai.formatter import render_economic_treemap_svg
            snapshot = getattr(economic_analysis, "snapshot_data", None) or {}
            if snapshot:
                html = render_economic_treemap_svg(snapshot)
                png = _svg_to_png(html)
                if png:
                    out["economic"] = png
        except Exception as e:
            print(f"[treemap] economic treemap 生成失败：{e}")

    return out


_CAPTIONS = {
    "news": "🗺️ 热点关键词分布",
    "economic": "📊 资产热力图",
}


def caption_for(name: str, report_type: str = "") -> str:
    """返回 treemap 图片的说明文字。"""
    base = _CAPTIONS.get(name, name)
    if report_type:
        return f"{base} · {report_type}"
    return base
