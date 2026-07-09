# coding=utf-8
"""
报告辅助函数模块

提供报告生成相关的通用辅助函数
"""

import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple


def clean_title(title: str) -> str:
    """清理标题中的特殊字符

    清理规则：
    - 将换行符(\n, \r)替换为空格
    - 将多个连续空白字符合并为单个空格
    - 去除首尾空白

    Args:
        title: 原始标题字符串

    Returns:
        清理后的标题字符串
    """
    if not isinstance(title, str):
        title = str(title)
    cleaned_title = title.replace("\n", " ").replace("\r", " ")
    cleaned_title = re.sub(r"\s+", " ", cleaned_title)
    cleaned_title = cleaned_title.strip()
    return cleaned_title


def html_escape(text: str) -> str:
    """HTML特殊字符转义

    转义规则（按顺序）：
    - & → &amp;
    - < → &lt;
    - > → &gt;
    - " → &quot;
    - ' → &#x27;

    Args:
        text: 原始文本

    Returns:
        转义后的文本
    """
    if not isinstance(text, str):
        text = str(text)

    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def calculate_rank_trend(rank_timeline=None, ranks=None):
    """根据排名时间线或排名列表计算趋势方向

    Args:
        rank_timeline: 按时间顺序的排名记录列表，如 [{"time": "10:00", "rank": 5}, ...]
        ranks: 排名列表

    Returns:
        "up" (排名上升/数值变小), "down" (排名下降/数值变大), 或 None
    """
    prev_rank = None
    curr_rank = None

    if rank_timeline:
        valid_ranks = [r["rank"] for r in rank_timeline if r.get("rank") is not None]
        if len(valid_ranks) >= 2:
            prev_rank = valid_ranks[-2]
            curr_rank = valid_ranks[-1]
    elif ranks and len(ranks) >= 2:
        prev_rank = ranks[-2]
        curr_rank = ranks[-1]

    if prev_rank is not None and curr_rank is not None:
        if curr_rank < prev_rank:
            return "up"
        elif curr_rank > prev_rank:
            return "down"
    return None


def format_rank_display(
    ranks: List[int],
    rank_threshold: int,
    format_type: str,
    rank_timeline: Optional[List[Dict]] = None,
) -> str:
    """格式化排名显示

    根据不同平台类型生成对应格式的排名字符串。
    当最小排名小于等于阈值时，使用高亮格式。

    Args:
        ranks: 排名列表（去重后的唯一值，用于范围显示）
        rank_threshold: 高亮阈值，小于等于此值的排名会高亮显示
        format_type: 平台类型，支持:
            - "html": HTML格式
            - "feishu": 飞书格式
            - "dingtalk": 钉钉格式
            - "wework": 企业微信格式
            - "telegram": Telegram格式
            - "slack": Slack格式
            - 其他: 默认markdown格式
        rank_timeline: 按时间顺序的排名记录列表（可选，用于计算趋势）

    Returns:
        格式化后的排名字符串，如 "[1]" 或 "[1 - 5]"
        如果排名列表为空，返回空字符串
    """
    if not ranks:
        return ""

    unique_ranks = sorted(set(ranks))
    min_rank = unique_ranks[0]
    max_rank = unique_ranks[-1]

    # 根据平台类型选择高亮格式
    if format_type == "html":
        highlight_start = "<font color='red'><strong>"
        highlight_end = "</strong></font>"
    elif format_type == "feishu":
        highlight_start = "<font color='red'>**"
        highlight_end = "**</font>"
    elif format_type == "dingtalk":
        highlight_start = "**"
        highlight_end = "**"
    elif format_type == "wework":
        highlight_start = "**"
        highlight_end = "**"
    elif format_type == "telegram":
        highlight_start = "<b>"
        highlight_end = "</b>"
    elif format_type == "slack":
        highlight_start = "*"
        highlight_end = "*"
    else:
        # 默认 markdown 格式
        highlight_start = "**"
        highlight_end = "**"

    # 生成排名显示
    rank_str = ""
    if min_rank <= rank_threshold:
        if min_rank == max_rank:
            rank_str = f"{highlight_start}[{min_rank}]{highlight_end}"
        else:
            rank_str = f"{highlight_start}[{min_rank} - {max_rank}]{highlight_end}"
    else:
        if min_rank == max_rank:
            rank_str = f"[{min_rank}]"
        else:
            rank_str = f"[{min_rank} - {max_rank}]"

    trend = calculate_rank_trend(rank_timeline, ranks)
    trend_arrow = {"up": "📈", "down": "📉"}.get(trend, "")

    return f"{rank_str} {trend_arrow}" if trend_arrow else rank_str


