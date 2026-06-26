# coding=utf-8
"""
AI 分析结果格式化模块

将 AI 分析结果格式化为各推送渠道的样式
"""

import html as html_lib
import re
from typing import Any, Dict, Literal
from .analyzer import AIAnalysisResult
from .economic_analyzer import EconomicAnalysisResult, ASSET_WHITELIST, PROFILES


def _escape_html(text: str) -> str:
    """转义 HTML 特殊字符，防止 XSS 攻击"""
    return html_lib.escape(text) if text else ""


def _format_list_content(text: str) -> str:
    """
    格式化列表内容，确保序号前有换行
    例如将 "1. xxx 2. yyy" 转换为:
    1. xxx
    2. yyy
    """
    if not text:
        return ""
    
    # 去除首尾空白，防止 AI 返回的内容开头就有换行导致显示空行
    text = text.strip()

    # 0. 合并序号与紧随的【标签】（防御性处理）
    # 将 "1.\n【投资者】：" 或 "1. 【投资者】：" 合并为 "1. 投资者："
    text = re.sub(r'(\d+\.)\s*【([^】]+)】([:：]?)', r'\1 \2：', text)

    # 1. 规范化：确保 "1." 后面有空格
    result = re.sub(r'(\d+)\.([^ \d])', r'\1. \2', text)

    # 2. 强制换行：匹配 "数字."，且前面不是换行符
    #    (?!\d) 排除版本号/小数（如 2.0、3.5），避免将其误判为列表序号
    result = re.sub(r'(?<=[^\n])\s+(\d+\.)(?!\d)', r'\n\1', result)
    
    # 3. 处理 "1.**粗体**" 这种情况（虽然 Prompt 要求不输出 Markdown，但防御性处理）
    result = re.sub(r'(?<=[^\n])(\d+\.\*\*)', r'\n\1', result)

    # 4. 处理中文标点后的换行（排除版本号/小数）
    result = re.sub(r'([：:;,。；，])\s*(\d+\.)(?!\d)', r'\1\n\2', result)

    # 5. 处理 "XX方面："、"XX领域：" 等子标题换行
    # 只有在中文标点（句号、逗号、分号等）后才触发换行，避免破坏 "1. XX领域：" 格式
    result = re.sub(r'([。！？；，、])\s*([a-zA-Z0-9\u4e00-\u9fa5]+(方面|领域)[:：])', r'\1\n\2', result)

    # 6. 处理 【标签】 格式
    # 6a. 标签前确保空行分隔（文本开头除外）
    result = re.sub(r'(?<=\S)\n*(【[^】]+】)', r'\n\n\1', result)
    # 6b. 合并标签与被换行拆开的冒号：【tag】\n： → 【tag】：
    result = re.sub(r'(【[^】]+】)\n+([:：])', r'\1\2', result)
    # 6c. 标签后（含可选冒号），如果紧跟非空白非冒号内容则另起一行
    # 用 (?=[^\s:：]) 避免正则回溯将冒号误判为"内容"而拆开 【tag】：
    result = re.sub(r'(【[^】]+】[:：]?)[ \t]*(?=[^\s:：])', r'\1\n', result)

    # 7. 在列表项之间增加视觉空行（排除版本号/小数）
    # 排除 【标签】 行（以】结尾）和子标题行（以冒号结尾）之后的情况，避免标题与首项之间出现空行
    result = re.sub(r'(?<![:：】])\n(\d+\.)(?!\d)', r'\n\n\1', result)

    return result


def _format_standalone_summaries(
    summaries: dict, bracket_left: str = "[", bracket_right: str = "]"
) -> str:
    """格式化独立展示区概括为纯文本行，每个源名称单独一行

    Args:
        summaries: 源名称 -> 概括文本 的字典
        bracket_left/bracket_right: 源名称两侧的方括号字符。飞书卡片 2.0 markdown
            基于 CommonMark，裸 ``[源名]:`` 会被当作「链接引用定义」整段吞掉，
            故飞书须传入 HTML 实体 ``&#91;`` ``&#93;``（其余渠道用默认裸方括号）。
    """
    if not summaries:
        return ""
    lines = []
    for source_name, summary in summaries.items():
        if summary:
            lines.append(f"{bracket_left}{source_name}{bracket_right}:\n{summary}")
    return "\n\n".join(lines)


def _render_ai_analysis_markdown_like(
    result: AIAnalysisResult, standalone_brackets=("[", "]")
) -> str:
    """Markdown 系渠道的通用渲染骨架（飞书 / 企业微信 / ntfy / Slack 共用）

    Args:
        standalone_brackets: 独立源点速览中源名两侧的括号字符。飞书卡片 markdown
            须用 HTML 实体 ``("&#91;", "&#93;")`` 避免源名被「链接引用定义」吞掉，
            其余渠道沿用默认裸方括号。
    """
    if not result.success:
        if result.skipped:
            return f"ℹ️ {result.error}"
        return f"⚠️ AI 分析失败: {result.error}"

    lines = ["**✨ AI 热点分析**", ""]

    if result.core_trends:
        lines.extend(["**核心热点态势**", _format_list_content(result.core_trends), ""])

    if result.sentiment_controversy:
        lines.extend(
            ["**舆论风向争议**", _format_list_content(result.sentiment_controversy), ""]
        )

    if result.signals:
        lines.extend(["**异动与弱信号**", _format_list_content(result.signals), ""])

    if result.rss_insights:
        lines.extend(
            ["**RSS 深度洞察**", _format_list_content(result.rss_insights), ""]
        )

    if result.outlook_strategy:
        lines.extend(
            ["**研判策略建议**", _format_list_content(result.outlook_strategy), ""]
        )

    if result.standalone_summaries:
        summaries_text = _format_standalone_summaries(
            result.standalone_summaries, *standalone_brackets
        )
        if summaries_text:
            lines.extend(["**独立源点速览**", summaries_text])

    return "\n".join(lines)


