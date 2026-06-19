# coding=utf-8
"""
经济数据快照持久化

将 EconomicSnapshot 保存到 output/economic_snapshots/YYYY-MM-DD.json，
加载历史快照计算多周期变化（1d / 7d / 30d），自动清理过期文件。
"""

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from trendradar.ai.economic_data import EconomicSnapshot

_DEFAULT_DIR = Path(__file__).parent.parent.parent / "output" / "economic_snapshots"


class SnapshotStore:
    """读写经济数据快照。文件名 YYYY-MM-DD.json，每天一个；同日多次写入会覆盖。"""

    def __init__(self, base_dir: Optional[Path] = None, retention_days: int = 30):
        self.base_dir = Path(base_dir) if base_dir else _DEFAULT_DIR
        self.retention_days = retention_days
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, snap: EconomicSnapshot, when: Optional[datetime] = None) -> Path:
        when = when or datetime.now()
        path = self.base_dir / f"{when.strftime('%Y-%m-%d')}.json"
        path.write_text(
            json.dumps(asdict(snap), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def load(self, day: datetime) -> Optional[Dict[str, Any]]:
        path = self.base_dir / f"{day.strftime('%Y-%m-%d')}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def load_recent(self, days: int = 30) -> List[Tuple[datetime, Dict[str, Any]]]:
        """返回 [(day, snapshot_dict), ...]，按时间升序。缺失的日期跳过。"""
        out: List[Tuple[datetime, Dict[str, Any]]] = []
        today = datetime.now().date()
        for offset in range(days, -1, -1):
            day = datetime.combine(today - timedelta(days=offset), datetime.min.time())
            data = self.load(day)
            if data:
                out.append((day, data))
        return out

    def cleanup(self) -> int:
        """删除 retention_days 之前的快照文件。返回删除数量。"""
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        removed = 0
        for f in self.base_dir.glob("*.json"):
            try:
                day = datetime.strptime(f.stem, "%Y-%m-%d")
            except ValueError:
                continue
            if day < cutoff:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed


def compute_trend_deltas(history: List[Tuple[datetime, Dict[str, Any]]]) -> Dict[str, Dict[str, float]]:
    """
    计算 1d / 7d / 30d 价格变化百分比。

    输入: SnapshotStore.load_recent() 的结果
    输出: {"沪深300": {"d1": 0.5, "d7": -2.1, "d30": 3.4}, ...}
          仅当历史数据中能找到对应基准点时才返回该周期。
    """
    if not history:
        return {}

    # 取最新快照作为基准
    latest_day, latest = history[-1]
    targets = ("a_stock", "a_stock_industry", "hk_stock", "us_stock", "commodities", "fx")

    # 先把历史快照按日期 → {资产: price} 索引
    by_day: Dict[datetime, Dict[str, float]] = {}
    for day, snap in history:
        prices: Dict[str, float] = {}
        for section in targets:
            for name, d in (snap.get(section) or {}).items():
                p = d.get("price")
                if p is not None:
                    prices[name] = float(p)
        by_day[day] = prices

    latest_prices = by_day.get(latest_day, {})
    if not latest_prices:
        return {}

    def find_baseline(asset: str, days_back: int) -> Optional[float]:
        target_day = latest_day - timedelta(days=days_back)
        # 容差 ±2 天匹配最近的非空价格
        candidates = sorted(by_day.keys(), key=lambda d: abs((d - target_day).days))
        for d in candidates:
            if abs((d - target_day).days) > 2:
                break
            price = by_day[d].get(asset)
            if price:
                return price
        return None

    deltas: Dict[str, Dict[str, float]] = {}
    for asset, latest_price in latest_prices.items():
        entry: Dict[str, float] = {}
        for label, days_back in (("d1", 1), ("d7", 7), ("d30", 30)):
            base = find_baseline(asset, days_back)
            if base:
                entry[label] = round((latest_price - base) / base * 100, 2)
        if entry:
            deltas[asset] = entry
    return deltas


def deltas_to_prompt_text(deltas: Dict[str, Dict[str, float]]) -> str:
    if not deltas:
        return "（暂无历史快照，无法计算多周期变化）"
    lines = ["格式: 资产 | 1日 | 7日 | 30日（百分比）"]
    for asset, d in deltas.items():
        d1 = f"{d.get('d1', 'N/A')}%" if "d1" in d else "—"
        d7 = f"{d.get('d7', 'N/A')}%" if "d7" in d else "—"
        d30 = f"{d.get('d30', 'N/A')}%" if "d30" in d else "—"
        lines.append(f"- {asset} | {d1} | {d7} | {d30}")
    return "\n".join(lines)
