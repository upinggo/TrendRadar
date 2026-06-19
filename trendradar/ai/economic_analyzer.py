# coding=utf-8
"""
经济分析器：宏观研判 + 三档资产配置

接收实时经济数据快照、多周期变化、当日财经新闻，调用 LLM 输出
全球+国内趋势研判与三档（保守/平衡/激进）资产配置百分比。

强约束：
- 资产名称必须来自固定 17 项白名单
- 每档权重之和必须 = 100（自动归一化容差 ±2，否则报错）
- JSON 解析失败时自动重试一次（沿用 analyzer.py 的修复机制）
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Tuple

from trendradar.ai.client import AIClient
from trendradar.ai.economic_data import EconomicSnapshot, snapshot_to_prompt_text
from trendradar.ai.economic_snapshot_store import deltas_to_prompt_text
from trendradar.ai.prompt_loader import load_prompt_template


# 必须与 economic_analysis_prompt.txt 中的资产清单严格一致
ASSET_WHITELIST: Tuple[str, ...] = (
    "沪深300", "中证500", "中证1000",
    "半导体", "新能源车", "消费", "医药", "银行", "高股息红利",
    "恒生科技", "港股高股息",
    "纳斯达克100", "标普500",
    "中国国债10Y", "美国国债10Y",
    "黄金", "原油WTI", "比特币",
    "美元人民币现金", "人民币货币基金",
)

PROFILES = ("conservative", "balanced", "aggressive")

# 自动归一化的容差：|sum - 100| ≤ NORMALIZE_TOLERANCE 时按比例缩放
NORMALIZE_TOLERANCE = 2


@dataclass
class EconomicAnalysisResult:
    global_trends: str = ""
    china_trends: str = ""
    key_risks: List[str] = field(default_factory=list)
    allocations: Dict[str, Dict[str, int]] = field(default_factory=dict)   # {profile: {asset: pct}}
    allocation_rationale: Dict[str, str] = field(default_factory=dict)
    disclaimer: str = ""

    raw_response: str = ""
    success: bool = False
    skipped: bool = False
    error: str = ""

    snapshot_time: str = ""
    sources_used: List[str] = field(default_factory=list)
    fetch_errors: List[str] = field(default_factory=list)
    finance_news_count: int = 0
    validation_warnings: List[str] = field(default_factory=list)
    # 原始行情快照（LLM 失败时仍可用作回退展示的兜底数据）
    snapshot_data: Dict[str, Any] = field(default_factory=dict)


class EconomicAnalyzer:
    """宏观研判 + 资产配置。"""

    def __init__(
        self,
        ai_config: Dict[str, Any],
        economic_config: Dict[str, Any],
        get_time_func: Callable,
        debug: bool = False,
    ):
        self.ai_config = ai_config
        self.economic_config = economic_config
        self.get_time_func = get_time_func
        self.debug = debug

        self.client = AIClient(ai_config)
        valid, error = self.client.validate_config()
        if not valid:
            print(f"[Economic] AI 配置警告: {error}")

        self.language = economic_config.get("LANGUAGE", "Chinese")
        self.max_news = int(economic_config.get("MAX_NEWS", 80))

        self.system_prompt, self.user_prompt_template = load_prompt_template(
            economic_config.get("PROMPT_FILE", "economic_analysis_prompt.txt"),
            label="Economic",
        )

    def analyze(
        self,
        snapshot: EconomicSnapshot,
        trend_deltas: Optional[Dict[str, Dict[str, float]]] = None,
        finance_news: Optional[List[Dict[str, Any]]] = None,
    ) -> EconomicAnalysisResult:
        result = EconomicAnalysisResult(
            snapshot_time=snapshot.snapshot_time,
            sources_used=list(snapshot.sources_used),
            fetch_errors=list(snapshot.fetch_errors),
            snapshot_data=asdict(snapshot),
        )

        if not self.client.api_key:
            result.error = "未配置 AI API Key"
            return result

        if not snapshot.sources_used:
            result.skipped = True
            result.error = "无可用经济数据源（akshare / yfinance 均不可用），跳过分析"
            return result

        snapshot_text = snapshot_to_prompt_text(snapshot)
        deltas_text = deltas_to_prompt_text(trend_deltas or {})
        news_text, news_count = self._format_finance_news(finance_news or [])
        result.finance_news_count = news_count

        current_time = self.get_time_func().strftime("%Y-%m-%d %H:%M:%S")

        prompt = self.user_prompt_template
        prompt = prompt.replace("{current_time}", current_time)
        prompt = prompt.replace("{snapshot_text}", snapshot_text)
        prompt = prompt.replace("{trend_deltas_text}", deltas_text)
        prompt = prompt.replace("{finance_news}", news_text or "（暂无财经类热点）")
        prompt = prompt.replace("{language}", self.language)

        if self.debug:
            print("\n" + "=" * 80)
            print("[Economic] User Prompt")
            print("=" * 80)
            print(prompt)
            print("=" * 80)

        try:
            messages: List[Dict[str, str]] = []
            if self.system_prompt:
                messages.append({"role": "system", "content": self.system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = self.client.chat(messages)
            parsed = self._parse_response(response)

            # JSON 解析失败时重试一次
            if parsed is None:
                print("[Economic] JSON 解析失败，尝试让 AI 修复...")
                fix_response = self._retry_fix_json(response)
                if fix_response:
                    parsed = self._parse_response(fix_response)

            if parsed is None:
                result.error = "AI 返回的 JSON 无法解析"
                result.raw_response = response
                return result

            self._populate(result, parsed)
            result.raw_response = response
            result.success = True
            return result

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)[:200]
            result.error = f"经济分析失败 ({error_type}): {error_msg}"
            return result

    # ---- 内部方法 ----------------------------------------------------------
    def _format_finance_news(self, finance_news: List[Dict[str, Any]]) -> Tuple[str, int]:
        """把命中财经/股市/房产等关键词的热榜条目格式化为简洁文本。"""
        if not finance_news:
            return "", 0
        lines: List[str] = []
        count = 0
        for stat in finance_news:
            word = stat.get("word", "")
            titles = stat.get("titles", [])
            if not word or not titles:
                continue
            lines.append(f"\n**{word}**")
            for t in titles:
                if not isinstance(t, dict):
                    continue
                title = t.get("title", "")
                if not title:
                    continue
                source = t.get("source_name", t.get("source", ""))
                prefix = f"[{source}] " if source else ""
                lines.append(f"- {prefix}{title}")
                count += 1
                if count >= self.max_news:
                    break
            if count >= self.max_news:
                break
        return "\n".join(lines), count

    def _retry_fix_json(self, original: str) -> Optional[str]:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 JSON 修复助手。下面是格式有误的 JSON，请只输出修复后的纯 JSON，"
                    "不要 markdown 代码块或说明文字。"
                ),
            },
            {"role": "user", "content": original},
        ]
        try:
            return self.client.chat(messages)
        except Exception as e:
            print(f"[Economic] JSON 修复失败: {type(e).__name__}: {e}")
            return None

    def _parse_response(self, response: str) -> Optional[Dict[str, Any]]:
        if not response or not response.strip():
            return None
        text = response.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1]
            if "```" in text:
                text = text.split("```", 1)[0]
        elif "```" in text:
            parts = text.split("```", 2)
            if len(parts) >= 2:
                text = parts[1]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            try:
                from json_repair import repair_json
                repaired = repair_json(text, return_objects=True)
                if isinstance(repaired, dict):
                    return repaired
            except Exception:
                return None
        return None

    def _populate(self, result: EconomicAnalysisResult, data: Dict[str, Any]) -> None:
        result.global_trends = str(data.get("global_trends", "")).strip()
        result.china_trends = str(data.get("china_trends", "")).strip()

        risks = data.get("key_risks", [])
        if isinstance(risks, list):
            result.key_risks = [str(r).strip() for r in risks if str(r).strip()]
        elif isinstance(risks, str):
            result.key_risks = [risks.strip()] if risks.strip() else []

        rationale = data.get("allocation_rationale", {})
        if isinstance(rationale, dict):
            result.allocation_rationale = {
                str(k): str(v).strip() for k, v in rationale.items() if k in PROFILES
            }

        result.disclaimer = str(data.get("disclaimer", "")).strip()
        if not result.disclaimer:
            result.disclaimer = "本配置基于公开新闻与行情快照由 AI 推演生成，非投资建议，盈亏自负。"

        # 配置百分比 —— 验证 + 归一化
        allocations_raw = data.get("allocations", {})
        if not isinstance(allocations_raw, dict):
            result.validation_warnings.append("allocations 字段不是 dict，已置空")
            return

        for profile in PROFILES:
            raw = allocations_raw.get(profile)
            if not isinstance(raw, dict):
                result.validation_warnings.append(f"档位 {profile} 缺失或不是 dict")
                continue
            cleaned, warns = self._validate_allocation(profile, raw)
            result.allocations[profile] = cleaned
            result.validation_warnings.extend(warns)

    def _validate_allocation(
        self, profile: str, raw: Dict[str, Any]
    ) -> Tuple[Dict[str, int], List[str]]:
        """
        校验单档配置：白名单过滤 + 整数化 + 总和归一化到 100。

        Returns:
            (cleaned dict, warnings list)
        """
        warnings: List[str] = []
        cleaned: Dict[str, int] = {asset: 0 for asset in ASSET_WHITELIST}

        # 收集合法资产
        for asset, weight in raw.items():
            if asset not in cleaned:
                warnings.append(f"[{profile}] 未知资产 '{asset}' 已被丢弃")
                continue
            try:
                w = int(round(float(weight)))
            except (ValueError, TypeError):
                warnings.append(f"[{profile}] {asset} 权重无效: {weight!r}")
                continue
            if w < 0:
                warnings.append(f"[{profile}] {asset} 权重为负 ({w})，置 0")
                w = 0
            cleaned[asset] = w

        total = sum(cleaned.values())
        if total == 100:
            return cleaned, warnings

        if total == 0:
            warnings.append(f"[{profile}] 所有权重为 0，无法归一化")
            return cleaned, warnings

        diff = abs(total - 100)
        if diff <= NORMALIZE_TOLERANCE:
            # 容差内：把差额加到/扣除最大单笔权重上
            largest = max(cleaned, key=lambda k: cleaned[k])
            cleaned[largest] += (100 - total)
            warnings.append(f"[{profile}] 总和 {total}，已自动调整 {largest} 至 100")
        else:
            # 超出容差：按比例归一化
            scale = 100.0 / total
            for k in cleaned:
                cleaned[k] = int(round(cleaned[k] * scale))
            # 处理 round 误差
            new_total = sum(cleaned.values())
            if new_total != 100:
                largest = max(cleaned, key=lambda k: cleaned[k])
                cleaned[largest] += (100 - new_total)
            warnings.append(
                f"[{profile}] 原始总和 {total}（偏差 {diff} > {NORMALIZE_TOLERANCE}），"
                f"已按比例归一化到 100"
            )

        return cleaned, warnings