def _squarify(values: List[float], x: float, y: float, w: float, h: float) -> List[Dict]:
    """Squarified treemap layout algorithm (Bruls et al.).

    Args:
        values: item weights, must be pre-sorted desc and sum > 0
        x, y, w, h: bounding rect

    Returns:
        List of dicts {x, y, w, h} in the same order as values.
    """
    if not values or w <= 0 or h <= 0:
        return [{"x": x, "y": y, "w": 0, "h": 0} for _ in values]

    total = float(sum(values))
    if total <= 0:
        return [{"x": x, "y": y, "w": 0, "h": 0} for _ in values]

    # Normalize values to match rect area
    scale = (w * h) / total
    scaled = [v * scale for v in values]

    rects: List[Dict] = [None] * len(values)  # type: ignore

    def worst_ratio(row: List[float], side: float) -> float:
        if not row or side <= 0:
            return float("inf")
        s = sum(row)
        rmax = max(row)
        rmin = min(row)
        s_sq = s * s
        side_sq = side * side
        return max((side_sq * rmax) / s_sq, s_sq / (side_sq * rmin))

    def layout_row(row: List[float], indices: List[int], rx: float, ry: float,
                   rw: float, rh: float, horizontal: bool) -> None:
        s = sum(row)
        if s <= 0:
            return
        if horizontal:
            row_h = s / rw
            cx = rx
            for val, idx in zip(row, indices):
                cw = val / row_h if row_h > 0 else 0
                rects[idx] = {"x": cx, "y": ry, "w": cw, "h": row_h}
                cx += cw
        else:
            row_w = s / rh
            cy = ry
            for val, idx in zip(row, indices):
                ch = val / row_w if row_w > 0 else 0
                rects[idx] = {"x": rx, "y": cy, "w": row_w, "h": ch}
                cy += ch

    remaining = list(enumerate(scaled))
    rx, ry, rw, rh = x, y, w, h

    while remaining:
        horizontal = rw >= rh
        side = rh if horizontal else rw
        row_vals: List[float] = []
        row_idx: List[int] = []
        i = 0
        while i < len(remaining):
            candidate_vals = row_vals + [remaining[i][1]]
            if worst_ratio(candidate_vals, side) <= worst_ratio(row_vals, side):
                row_vals.append(remaining[i][1])
                row_idx.append(remaining[i][0])
                i += 1
            else:
                break

        if not row_vals:
            # single item too small — force one
            row_vals.append(remaining[0][1])
            row_idx.append(remaining[0][0])
            i = 1

        s = sum(row_vals)
        if horizontal:
            row_w = s / side if side > 0 else 0
            layout_row(row_vals, row_idx, rx, ry, rw, rh, horizontal=False)
            rx += row_w
            rw -= row_w
        else:
            row_h = s / side if side > 0 else 0
            layout_row(row_vals, row_idx, rx, ry, rw, rh, horizontal=True)
            ry += row_h
            rh -= row_h
        remaining = remaining[i:]

    # ensure all rects exist
    for i, r in enumerate(rects):
        if r is None:
            rects[i] = {"x": rx, "y": ry, "w": 0, "h": 0}
    return rects