def render_ai_analysis_markdown(result: AIAnalysisResult) -> str:
    """渲染为通用 Markdown 格式（企业微信、ntfy、Slack）"""
    return _render_ai_analysis_markdown_like(result)


def render_ai_analysis_feishu(result: AIAnalysisResult) -> str:
    """渲染为飞书卡片 2.0 markdown 格式

    飞书卡片 markdown 基于 CommonMark，裸 ``[源名]:`` 会被解析为「链接引用定义」
    (link reference definition) 而整段不显示，故独立源点速览的源名改用 HTML 实体
    方括号 ``&#91;`` ``&#93;``（与 report/formatter.py 标题来源标签的处理一致）。
    """
    return _render_ai_analysis_markdown_like(
        result, standalone_brackets=("&#91;", "&#93;")
    )


def render_ai_analysis_dingtalk(result: AIAnalysisResult) -> str:
    """渲染为钉钉 Markdown 格式"""
    if not result.success:
        if result.skipped:
            return f"ℹ️ {result.error}"
        return f"⚠️ AI 分析失败: {result.error}"

    lines = ["### ✨ AI 热点分析", ""]

    if result.core_trends:
        lines.extend(
            ["#### 核心热点态势", _format_list_content(result.core_trends), ""]
        )

    if result.sentiment_controversy:
        lines.extend(
            [
                "#### 舆论风向争议",
                _format_list_content(result.sentiment_controversy),
                "",
            ]
        )

    if result.signals:
        lines.extend(["#### 异动与弱信号", _format_list_content(result.signals), ""])

    if result.rss_insights:
        lines.extend(
            ["#### RSS 深度洞察", _format_list_content(result.rss_insights), ""]
        )

    if result.outlook_strategy:
        lines.extend(
            ["#### 研判策略建议", _format_list_content(result.outlook_strategy), ""]
        )

    if result.standalone_summaries:
        summaries_text = _format_standalone_summaries(result.standalone_summaries)
        if summaries_text:
            lines.extend(["#### 独立源点速览", summaries_text])

    return "\n".join(lines)


def render_ai_analysis_plain(result: AIAnalysisResult) -> str:
    """渲染为纯文本格式"""
    if not result.success:
        if result.skipped:
            return result.error
        return f"AI 分析失败: {result.error}"

    lines = ["【✨ AI 热点分析】", ""]

    if result.core_trends:
        lines.extend(["[核心热点态势]", _format_list_content(result.core_trends), ""])

    if result.sentiment_controversy:
        lines.extend(
            ["[舆论风向争议]", _format_list_content(result.sentiment_controversy), ""]
        )

    if result.signals:
        lines.extend(["[异动与弱信号]", _format_list_content(result.signals), ""])

    if result.rss_insights:
        lines.extend(["[RSS 深度洞察]", _format_list_content(result.rss_insights), ""])

    if result.outlook_strategy:
        lines.extend(["[研判策略建议]", _format_list_content(result.outlook_strategy), ""])

    if result.standalone_summaries:
        summaries_text = _format_standalone_summaries(result.standalone_summaries)
        if summaries_text:
            lines.extend(["[独立源点速览]", summaries_text])

    return "\n".join(lines)


def render_ai_analysis_telegram(result: AIAnalysisResult) -> str:
    """渲染为 Telegram HTML 格式（配合 parse_mode: HTML）

    Telegram Bot API 的 HTML 模式仅支持有限标签：
    <b>, <i>, <u>, <s>, <code>, <pre>, <a href="">, <blockquote>
    换行直接使用 \\n，不支持 <br>, <div>, <h1>-<h6> 等标签。
    """
    if not result.success:
        if result.skipped:
            return f"ℹ️ {_escape_html(result.error)}"
        return f"⚠️ AI 分析失败: {_escape_html(result.error)}"

    lines = ["<b>✨ AI 热点分析</b>", ""]

    if result.core_trends:
        lines.extend(["<b>核心热点态势</b>", _escape_html(_format_list_content(result.core_trends)), ""])

    if result.sentiment_controversy:
        lines.extend(["<b>舆论风向争议</b>", _escape_html(_format_list_content(result.sentiment_controversy)), ""])

    if result.signals:
        lines.extend(["<b>异动与弱信号</b>", _escape_html(_format_list_content(result.signals)), ""])

    if result.rss_insights:
        lines.extend(["<b>RSS 深度洞察</b>", _escape_html(_format_list_content(result.rss_insights)), ""])

    if result.outlook_strategy:
        lines.extend(["<b>研判策略建议</b>", _escape_html(_format_list_content(result.outlook_strategy)), ""])

    if result.standalone_summaries:
        summaries_text = _format_standalone_summaries(result.standalone_summaries)
        if summaries_text:
            lines.extend(["<b>独立源点速览</b>", _escape_html(summaries_text)])

    return "\n".join(lines)


