# coding=utf-8
"""一次性测试脚本：单独加载 economic_data，绕过 trendradar 包的导入链"""
import importlib.util
import sys


def load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ed = load("economic_data", "trendradar/ai/economic_data.py")

print("Sources detected (akshare/yfinance auto-skip if missing):")
fetcher = ed.EconomicDataFetcher(use_proxy=False, debug=False)
snap = fetcher.fetch_snapshot()

print()
print("=" * 60)
print(ed.snapshot_to_prompt_text(snap))
print("=" * 60)
print(f"\nTotal errors: {len(snap.fetch_errors)}")
print(f"Sources used: {snap.sources_used}")