def _render_treemap_tiles(
    items: List[Tuple[str, float]],
    total: float,
    width: float,
    height: float,
) -> str:
    """为给定尺寸生成 treemap tile 的 SVG 内容（不含 <svg> 外层）。"""
    values = [c for _, c in items]
    if not values or total <= 0:
        return ""

    rects = _squarify(values, 0.0, 0.0, float(width), float(height))
    max_count = values[0]
    tiles = ""

    for (word, count), rect in zip(items, rects):
        if rect["w"] < 0.5 or rect["h"] < 0.5:
            continue

        # 按占最大值的比例上色（避免整数/浮点阈值差异）
        rel = (count / max_count) if max_count > 0 else 0.0
        if rel >= 0.7:
            fill = "#dc2626"  # hot
        elif rel >= 0.35:
            fill = "#ea580c"  # warm
        else:
            fill = "#4f46e5"  # cool indigo
        text_color = "#ffffff"

        pct = (count / total) * 100
        escaped_word = html_escape(word)
        # 整数值就显示整数，浮点显示一位小数
        if abs(count - round(count)) < 0.01:
            count_display = str(int(round(count)))
        else:
            count_display = f"{count:.1f}"

        # Adaptive font size
        min_side = min(rect["w"], rect["h"])
        area = rect["w"] * rect["h"]
        font_size = max(9.0, min(18.0, (area ** 0.5) / 6.5))
        show_label = min_side >= 32 and rect["w"] >= 40
        show_count = min_side >= 22

        tiles += (
            f'<g class="treemap-tile">'
            f'<title>{escaped_word} · {count_display} ({pct:.1f}%)</title>'
            f'<rect x="{rect["x"]:.2f}" y="{rect["y"]:.2f}" '
            f'width="{rect["w"]:.2f}" height="{rect["h"]:.2f}" '
            f'fill="{fill}" stroke="#ffffff" stroke-width="2" rx="4" ry="4"/>'
        )
        if show_label:
            label_y = rect["y"] + rect["h"] / 2 - (font_size * 0.15)
            # Truncate label to fit width
            approx_char_w = font_size * 0.75  # 中文
            max_chars = max(1, int(rect["w"] / approx_char_w) - 1)
            display_word = word if len(word) <= max_chars else (word[: max(1, max_chars - 1)] + "…")
            tiles += (
                f'<text x="{rect["x"] + rect["w"] / 2:.2f}" y="{label_y:.2f}" '
                f'text-anchor="middle" dominant-baseline="middle" '
                f'fill="{text_color}" font-size="{font_size:.1f}" '
                f'font-weight="600" style="pointer-events:none;">{html_escape(display_word)}</text>'
            )
            if show_count:
                count_size = max(8.0, font_size * 0.7)
                tiles += (
                    f'<text x="{rect["x"] + rect["w"] / 2:.2f}" y="{rect["y"] + rect["h"] / 2 + font_size:.2f}" '
                    f'text-anchor="middle" dominant-baseline="middle" '
                    f'fill="{text_color}" font-size="{count_size:.1f}" '
                    f'opacity="0.85" style="pointer-events:none;">{count_display}</text>'
                )
        elif show_count:
            # Only room for the count
            tiles += (
                f'<text x="{rect["x"] + rect["w"] / 2:.2f}" y="{rect["y"] + rect["h"] / 2:.2f}" '
                f'text-anchor="middle" dominant-baseline="middle" '
                f'fill="{text_color}" font-size="10" '
                f'font-weight="600" style="pointer-events:none;">{count_display}</text>'
            )
        tiles += "</g>"

    return tiles


def render_news_treemap_svg(
    stats: List[Dict],
    width: int = 560,
    height: int = 320,
    title: str = "🗺️ 热点关键词分布",
    subtitle_prefix: str = "按命中数占比",
    portrait_width: int = 360,
    portrait_height: int = 420,
) -> str:
    """渲染新闻热点关键词 treemap 为响应式 inline SVG。

    输出包含两个 SVG：横向布局（desktop/tablet）和纵向布局（mobile），
    由 CSS media query 切换显示。每个 SVG 都用对应尺寸单独运行 squarified
    布局，保证 tile 比例在各视口下都不失真。

    Args:
        stats: 关键词分组列表 [{word, count, titles: [...]}]，也可以是从 raw titles
            通过 extract_trending_ngrams 得到的趋势条目
        width, height: 横向 SVG viewBox 尺寸（desktop）
        portrait_width, portrait_height: 纵向 SVG viewBox 尺寸（mobile）
        title: 标题文本
        subtitle_prefix: 副标题前缀（后面会自动附加 "共 N 条"）

    Returns:
        HTML 字符串，无数据时返回空字符串。
    """
    if not stats:
        return ""
    items = [(s.get("word", ""), float(s.get("count", 0))) for s in stats if s.get("count", 0) > 0]
    if not items:
        return ""

    items.sort(key=lambda x: x[1], reverse=True)
    total = sum(c for _, c in items)
    if total <= 0:
        return ""

    wide_tiles = _render_treemap_tiles(items, total, float(width), float(height))
    portrait_tiles = _render_treemap_tiles(items, total, float(portrait_width), float(portrait_height))

    # 副标题的计数：n-gram 趋势模式（subtitle_prefix 含"加权"）显示关键词数量，否则显示原始命中数
    if "加权" in subtitle_prefix:
        total_display = f"共 {len(items)} 个关键词"
    elif abs(total - round(total)) < 0.01:
        total_display = f"共 {int(round(total))} 条"
    else:
        total_display = f"共 {len(items)} 个关键词"

    return (
        '<div class="treemap-block treemap-news">'
        '<div class="treemap-header">'
        f'<div class="treemap-title">{title}</div>'
        f'<div class="treemap-subtitle">{subtitle_prefix} · {total_display}</div>'
        '</div>'
        f'<svg class="treemap-svg treemap-svg--wide" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="xMidYMid meet" role="img" aria-label="News keyword treemap">'
        f'{wide_tiles}</svg>'
        f'<svg class="treemap-svg treemap-svg--portrait" viewBox="0 0 {portrait_width} {portrait_height}" '
        f'preserveAspectRatio="xMidYMid meet" role="img" aria-label="News keyword treemap" aria-hidden="true">'
        f'{portrait_tiles}</svg>'
        '</div>'
    )