def get_ai_analysis_renderer(channel: str):
    """根据渠道获取对应的渲染函数"""
    renderers = {
        "feishu": render_ai_analysis_feishu,
        "dingtalk": render_ai_analysis_dingtalk,
        "wework": render_ai_analysis_markdown,
        "telegram": render_ai_analysis_telegram,
        "email": render_ai_analysis_html_rich,  # 邮件使用丰富样式，配合 HTML 报告的 CSS
        "ntfy": render_ai_analysis_markdown,
        "bark": render_ai_analysis_plain,
        "slack": render_ai_analysis_markdown,
    }
    return renderers.get(channel, render_ai_analysis_markdown)


def render_ai_analysis_html_rich(result: AIAnalysisResult) -> str:
    """渲染为丰富样式的 HTML 格式（HTML 报告用）"""
    if not result:
        return ""

    # 检查是否成功
    if not result.success:
        if result.skipped:
            return f"""
                <div class="ai-section">
                    <div class="ai-info">ℹ️ {_escape_html(str(result.error))}</div>
                </div>"""
        error_msg = result.error or "未知错误"
        return f"""
                <div class="ai-section">
                    <div class="ai-warning">AI 分析失败: {_escape_html(str(error_msg))}</div>
                </div>"""

    ai_html = """
                <div class="ai-section">
                    <div class="ai-section-header">
                        <div class="ai-section-title">✨ AI 热点分析</div>
                        <span class="ai-section-badge">AI</span>
                    </div>
                    <div class="ai-blocks-grid">"""

    if result.core_trends:
        content = _format_list_content(result.core_trends)
        content_html = _escape_html(content).replace("\n", "<br>")
        ai_html += f"""
                    <div class="ai-block">
                        <div class="ai-block-title">核心热点态势</div>
                        <div class="ai-block-content">{content_html}</div>
                    </div>"""

    if result.sentiment_controversy:
        content = _format_list_content(result.sentiment_controversy)
        content_html = _escape_html(content).replace("\n", "<br>")
        ai_html += f"""
                    <div class="ai-block">
                        <div class="ai-block-title">舆论风向争议</div>
                        <div class="ai-block-content">{content_html}</div>
                    </div>"""

    if result.signals:
        content = _format_list_content(result.signals)
        content_html = _escape_html(content).replace("\n", "<br>")
        ai_html += f"""
                    <div class="ai-block">
                        <div class="ai-block-title">异动与弱信号</div>
                        <div class="ai-block-content">{content_html}</div>
                    </div>"""

    if result.rss_insights:
        content = _format_list_content(result.rss_insights)
        content_html = _escape_html(content).replace("\n", "<br>")
        ai_html += f"""
                    <div class="ai-block">
                        <div class="ai-block-title">RSS 深度洞察</div>
                        <div class="ai-block-content">{content_html}</div>
                    </div>"""

    if result.outlook_strategy:
        content = _format_list_content(result.outlook_strategy)
        content_html = _escape_html(content).replace("\n", "<br>")
        ai_html += f"""
                    <div class="ai-block">
                        <div class="ai-block-title">研判策略建议</div>
                        <div class="ai-block-content">{content_html}</div>
                    </div>"""

    if result.standalone_summaries:
        summaries_text = _format_standalone_summaries(result.standalone_summaries)
        if summaries_text:
            summaries_html = _escape_html(summaries_text).replace("\n", "<br>")
            ai_html += f"""
                    <div class="ai-block">
                        <div class="ai-block-title">独立源点速览</div>
                        <div class="ai-block-content">{summaries_html}</div>
                    </div>"""

    ai_html += """
                    </div>
                </div>"""
    return ai_html


_PROFILE_LABELS = {
    "conservative": "保守型",
    "balanced": "平衡型",
    "aggressive": "激进型",
}


