# coding=utf-8
"""
经济分析结果持久化

将 EconomicAnalysisResult 保存到 output/economic_analysis/YYYY-MM-DD.json，
用于实现"每天首次生成、当日复用缓存"的策略，避免在 current/incremental 模式下
每次推送都重复调用 LLM。
"""

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from trendradar.ai.economic_analyzer import EconomicAnalysisResult

_DEFAULT_DIR = Path(__file__).parent.parent.parent / "output" / "economic_analysis"


class AnalysisStore:
    """读写每日经济分析结果。文件名 YYYY-MM-DD.json，每天一个；同日多次写入会覆盖。"""

    def __init__(self, base_dir: Optional[Path] = None, retention_days: int = 30):
        self.base_dir = Path(base_dir) if base_dir else _DEFAULT_DIR
        self.retention_days = retention_days
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, result: EconomicAnalysisResult, when: Optional[datetime] = None) -> Path:
        when = when or datetime.now()
        path = self.base_dir / f"{when.strftime('%Y-%m-%d')}.json"
        path.write_text(
            json.dumps(asdict(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    def load(self, day: datetime) -> Optional[EconomicAnalysisResult]:
        path = self.base_dir / f"{day.strftime('%Y-%m-%d')}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return EconomicAnalysisResult(**data)
        except (json.JSONDecodeError, OSError, TypeError):
            return None

    def cleanup(self) -> int:
        """删除 retention_days 之前的分析结果文件。返回删除数量。"""
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
