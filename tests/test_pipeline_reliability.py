"""Offline regression tests for degraded crawler runs (no API or notifications)."""

import io
import json
import math
import os
import tempfile
import sqlite3
import time
import unittest

import yaml
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch

with patch.dict(os.environ, {"LITELLM_LOCAL_MODEL_COST_MAP": "True"}):
    from trendradar.ai.client import AIClient
    from trendradar.ai.economic_analyzer import EconomicAnalyzer, PROFILES
    from trendradar.ai.economic_analysis_store import AnalysisStore
    from trendradar.ai.economic_data import EconomicDataFetcher, EconomicSnapshot
    from trendradar.ai.translator import AITranslator

from scripts.restore_crawler_state import restore_state
from trendradar.core.frequency import load_frequency_words, matches_word_groups
from trendradar.utils.diagnostics import safe_error, warning


class EconomicValidationTests(unittest.TestCase):
    def setUp(self):
        self.analyzer = EconomicAnalyzer.__new__(EconomicAnalyzer)
        self.analyzer.client = Mock(api_key="test-key")
        self.analyzer.get_time_func = lambda: datetime(2026, 11, 24, 12)
        self.analyzer.system_prompt = "test"
        self.analyzer.user_prompt_template = "{snapshot_text}"
        self.analyzer.language = "Chinese"
        self.analyzer.max_news = 5
        self.analyzer.debug = False
        self.snapshot = EconomicSnapshot(sources_used=["test"], a_stock={"沪深300": {"price": 100}})

    def payload(self, weight=100):
        return {"global_trends": "Global", "china_trends": "China",
                "allocations": {p: {"沪深300": weight} for p in PROFILES}}

    def analyze_payload(self, payload):
        self.analyzer.client.chat.return_value = json.dumps(payload)
        return self.analyzer.analyze(self.snapshot)

    def test_zero_profiles_is_not_success(self):
        result = self.analyze_payload({"global_trends": "Text only"})
        self.assertFalse(result.success)
        self.assertTrue(result.error)
        self.assertEqual(result.snapshot_data["a_stock"], self.snapshot.a_stock)

    def test_missing_profile_is_not_success(self):
        payload = self.payload()
        del payload["allocations"]["balanced"]
        self.assertFalse(self.analyze_payload(payload).success)

    def test_invalid_weights_are_not_success(self):
        for weight in (0, -1, "bad", math.inf, math.nan, True, 50):
            with self.subTest(weight=weight):
                self.assertFalse(self.analyze_payload(self.payload(weight)).success)

    def test_valid_profiles_and_small_rounding_error(self):
        for weight in (100, 99, 101):
            with self.subTest(weight=weight):
                result = self.analyze_payload(self.payload(weight))
                self.assertTrue(result.success, result.error)
                self.assertEqual(set(result.allocations), set(PROFILES))
                self.assertTrue(all(sum(a.values()) == 100 for a in result.allocations.values()))

    def test_semantic_repair_is_bounded_and_can_succeed(self):
        self.analyzer.client.chat.side_effect = ["{}", json.dumps(self.payload())]
        result = self.analyzer.analyze(self.snapshot)
        self.assertTrue(result.success, result.error)
        self.assertEqual(self.analyzer.client.chat.call_count, 2)

    def test_unrepairable_response_uses_only_two_calls(self):
        self.analyzer.client.chat.return_value = "{}"
        self.assertFalse(self.analyzer.analyze(self.snapshot).success)
        self.assertEqual(self.analyzer.client.chat.call_count, 2)

    def test_unknown_asset_rejected(self):
        payload = self.payload()
        payload["allocations"]["balanced"] = {"not-an-asset": 100}
        self.assertFalse(self.analyze_payload(payload).success)

    def test_valid_result_roundtrips_through_cache(self):
        result = self.analyze_payload(self.payload())
        with tempfile.TemporaryDirectory() as directory:
            store = AnalysisStore(Path(directory))
            store.save(result, self.analyzer.get_time_func())
            self.assertTrue(store.load(self.analyzer.get_time_func()).has_valid_allocations())

    def test_non_object_response_rejected(self):
        self.assertIsNone(self.analyzer._parse_response("[]"))

    def test_legacy_invalid_success_cache_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            day = self.analyzer.get_time_func()
            path = Path(directory) / "2026-11-24.json"
            path.write_text(json.dumps({"success": True, "allocations": {}}))
            self.assertIsNone(AnalysisStore(Path(directory)).load(day))


class TranslationReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.translator = AITranslator.__new__(AITranslator)
        self.translator.enabled = True
        self.translator.target_language = "中文"
        self.translator.system_prompt = "test"
        self.translator.user_prompt_template = "{content}"
        self.translator.client = Mock(api_key="test-key")

    def test_missing_number_is_failure_and_preserves_alignment(self):
        self.translator.client.chat.return_value = "[1] 第一条\n[3] 第三条"
        result = self.translator.translate_batch(["first", "second", "third"])
        self.assertEqual((result.success_count, result.fail_count), (2, 1))
        self.assertFalse(result.results[1].success)
        self.assertEqual(result.results[1].translated_text, "second")
        self.assertEqual(result.results[2].translated_text, "第三条")

    def test_empty_single_response_is_failure(self):
        self.translator.client.chat.return_value = " "
        self.assertFalse(self.translator.translate("original").success)

    def test_exception_does_not_expose_key(self):
        self.translator.client.chat.side_effect = RuntimeError("secret-test-key endpoint credentials")
        result = self.translator.translate_batch(["one", "two"])
        self.assertEqual(result.fail_count, 2)
        self.assertNotIn("secret-test-key", result.results[0].error)
        self.assertIn("RuntimeError", result.results[0].error)

    def test_duplicate_titles_are_requested_once_and_reused(self):
        self.translator.client.chat.return_value = "[1] 一"
        first = self.translator.translate_batch(["one", "one"])
        second = self.translator.translate_batch(["one"])
        self.assertEqual(self.translator.client.chat.call_count, 1)
        self.assertEqual(first.success_count, 2)
        self.assertEqual(second.results[0].translated_text, "一")

    def test_failed_translations_are_not_cached(self):
        self.translator.client.chat.side_effect = [RuntimeError("failure"), "[1] 一"]
        self.assertFalse(self.translator.translate_batch(["one"]).results[0].success)
        self.assertTrue(self.translator.translate_batch(["one"]).results[0].success)
        self.assertEqual(self.translator.client.chat.call_count, 2)

    def test_duplicate_response_number_is_ambiguous(self):
        self.translator.client.chat.return_value = "[1] 一\n[1] 二"
        result = self.translator.translate_batch(["one"])
        self.assertFalse(result.results[0].success)
        self.assertEqual(result.results[0].translated_text, "one")

    def test_partial_unnumbered_response_is_not_shifted(self):
        self.translator.client.chat.return_value = "only one line"
        result = self.translator.translate_batch(["one", "two"])
        self.assertEqual(result.fail_count, 2)

    def test_out_of_order_response_is_aligned(self):
        self.translator.client.chat.return_value = "[2] 二\n[1] 一"
        result = self.translator.translate_batch(["one", "two"])
        self.assertEqual([r.translated_text for r in result.results], ["一", "二"])


class ModelValidationTests(unittest.TestCase):
    def test_invisible_model_character_rejected_before_request(self):
        client = AIClient({"MODEL": "openai/\u200btest", "API_KEY": "test-key"})
        self.assertFalse(client.validate_config()[0])
        with patch("trendradar.ai.client.completion") as completion:
            with self.assertRaises(ValueError):
                client.chat([])
            completion.assert_not_called()

    def test_normal_model_is_valid(self):
        self.assertTrue(AIClient({"MODEL": "openai/test", "API_KEY": "test-key"}).validate_config()[0])