def render_economic_analysis_html_rich(
    result: EconomicAnalysisResult,
    macro_conclusion: str = "",
) -> str:
    """渲染经济分析与资产配置为丰富 HTML（HTML 报告用）

    macro_conclusion: 由 AI 热点分析（AIAnalysisResult.macro_conclusion）提供的
    "热点 + 经济趋势" 综合结论；若非空，渲染在本区块底部。
    """
    if not result:
        # 即使经济分析整体未启用，也可能有 macro_conclusion 想单独展示
        if not macro_conclusion:
            return ""
        return _render_macro_conclusion_only(macro_conclusion)

    if not result.success:
        if result.skipped:
            return f"""
                <div class="ai-section">
                    <div class="ai-section-header">
                        <div class="ai-section-title">📊 经济分析与资产配置</div>
                        <span class="ai-section-badge">AI</span>
                    </div>
                    <div class="ai-info">ℹ️ {_escape_html(str(result.error))}</div>
                    {_render_macro_conclusion_block(macro_conclusion)}
                </div>"""
        # AI 失败：尽量用已抓到的快照数据兜底展示原始行情
        error_msg = result.error or "未知错误"
        fallback_html = _render_snapshot_fallback(result)
        if fallback_html:
            return f"""
                <div class="ai-section">
                    <div class="ai-section-header">
                        <div class="ai-section-title">📊 经济分析与资产配置</div>
                        <span class="ai-section-badge">AI</span>
                    </div>
                    <div class="ai-warning">AI 分析暂不可用: {_escape_html(str(error_msg))}（以下为原始行情兜底展示）</div>
                    {fallback_html}
                    {_render_macro_conclusion_block(macro_conclusion)}
                </div>"""
        return f"""
                <div class="ai-section">
                    <div class="ai-section-header">
                        <div class="ai-section-title">📊 经济分析与资产配置</div>
                        <span class="ai-section-badge">AI</span>
                    </div>
                    <div class="ai-warning">经济分析失败: {_escape_html(str(error_msg))}</div>
                    {_render_macro_conclusion_block(macro_conclusion)}
                </div>"""

    html = """
                <div class="ai-section">
                    <div class="ai-section-header">
                        <div class="ai-section-title">📊 经济分析与资产配置</div>
                        <span class="ai-section-badge">AI</span>
                    </div>
                    <div class="ai-blocks-grid">"""

    if result.global_trends:
        content_html = _escape_html(_format_list_content(result.global_trends)).replace("\n", "<br>")
        html += f"""
                    <div class="ai-block">
                        <div class="ai-block-title">全球宏观研判</div>
                        <div class="ai-block-content">{content_html}</div>
                    </div>"""

    if result.china_trends:
        content_html = _escape_html(_format_list_content(result.china_trends)).replace("\n", "<br>")
        html += f"""
                    <div class="ai-block">
                        <div class="ai-block-title">国内宏观研判</div>
                        <div class="ai-block-content">{content_html}</div>
                    </div>"""

    if result.key_risks:
        risks_html = "<br>".join(f"• {_escape_html(r)}" for r in result.key_risks)
        html += f"""
                    <div class="ai-block">
                        <div class="ai-block-title">关键风险</div>
                        <div class="ai-block-content">{risks_html}</div>
                    </div>"""

    html += """
                    </div>"""

    if result.allocations:
        html += _render_allocation_table(result)

    if result.allocation_rationale:
        html += """
                    <div class="ai-blocks-grid">"""
        for profile in PROFILES:
            rationale = result.allocation_rationale.get(profile, "")
            if not rationale:
                continue
            label = _PROFILE_LABELS.get(profile, profile)
            content_html = _escape_html(_format_list_content(rationale)).replace("\n", "<br>")
            html += f"""
                    <div class="ai-block">
                        <div class="ai-block-title">{_escape_html(label)} · 配置逻辑</div>
                        <div class="ai-block-content">{content_html}</div>
                    </div>"""
        html += """
                    </div>"""

    # 元数据脚注
    meta_lines = []
    if result.snapshot_time:
        meta_lines.append(f"快照时间: {_escape_html(result.snapshot_time)}")
    if result.sources_used:
        meta_lines.append(f"数据源: {_escape_html(', '.join(result.sources_used))}")
    if result.finance_news_count:
        meta_lines.append(f"参考财经新闻: {result.finance_news_count} 条")
    if result.fetch_errors:
        meta_lines.append(f"抓取异常: {len(result.fetch_errors)} 条")
    if result.validation_warnings:
        meta_lines.append(f"配置归一化警告: {len(result.validation_warnings)} 条")

    if meta_lines or result.disclaimer:
        html += """
                    <div class="ai-info" style="margin-top: 12px; font-size: 12px;">"""
        if result.disclaimer:
            html += f"""
                        <div>{_escape_html(result.disclaimer)}</div>"""
        if meta_lines:
            html += f"""
                        <div style="margin-top: 6px; opacity: 0.75;">{' · '.join(meta_lines)}</div>"""
        html += """
                    </div>"""

    html += _render_macro_conclusion_block(macro_conclusion)

    html += """
                </div>"""
    return html


def _render_macro_conclusion_block(macro_conclusion: str) -> str:
    """渲染综合宏观研判结论卡片（嵌入经济分析区底部）。空字符串返回空。"""
    text = (macro_conclusion or "").strip()
    if not text:
        return ""
    content_html = _escape_html(_format_list_content(text)).replace("\n", "<br>")
    return f"""
                    <div class="ai-block" style="margin-top: 16px; border-left: 4px solid #2563eb; background: rgba(37, 99, 235, 0.06);">
                        <div class="ai-block-title">🧭 综合研判结论（热点 × 经济趋势）</div>
                        <div class="ai-block-content">{content_html}</div>
                    </div>"""


def _render_macro_conclusion_only(macro_conclusion: str) -> str:
    """当经济分析未启用、但仍有 macro_conclusion 时，单独渲染一个轻量 section。"""
    text = (macro_conclusion or "").strip()
    if not text:
        return ""
    content_html = _escape_html(_format_list_content(text)).replace("\n", "<br>")
    return f"""
                <div class="ai-section">
                    <div class="ai-section-header">
                        <div class="ai-section-title">🧭 综合研判结论</div>
                        <span class="ai-section-badge">AI</span>
                    </div>
                    <div class="ai-block" style="border-left: 4px solid #2563eb; background: rgba(37, 99, 235, 0.06);">
                        <div class="ai-block-content">{content_html}</div>
                    </div>
                </div>"""