# ============================================================
# 全平台热点趋势提取（不依赖用户配置的关键词）
# ============================================================

# 通用中文停用词 —— 高频出现但语义空的词
_TRENDING_STOPWORDS = {
    # 单字/数字/标点已在 tokenizer 里过滤
    "视频", "图片", "组图", "热搜", "热议", "关注", "回应", "表示", "透露",
    "确认", "宣布", "公布", "发布", "披露", "曝光", "报道", "官方", "记者",
    "网友", "网传", "疑似", "据悉", "据说", "消息", "最新", "今天", "昨天",
    "明天", "今日", "昨日", "上午", "下午", "晚间", "凌晨", "深夜", "刚刚",
    "现场", "直播", "全文", "详情", "详细", "更多", "点击", "查看", "阅读",
    "评论", "点赞", "转发", "分享", "推荐", "热门", "推送", "更新",
    "什么", "怎么", "为什么", "如何", "是否", "还是", "还有", "已经",
    "可能", "或将", "将会", "有望", "此前", "此后", "之前", "之后",
    "以来", "以及", "以后", "而言", "而且", "然而", "但是", "不过",
    "一次", "一个", "一场", "一起", "一名", "一位", "一款", "一种",
    "两名", "两位", "两个", "多名", "多位", "多个", "数名", "数位",
    "记者", "编辑", "作者", "来源", "转自", "综合", "整理",
    "中国", "国家", "全国", "全球", "世界", "国内", "国际",
    "美国", "日本", "俄罗斯",  # 常见但过于泛的国名
    "报道称", "报道指", "报导", "微博", "抖音", "快手", "小红书", "知乎",
    "网易", "腾讯", "新浪", "搜狐", "百度",
    "澎湃", "新华社", "人民日报", "央视", "环球", "第一财经",
    # 知乎问句模板
    "如何评价", "如何看待", "怎么看", "怎么样", "有哪些", "是什么",
}

# 不完整短语判定：以这些虚词/介词/助词结尾或开头的 n-gram 通常是切片碎片
_INCOMPLETE_ENDS = {"被", "的", "了", "在", "到", "于", "是", "把", "对", "为", "与", "和", "或", "及", "从", "向"}
_INCOMPLETE_STARTS = {"被", "的", "了", "在", "到", "于", "是", "把", "对", "为", "与", "和", "或", "及", "从", "向", "并", "而", "则"}

# 中文正则：连续汉字段
_CHINESE_RUN = re.compile(r"[一-龥]+")