class StateRestorationTests(unittest.TestCase):
    def test_restores_recent_state_but_not_html_old_future_or_links(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            target = Path(directory) / "target"
            for folder in ("news", "economic_analysis", "html"):
                (source / folder).mkdir(parents=True)
            connection = sqlite3.connect(source / "news/2026-11-24.db")
            connection.execute("CREATE TABLE headlines (title TEXT)")
            connection.execute("INSERT INTO headlines VALUES ('already seen')")
            connection.commit()
            connection.close()
            (source / "news/2025-01-01.db").write_text("old")
            (source / "news/2026-11-25.db").write_text("future")
            (source / "news/2026-11-23.db").symlink_to(source / "news/2026-11-24.db")
            (source / "economic_analysis/2026-11-24.json").write_text("{}")
            (source / "html/latest.html").write_text("stale report")
            count = restore_state(source, target, date(2026, 11, 24))
            self.assertEqual(count, 2)
            self.assertFalse((target / "html").exists())
            self.assertEqual(len(list((target / "news").iterdir())), 1)
            connection = sqlite3.connect(target / "news/2026-11-24.db")
            self.assertEqual(connection.execute("SELECT title FROM headlines").fetchone()[0], "already seen")
            connection.close()
            self.assertEqual(restore_state(source, target, date(2026, 11, 24)), 2)

    def test_missing_state_is_safe_cold_start(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(restore_state(Path(directory) / "missing", Path(directory) / "target", date.today()), 0)


class EconomicFetchBudgetTests(unittest.TestCase):
    def test_exhausted_budget_never_starts_network_call(self):
        fetcher = EconomicDataFetcher(total_timeout=1)
        fetcher._deadline = time.monotonic() - 1
        snapshot = EconomicSnapshot()
        call = Mock()
        self.assertIsNone(fetcher._run_with_timeout("test", call, snapshot))
        call.assert_not_called()
        self.assertEqual(len(snapshot.fetch_errors), 1)

    def test_sources_used_requires_actual_data(self):
        fetcher = EconomicDataFetcher()
        with patch.object(fetcher, "_fetch_tencent_quotes"), patch.object(fetcher, "_try_import", return_value=None):
            snapshot = fetcher.fetch_snapshot()
        self.assertEqual(snapshot.sources_used, [])
        self.assertTrue(snapshot.fetch_errors)


class FocusedNewsProfileTests(unittest.TestCase):
    def test_active_profile_is_updated_and_retains_existing_interests(self):
        groups, filters, global_filters = load_frequency_words("config/frequency_words.txt")
        self.assertEqual(groups[0]["display_name"], "上海房产")
        for title in (
            "上海二手房网签成交量变化", "万科债务重组进展",
            "美联储降息与黄金价格走势", "华为发布鸿蒙新版本",
            "比亚迪发布刀片电池", "美国宣布新关税政策",
        ):
            with self.subTest(title=title):
                self.assertTrue(matches_word_groups(title, groups, filters, global_filters))
        for title in ("美国演员获得奖项", "浦东马拉松开跑", "法国电影节开幕"):
            with self.subTest(title=title):
                self.assertFalse(matches_word_groups(title, groups, filters, global_filters))



class CrawlerWorkflowTests(unittest.TestCase):
    def test_state_failure_does_not_block_crawler_or_publish_invalid_checkout(self):
        workflow = yaml.safe_load(Path(".github/workflows/crawler.yml").read_text())
        steps = {step["name"]: step for step in workflow["jobs"]["crawl"]["steps"]}
        self.assertTrue(steps["Checkout reports state"]["continue-on-error"])
        self.assertTrue(steps["Restore crawler state"]["continue-on-error"])
        self.assertIn("steps.reports_checkout.outcome == 'success'", steps["Restore crawler state"]["if"])
        self.assertIn("steps.reports_checkout.outcome == 'success'", steps["Push output/ to reports repo"]["if"])
        self.assertNotIn("reports_checkout", steps["Run crawler"]["if"])
        self.assertIn("outcome == 'failure'", steps["Warn if state restoration failed"]["if"])
        self.assertEqual(workflow["permissions"]["actions"], "read")
        self.assertEqual(workflow["permissions"]["contents"], "write")


class DiagnosticsTests(unittest.TestCase):
    def test_status_is_logged_without_provider_message(self):
        error = RuntimeError("secret-key")
        error.status_code = 429
        self.assertEqual(safe_error(error), "RuntimeError (HTTP 429)")

    def test_warning_is_escaped_and_written_to_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.md"
            with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "GITHUB_STEP_SUMMARY": str(path)}), redirect_stdout(io.StringIO()) as output:
                warning("partial\n50%")
            self.assertIn("::warning::partial%0A50%25", output.getvalue())
            self.assertIn("DEGRADED", path.read_text())


if __name__ == "__main__":
    unittest.main()