def _render_allocation_table(result: EconomicAnalysisResult) -> str:
    """渲染资产配置三档对比表。"""
    # 仅展示至少一档非零的资产，避免长表全 0 行
    visible_assets = [
        asset for asset in ASSET_WHITELIST
        if any(result.allocations.get(p, {}).get(asset, 0) > 0 for p in PROFILES)
    ]
    if not visible_assets:
        return ""

    header_cells = "".join(
        f'<th style="padding: 6px 10px; text-align: right; border-bottom: 1px solid rgba(0,0,0,0.1);">{_escape_html(_PROFILE_LABELS.get(p, p))}</th>'
        for p in PROFILES
    )

    rows_html = ""
    for asset in visible_assets:
        cells = ""
        for p in PROFILES:
            pct = result.allocations.get(p, {}).get(asset, 0)
            cell_style = "padding: 5px 10px; text-align: right; border-bottom: 1px solid rgba(0,0,0,0.05);"
            if pct > 0:
                cells += f'<td style="{cell_style} font-weight: 600;">{pct}%</td>'
            else:
                cells += f'<td style="{cell_style} opacity: 0.3;">—</td>'
        rows_html += f"""
                            <tr>
                                <td style="padding: 5px 10px; border-bottom: 1px solid rgba(0,0,0,0.05);">{_escape_html(asset)}</td>
                                {cells}
                            </tr>"""

    # 总和行（用于校验）
    totals = []
    for p in PROFILES:
        s = sum(result.allocations.get(p, {}).values())
        totals.append(f'<td style="padding: 6px 10px; text-align: right; font-weight: 700; border-top: 2px solid rgba(0,0,0,0.15);">{s}%</td>')
    totals_row = f"""
                            <tr>
                                <td style="padding: 6px 10px; font-weight: 700; border-top: 2px solid rgba(0,0,0,0.15);">合计</td>
                                {''.join(totals)}
                            </tr>"""

    return f"""
                    <div class="ai-block" style="margin-top: 16px;">
                        <div class="ai-block-title">三档资产配置（百分比）</div>
                        <div class="ai-block-content" style="overflow-x: auto;">
                            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                                <thead>
                                    <tr>
                                        <th style="padding: 6px 10px; text-align: left; border-bottom: 1px solid rgba(0,0,0,0.1);">资产</th>
                                        {header_cells}
                                    </tr>
                                </thead>
                                <tbody>{rows_html}{totals_row}
                                </tbody>
                            </table>
                        </div>
                    </div>"""


# 兜底渲染：板块名 → 中文标题
_SNAPSHOT_SECTION_LABELS = (
    ("a_stock", "A 股指数"),
    ("a_stock_industry", "A 股行业"),
    ("hk_stock", "港股"),
    ("us_stock", "美股"),
    ("commodities", "商品"),
    ("fx", "汇率"),
    ("bonds", "债券"),
)


def _format_price_value(price: Any) -> str:
    if price is None or price == "":
        return "—"
    try:
        p = float(price)
        if abs(p) >= 1000:
            return f"{p:,.2f}"
        return f"{p:.4f}".rstrip("0").rstrip(".") or "0"
    except (ValueError, TypeError):
        return _escape_html(str(price))


def _format_change_pct(pct: Any) -> str:
    if pct is None or pct == "":
        return ""
    try:
        v = float(pct)
    except (ValueError, TypeError):
        return _escape_html(str(pct))
    color = "#16a34a" if v >= 0 else "#dc2626"
    sign = "+" if v >= 0 else ""
    return f'<span style="color: {color}; font-weight: 600;">{sign}{v:.2f}%</span>'


def _render_snapshot_section_table(title: str, rows: Dict[str, Dict[str, Any]]) -> str:
    """渲染单个数据板块（如 A股、港股）为 HTML 表格。"""
    if not rows:
        return ""
    # 过滤掉无价格的项
    visible = [(name, d) for name, d in rows.items() if d and d.get("price") is not None]
    if not visible:
        return ""

    body_rows = ""
    for name, d in visible:
        price_html = _format_price_value(d.get("price"))
        change_html = _format_change_pct(d.get("change_pct"))
        body_rows += f"""
                            <tr>
                                <td style="padding: 5px 10px; border-bottom: 1px solid rgba(0,0,0,0.05);">{_escape_html(name)}</td>
                                <td style="padding: 5px 10px; text-align: right; border-bottom: 1px solid rgba(0,0,0,0.05); font-variant-numeric: tabular-nums;">{price_html}</td>
                                <td style="padding: 5px 10px; text-align: right; border-bottom: 1px solid rgba(0,0,0,0.05); font-variant-numeric: tabular-nums;">{change_html}</td>
                            </tr>"""

    return f"""
                    <div class="ai-block">
                        <div class="ai-block-title">{_escape_html(title)}</div>
                        <div class="ai-block-content" style="overflow-x: auto;">
                            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                                <thead>
                                    <tr>
                                        <th style="padding: 6px 10px; text-align: left; border-bottom: 1px solid rgba(0,0,0,0.1);">资产</th>
                                        <th style="padding: 6px 10px; text-align: right; border-bottom: 1px solid rgba(0,0,0,0.1);">价格</th>
                                        <th style="padding: 6px 10px; text-align: right; border-bottom: 1px solid rgba(0,0,0,0.1);">涨跌幅</th>
                                    </tr>
                                </thead>
                                <tbody>{body_rows}
                                </tbody>
                            </table>
                        </div>
                    </div>"""


