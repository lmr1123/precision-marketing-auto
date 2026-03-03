import csv
import tempfile
import unittest
from pathlib import Path
import importlib.util
import sys
import types


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "precision-auto-playwright-batch.py"


def load_module():
    # 仅用于单元测试：避免因未安装 playwright 导致模块无法加载。
    fake_playwright = types.ModuleType("playwright")
    fake_async_api = types.ModuleType("playwright.async_api")

    async def _unreachable_async_playwright():
        raise RuntimeError("async_playwright should not be used in unit tests")

    fake_async_api.async_playwright = _unreachable_async_playwright
    fake_async_api.TimeoutError = TimeoutError
    fake_playwright.async_api = fake_async_api
    sys.modules.setdefault("playwright", fake_playwright)
    sys.modules.setdefault("playwright.async_api", fake_async_api)

    spec = importlib.util.spec_from_file_location("precision_batch", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BatchScriptTests(unittest.TestCase):
    def setUp(self):
        self.module = load_module()

    def test_escape_js_string(self):
        raw = "会员\\测试'文案\n下一行"
        escaped = self.module.escape_js_string(raw)
        self.assertEqual(escaped, "会员\\\\测试\\'文案\\n下一行")

    def test_load_csv_includes_main_operating_area(self):
        headers = [
            "name", "region", "theme", "use_recommend", "start_time", "end_time",
            "trigger_type", "send_time", "global_limit", "set_target",
            "group_name", "update_type", "main_operating_area", "coupon_ids", "sms_content"
        ]
        row = [
            "测试计划", "省区", "其他", "否", "2026-03-01 08:00", "2026-03-01 08:00",
            "定时-单次任务", "2026-03-01 08:00", "不限制", "否",
            "测试分群", "自动更新", "广佛省区", "1-20000005475", "短信内容"
        ]

        with tempfile.NamedTemporaryFile("w", newline="", encoding="utf-8", suffix=".csv") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerow(row)
            f.flush()

            plans = self.module.load_plans_from_csv(f.name)

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0]["main_operating_area"], "广佛省区")

    def test_split_datetime(self):
        date_part, time_part = self.module.split_datetime("2026-03-02 08:00")
        self.assertEqual(date_part, "2026-03-02")
        self.assertEqual(time_part, "08:00:00")

    def test_values_include_datetime(self):
        values = ["2026-03-02 08:00:00", "其他字段"]
        self.assertTrue(self.module.values_include_datetime(values, "2026-03-02", "08:00:00"))
        self.assertFalse(self.module.values_include_datetime(values, "2026-03-03", "08:00:00"))

    def test_datetime_equals(self):
        self.assertTrue(self.module.datetime_equals("2026-03-06 08:30", "2026-03-06 08:30:00"))
        self.assertTrue(self.module.datetime_equals("2026-03-06 08:30:00", "2026-03-06 08:30"))
        self.assertFalse(self.module.datetime_equals("2026-03-06 08:30:00", "2026-03-02 08:00:00"))


if __name__ == "__main__":
    unittest.main()