def extract_trending_ngrams(
    raw_results: Dict[str, Dict[str, Dict]],
    top_n: int = 20,
    min_ngram: int = 2,
    max_ngram: int = 4,
    stopwords: Optional[set] = None,
) -> List[Dict]:
    """从所有抓取到的原始标题中提取热门 n-gram，按热榜排名加权。

    这不依赖用户的关键词配置：把每条标题按平台排名加权（rank 1 权重最大，
    30+ 权重接近 0），对连续汉字段的所有 n-gram 计频，去除停用词后取 top N。
    然后做重叠去重：若长 n-gram 与短 n-gram 相互包含且长的权重 ≥ 短的 60%，
    保留长的丢短的（"房价上涨" > "房价"），反之亦然。

    Args:
        raw_results: {source_id: {title: {ranks: [int, ...], ...}}}
        top_n: 返回的最多条目数
        min_ngram, max_ngram: n-gram 字符长度范围
        stopwords: 自定义停用词集合（会与内置 _TRENDING_STOPWORDS 合并）

    Returns:
        [{word, count, ...}, ...]，与 render_news_treemap_svg 兼容。
        count 是浮点加权得分（treemap 会自动归一化面积）。
    """
    if not raw_results:
        return []

    stops = set(_TRENDING_STOPWORDS)
    if stopwords:
        stops.update(stopwords)

    # n-gram → (加权得分, 覆盖的标题集合)
    scores: Dict[str, float] = defaultdict(float)
    ngram_titles: Dict[str, set] = defaultdict(set)

    for _, titles_data in raw_results.items():
        if not isinstance(titles_data, dict):
            continue
        for title, meta in titles_data.items():
            if not title or not isinstance(title, str):
                continue
            # 提取排名权重
            ranks = []
            if isinstance(meta, dict):
                ranks = meta.get("ranks") or []
            # 用最优排名（数值最小）作为该标题的热度
            best_rank = None
            for r in ranks:
                try:
                    rv = int(r)
                    if best_rank is None or rv < best_rank:
                        best_rank = rv
                except (ValueError, TypeError):
                    continue
            # 权重函数：top1 = 30, top30 = 1, 更靠后不计
            if best_rank is None:
                weight = 1.0  # 无排名信息也算 1 分兜底
            elif best_rank >= 31:
                continue
            else:
                weight = float(max(1, 31 - best_rank))

            # 提取所有连续汉字段
            for run in _CHINESE_RUN.findall(title):
                run_len = len(run)
                if run_len < min_ngram:
                    continue
                # 生成所有 n-gram
                for n in range(min_ngram, min(max_ngram, run_len) + 1):
                    for i in range(run_len - n + 1):
                        gram = run[i:i + n]
                        if gram in stops:
                            continue
                        # 过滤纯重复字符（如 "啊啊"）
                        if len(set(gram)) == 1:
                            continue
                        # 过滤以虚词/助词开头或结尾的碎片
                        if gram[0] in _INCOMPLETE_STARTS or gram[-1] in _INCOMPLETE_ENDS:
                            continue
                        scores[gram] += weight
                        ngram_titles[gram].add(title)

    if not scores:
        return []

    # 至少要出现在 2 篇不同标题里，避免单条标题内部的偶然 n-gram
    filtered = [(g, s) for g, s in scores.items() if len(ngram_titles[g]) >= 2]
    if not filtered:
        # 兜底：如果全部只出现一次，取原始分数
        filtered = list(scores.items())

    # 先按分数从高到低排序（并列时按长度升序：更短的先入，代表更泛的关键词）
    # 但对于"同题碎片"抑制，我们需要长者先入 —— 采用两次遍历
    filtered.sort(key=lambda x: (-x[1], -len(x[0])))

    # 第一遍：抑制"同题碎片" —— 若一个 n-gram 出现在同一批标题里且已有更高分/等分的候选覆盖，则丢弃
    # 关键判据：ngram_titles[gram] 与已保留项完全相同 → 来自同一批病毒式标题的滑窗切片
    survivors: List[tuple] = []
    for gram, score in filtered:
        dominated = False
        gram_titles = ngram_titles[gram]
        for other_gram, other_score in survivors:
            other_titles = ngram_titles[other_gram]
            # 同题集：来自同一批标题 → 只保留一个（保留先入者，即分数更高/长度更长）
            if gram_titles == other_titles:
                dominated = True
                break
            # 子串同分：滑窗碎片
            if gram in other_gram and gram != other_gram and score <= other_score * 1.001 and score >= other_score * 0.9:
                dominated = True
                break
            # gram 的标题集是 other 的子集或超集（不完全相同也不完全独立）且分数相近 → 视为同题碎片
            if gram_titles < other_titles and score <= other_score * 1.001 and score >= other_score * 0.7:
                dominated = True
                break
            if gram_titles > other_titles and score <= other_score * 1.001 and score >= other_score * 0.7:
                # gram 的标题集包含 other 的 —— 分数应该更高，但如果分数接近 other，说明 gram 只是 other 的稍宽松版本，保留 other
                dominated = True
                break
        if not dominated:
            survivors.append((gram, score))

    # 第二遍：去重叠 —— 高分优先，当 n-gram 与已保留项相互包含时，
    # 若长者分数 ≥ 60% 短者分数，保留长者（更具体）；否则保留短者（更泛/更高分）
    survivors.sort(key=lambda x: x[1], reverse=True)
    kept: List[tuple] = []
    for gram, score in survivors:
        keep = True
        replace_idx = None
        for i, (kept_gram, kept_score) in enumerate(kept):
            if gram == kept_gram:
                keep = False
                break
            if gram in kept_gram or kept_gram in gram:
                if gram in kept_gram and gram != kept_gram:
                    keep = False
                    break
                if kept_gram in gram and gram != kept_gram:
                    if score >= 0.6 * kept_score:
                        replace_idx = i
                        break
                    else:
                        keep = False
                        break
        if keep:
            if replace_idx is not None:
                kept[replace_idx] = (gram, score)
            else:
                kept.append((gram, score))
        if len(kept) >= top_n:
            break

    return [{"word": g, "count": s, "titles": []} for g, s in kept[:top_n]]