def _render_snapshot_fallback(result: EconomicAnalysisResult) -> str:
    """LLM 失败时的兜底：把已抓到的原始行情数据以表格形式展示出来。"""
    snap = result.snapshot_data or {}
    if not snap:
        return ""

    sections_html = ""
    for key, label in _SNAPSHOT_SECTION_LABELS:
        sections_html += _render_snapshot_section_table(label, snap.get(key) or {})

    # 中国宏观（结构为 {indicator: {value, as_of}}，单独渲染）
    china_macro = snap.get("china_macro") or {}
    if china_macro:
        rows = ""
        for k, v in china_macro.items():
            if v is None or v == "":
                continue
            if isinstance(v, dict):
                raw_val = v.get("value")
                as_of = v.get("as_of") or ""
            else:
                raw_val = v
                as_of = ""
            # 跳过 NaN / None / 空值
            try:
                fval = float(raw_val) if raw_val is not None else None
                if fval is None or fval != fval:  # NaN check
                    continue
                value_html = f"{fval:.2f}".rstrip("0").rstrip(".") or "0"
            except (ValueError, TypeError):
                if raw_val is None or raw_val == "":
                    continue
                value_html = _escape_html(str(raw_val))
            as_of_html = _escape_html(str(as_of)) if as_of else ""
            rows += f"""
                            <tr>
                                <td style="padding: 5px 10px; border-bottom: 1px solid rgba(0,0,0,0.05);">{_escape_html(str(k))}</td>
                                <td style="padding: 5px 10px; text-align: right; border-bottom: 1px solid rgba(0,0,0,0.05); font-variant-numeric: tabular-nums;">{value_html}</td>
                                <td style="padding: 5px 10px; text-align: right; border-bottom: 1px solid rgba(0,0,0,0.05); color: #6b7280; font-size: 12px;">{as_of_html}</td>
                            </tr>"""
        if rows:
            sections_html += f"""
                    <div class="ai-block">
                        <div class="ai-block-title">中国宏观</div>
                        <div class="ai-block-content" style="overflow-x: auto;">
                            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                                <thead>
                                    <tr>
                                        <th style="padding: 6px 10px; text-align: left; border-bottom: 1px solid rgba(0,0,0,0.1);">指标</th>
                                        <th style="padding: 6px 10px; text-align: right; border-bottom: 1px solid rgba(0,0,0,0.1);">数值</th>
                                        <th style="padding: 6px 10px; text-align: right; border-bottom: 1px solid rgba(0,0,0,0.1);">截至日期</th>
                                    </tr>
                                </thead>
                                <tbody>{rows}
                                </tbody>
                            </table>
                        </div>
                    </div>"""

    if not sections_html:
        return ""

    meta_lines = []
    if result.snapshot_time:
        meta_lines.append(f"快照时间: {_escape_html(result.snapshot_time)}")
    if result.sources_used:
        meta_lines.append(f"数据源: {_escape_html(', '.join(result.sources_used))}")
    if result.fetch_errors:
        meta_lines.append(f"抓取异常: {len(result.fetch_errors)} 条")

    meta_html = ""
    if meta_lines:
        meta_html = f"""
                    <div class="ai-info" style="margin-top: 12px; font-size: 12px; opacity: 0.8;">{' · '.join(meta_lines)}</div>"""

    return f"""
                    <div class="ai-blocks-grid">{sections_html}
                    </div>{meta_html}"""


# ============================================================
# 推送渠道经济分析渲染器（飞书 / 钉钉 / 企业微信 / Telegram / ntfy / Bark / Slack / Generic Webhook）
# ============================================================
#
# 设计要点：
# 1. verbosity="full" 用于字节预算宽松的渠道（飞书、钉钉），渲染完整内容
#    （三档配置 + 配置逻辑 + 元数据 + 免责声明）。
# 2. verbosity="compact" 用于紧凑渠道（企业微信、Telegram、ntfy、Bark、Slack、
#    Generic Webhook），仅保留核心信息：宏观研判 / 关键风险 / 配置表 + 快照时间。
#    去掉配置逻辑与免责声明，控制单条消息字节占用。
# 3. 错误/跳过路径只输出一行提示，不渲染兜底快照表（避免在紧凑渠道炸预算）。


def _format_economic_allocation_table_markdown(result: EconomicAnalysisResult) -> str:
    """渲染三档资产配置表为 Markdown 表格（飞书 / 钉钉 / 企业微信 / Slack / ntfy 通用）。

    仅展示至少有一档非零的资产，行末百分比；同时输出合计行用于校验。
    若无可见行，返回空字符串。
    """
    visible_assets = [
        asset for asset in ASSET_WHITELIST
        if any(result.allocations.get(p, {}).get(asset, 0) > 0 for p in PROFILES)
    ]
    if not visible_assets:
        return ""

    headers = ["资产"] + [_PROFILE_LABELS.get(p, p) for p in PROFILES]
    header_line = "| " + " | ".join(headers) + " |"
    sep_line = "| " + " | ".join(["---"] + [":---:"] * len(PROFILES)) + " |"

    body_lines = []
    for asset in visible_assets:
        cells = [asset]
        for p in PROFILES:
            pct = result.allocations.get(p, {}).get(asset, 0)
            cells.append(f"{pct}%" if pct > 0 else "—")
        body_lines.append("| " + " | ".join(cells) + " |")

    totals = ["合计"] + [f"{sum(result.allocations.get(p, {}).values())}%" for p in PROFILES]
    body_lines.append("| " + " | ".join(totals) + " |")

    return "\n".join([header_line, sep_line] + body_lines)


def _format_economic_allocation_table_plain(result: EconomicAnalysisResult) -> str:
    """渲染三档配置为对齐的纯文本表格（Telegram / Bark 用）。"""
    visible_assets = [
        asset for asset in ASSET_WHITELIST
        if any(result.allocations.get(p, {}).get(asset, 0) > 0 for p in PROFILES)
    ]
    if not visible_assets:
        return ""

    headers = ["资产"] + [_PROFILE_LABELS.get(p, p) for p in PROFILES]
    rows = [headers]
    for asset in visible_assets:
        row = [asset]
        for p in PROFILES:
            pct = result.allocations.get(p, {}).get(asset, 0)
            row.append(f"{pct}%" if pct > 0 else "—")
        rows.append(row)
    rows.append(["合计"] + [f"{sum(result.allocations.get(p, {}).values())}%" for p in PROFILES])

    # 计算每列最大显示宽度（中文按 2，其余按 1 估算）
    def _w(s: str) -> int:
        return sum(2 if ord(c) > 127 else 1 for c in s)

    col_widths = [max(_w(row[i]) for row in rows) for i in range(len(headers))]

    def _pad(s: str, width: int) -> str:
        return s + " " * max(0, width - _w(s))

    return "\n".join(
        "  ".join(_pad(cell, col_widths[i]) for i, cell in enumerate(row))
        for row in rows
    )


def _render_economic_markdown_like(
    result: EconomicAnalysisResult,
    verbosity: Literal["full", "compact"] = "full",
) -> str:
    """Markdown 系渠道（飞书 / 企业微信 / ntfy / Slack / Generic Webhook）的共享渲染骨架。

    - verbosity="full"：保留三档配置 + 配置逻辑 + 元数据 + 免责声明
    - verbosity="compact"：仅保留宏观研判 / 关键风险 / 配置表 + 快照时间
    """
    if not result:
        return ""

    if not result.success:
        if result.skipped:
            return f"ℹ️ {result.error}"
        return f"⚠️ 经济分析失败: {result.error}"

    lines = ["**📊 经济分析与资产配置**", ""]

    if result.global_trends:
        lines.extend(["**全球宏观研判**", _format_list_content(result.global_trends), ""])

    if result.china_trends:
        lines.extend(["**国内宏观研判**", _format_list_content(result.china_trends), ""])

    if result.key_risks:
        risks_text = "\n".join(f"• {r}" for r in result.key_risks if r)
        if risks_text:
            lines.extend(["**关键风险**", risks_text, ""])

    if result.allocations:
        table_md = _format_economic_allocation_table_markdown(result)
        if table_md:
            lines.extend(["**资产配置建议**", table_md, ""])

    if verbosity == "full":
        if result.allocation_rationale:
            for profile in PROFILES:
                rationale = result.allocation_rationale.get(profile, "")
                if not rationale:
                    continue
                label = _PROFILE_LABELS.get(profile, profile)
                lines.extend([f"**{label} · 配置逻辑**", _format_list_content(rationale), ""])

        meta_lines = []
        if result.snapshot_time:
            meta_lines.append(f"快照时间: {result.snapshot_time}")
        if result.sources_used:
            meta_lines.append(f"数据源: {', '.join(result.sources_used)}")
        if result.finance_news_count:
            meta_lines.append(f"参考财经新闻: {result.finance_news_count} 条")
        if meta_lines:
            lines.append(" · ".join(meta_lines))
        if result.disclaimer:
            lines.append(result.disclaimer)
    else:
        # compact：仅保留快照时间
        if result.snapshot_time:
            lines.append(f"快照时间: {result.snapshot_time}")

    return "\n".join(lines).rstrip()


def render_economic_analysis_markdown(
    result: EconomicAnalysisResult,
    verbosity: Literal["full", "compact"] = "full",
) -> str:
    """渲染为通用 Markdown 格式（企业微信 / ntfy / Slack / Generic Webhook）"""
    return _render_economic_markdown_like(result, verbosity=verbosity)


def render_economic_analysis_feishu(
    result: EconomicAnalysisResult,
    verbosity: Literal["full", "compact"] = "full",
) -> str:
    """渲染为飞书卡片 2.0 markdown 格式

    飞书卡片 markdown 基于 CommonMark，与企业微信渲染主体一致。
    """
    return _render_economic_markdown_like(result, verbosity=verbosity)


def render_economic_analysis_dingtalk(
    result: EconomicAnalysisResult,
    verbosity: Literal["full", "compact"] = "full",
) -> str:
    """渲染为钉钉 Markdown 格式（### / #### 标题层级）"""
    if not result:
        return ""

    if not result.success:
        if result.skipped:
            return f"ℹ️ {result.error}"
        return f"⚠️ 经济分析失败: {result.error}"

    lines = ["### 📊 经济分析与资产配置", ""]

    if result.global_trends:
        lines.extend(["#### 全球宏观研判", _format_list_content(result.global_trends), ""])

    if result.china_trends:
        lines.extend(["#### 国内宏观研判", _format_list_content(result.china_trends), ""])

    if result.key_risks:
        risks_text = "\n".join(f"- {r}" for r in result.key_risks if r)
        if risks_text:
            lines.extend(["#### 关键风险", risks_text, ""])

    if result.allocations:
        table_md = _format_economic_allocation_table_markdown(result)
        if table_md:
            lines.extend(["#### 资产配置建议", table_md, ""])

    if verbosity == "full":
        if result.allocation_rationale:
            for profile in PROFILES:
                rationale = result.allocation_rationale.get(profile, "")
                if not rationale:
                    continue
                label = _PROFILE_LABELS.get(profile, profile)
                lines.extend([f"#### {label} · 配置逻辑", _format_list_content(rationale), ""])

        meta_lines = []
        if result.snapshot_time:
            meta_lines.append(f"快照时间: {result.snapshot_time}")
        if result.sources_used:
            meta_lines.append(f"数据源: {', '.join(result.sources_used)}")
        if result.finance_news_count:
            meta_lines.append(f"参考财经新闻: {result.finance_news_count} 条")
        if meta_lines:
            lines.append(" · ".join(meta_lines))
        if result.disclaimer:
            lines.append(result.disclaimer)
    else:
        if result.snapshot_time:
            lines.append(f"快照时间: {result.snapshot_time}")

    return "\n".join(lines).rstrip()


def render_economic_analysis_telegram(
    result: EconomicAnalysisResult,
    verbosity: Literal["full", "compact"] = "full",
) -> str:
    """渲染为 Telegram HTML 格式（parse_mode: HTML）

    Telegram HTML 模式仅支持有限标签：<b>, <i>, <code>, <pre>, <a>, <blockquote>。
    不支持 <table>，配置表以 <pre> 包裹纯文本对齐表呈现。
    """
    if not result:
        return ""

    if not result.success:
        if result.skipped:
            return f"ℹ️ {_escape_html(result.error)}"
        return f"⚠️ 经济分析失败: {_escape_html(result.error)}"

    lines = ["<b>📊 经济分析与资产配置</b>", ""]

    if result.global_trends:
        lines.extend(
            ["<b>全球宏观研判</b>", _escape_html(_format_list_content(result.global_trends)), ""]
        )

    if result.china_trends:
        lines.extend(
            ["<b>国内宏观研判</b>", _escape_html(_format_list_content(result.china_trends)), ""]
        )

    if result.key_risks:
        risks_text = "\n".join(f"• {_escape_html(r)}" for r in result.key_risks if r)
        if risks_text:
            lines.extend(["<b>关键风险</b>", risks_text, ""])

    if result.allocations:
        table_plain = _format_economic_allocation_table_plain(result)
        if table_plain:
            lines.extend(
                ["<b>资产配置建议</b>", f"<pre>{_escape_html(table_plain)}</pre>", ""]
            )

    if verbosity == "full":
        if result.allocation_rationale:
            for profile in PROFILES:
                rationale = result.allocation_rationale.get(profile, "")
                if not rationale:
                    continue
                label = _PROFILE_LABELS.get(profile, profile)
                lines.extend(
                    [
                        f"<b>{_escape_html(label)} · 配置逻辑</b>",
                        _escape_html(_format_list_content(rationale)),
                        "",
                    ]
                )

        meta_lines = []
        if result.snapshot_time:
            meta_lines.append(f"快照时间: {result.snapshot_time}")
        if result.sources_used:
            meta_lines.append(f"数据源: {', '.join(result.sources_used)}")
        if result.finance_news_count:
            meta_lines.append(f"参考财经新闻: {result.finance_news_count} 条")
        if meta_lines:
            lines.append(_escape_html(" · ".join(meta_lines)))
        if result.disclaimer:
            lines.append(_escape_html(result.disclaimer))
    else:
        if result.snapshot_time:
            lines.append(_escape_html(f"快照时间: {result.snapshot_time}"))

    return "\n".join(lines).rstrip()


def render_economic_analysis_plain(
    result: EconomicAnalysisResult,
    verbosity: Literal["full", "compact"] = "full",
) -> str:
    """渲染为纯文本格式（Bark 等不支持 Markdown 的渠道）"""
    if not result:
        return ""

    if not result.success:
        if result.skipped:
            return result.error
        return f"经济分析失败: {result.error}"

    lines = ["【📊 经济分析与资产配置】", ""]

    if result.global_trends:
        lines.extend(["[全球宏观研判]", _format_list_content(result.global_trends), ""])

    if result.china_trends:
        lines.extend(["[国内宏观研判]", _format_list_content(result.china_trends), ""])

    if result.key_risks:
        risks_text = "\n".join(f"• {r}" for r in result.key_risks if r)
        if risks_text:
            lines.extend(["[关键风险]", risks_text, ""])

    if result.allocations:
        table_plain = _format_economic_allocation_table_plain(result)
        if table_plain:
            lines.extend(["[资产配置建议]", table_plain, ""])

    if verbosity == "full":
        if result.allocation_rationale:
            for profile in PROFILES:
                rationale = result.allocation_rationale.get(profile, "")
                if not rationale:
                    continue
                label = _PROFILE_LABELS.get(profile, profile)
                lines.extend([f"[{label} · 配置逻辑]", _format_list_content(rationale), ""])

        meta_lines = []
        if result.snapshot_time:
            meta_lines.append(f"快照时间: {result.snapshot_time}")
        if result.sources_used:
            meta_lines.append(f"数据源: {', '.join(result.sources_used)}")
        if result.finance_news_count:
            meta_lines.append(f"参考财经新闻: {result.finance_news_count} 条")
        if meta_lines:
            lines.append(" · ".join(meta_lines))
        if result.disclaimer:
            lines.append(result.disclaimer)
    else:
        if result.snapshot_time:
            lines.append(f"快照时间: {result.snapshot_time}")

    return "\n".join(lines).rstrip()


def get_economic_analysis_renderer(channel: str):
    """根据渠道获取经济分析渲染函数。

    返回的渲染函数签名为 ``(result, verbosity="full") -> str``。
    email 渠道沿用 HTML 报告嵌入路径（render_economic_analysis_html_rich），
    此处不返回 email 渲染器；调用方应只为非 email 渠道调用本函数。
    """
    renderers = {
        "feishu": render_economic_analysis_feishu,
        "dingtalk": render_economic_analysis_dingtalk,
        "wework": render_economic_analysis_markdown,
        "telegram": render_economic_analysis_telegram,
        "ntfy": render_economic_analysis_markdown,
        "bark": render_economic_analysis_plain,
        "slack": render_economic_analysis_markdown,
        "generic_webhook": render_economic_analysis_markdown,
    }
    return renderers.get(channel, render_economic_analysis_markdown)
