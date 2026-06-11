import csv
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    import ui_app.server as server
except ModuleNotFoundError as exc:
    server = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


@unittest.skipIf(server is None, f"UI dependencies unavailable: {IMPORT_ERROR}")
class SimpleTargetFieldTests(unittest.TestCase):
    def test_prepare_simple_target_fields_generates_product_file_and_coupon_ids(self):
        with tempfile.TemporaryDirectory() as td:
            csv_path = Path(td) / "plan.csv"
            headers = [
                "name",
                "purchase_target_product_code",
                "coupon_ids_sheet_ref",
                "coupon_ids",
                "step2_product_file_path",
            ]
            with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerow(
                    {
                        "name": "测试",
                        "purchase_target_product_code": "1001、1002",
                        "coupon_ids_sheet_ref": "1-2001、1-2002",
                    }
                )

            server.prepare_simple_target_fields(csv_path, "unit-simple")

            with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                row = next(csv.DictReader(f))
            self.assertEqual(row["coupon_ids"], "1-2001/1-2002")
            self.assertTrue(row["step2_product_file_path"])
            self.assertTrue(Path(row["step2_product_file_path"]).exists())

    def test_unified_mapping_keeps_separate_combo_channel_content(self):
        with tempfile.TemporaryDirectory() as td:
            csv_path = Path(td) / "plan.csv"
            headers = [
                "name",
                "channels",
                "theme",
                "push_content",
                "sms_content",
                "send_content",
                "start_time",
                "end_time",
                "send_time",
                "create_url",
            ]
            with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerow(
                    {
                        "name": "组合渠道",
                        "channels": "短信、会员通-发客户消息",
                        "theme": "其他、新店营销",
                        "push_content": "兜底内容",
                        "sms_content": "短信专用内容",
                        "send_content": "会员通专用内容",
                        "start_time": "2026-06-01",
                        "end_time": "2026-06-10",
                        "send_time": "2026-06-02 09:00",
                    }
                )

            server.apply_unified_field_mapping_and_refs(csv_path, "unit-simple", "", {})

            with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                row = next(csv.DictReader(f))
            self.assertEqual(row["sms_content"], "短信专用内容")
            self.assertEqual(row["send_content"], "会员通专用内容")
            self.assertIn("600035736992907264", row["create_url"])

    def test_unified_mapping_supports_smart_phone_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            csv_path = Path(td) / "plan.csv"
            headers = [
                "name",
                "channels",
                "theme",
                "push_content",
                "activity_intro",
                "region",
                "start_time",
                "end_time",
                "send_time",
                "create_url",
            ]
            with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerow(
                    {
                        "name": "智能电话",
                        "channels": "智能电话",
                        "theme": "其他、新店营销",
                        "push_content": "电话活动介绍",
                        "start_time": "2026-06-01 09:00:00",
                        "end_time": "2026-06-08 23:00:00",
                        "send_time": "2026-06-02 10:00:00",
                    }
                )

            server.apply_unified_field_mapping_and_refs(csv_path, "unit-simple", "", {})

            with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                row = next(csv.DictReader(f))
            self.assertEqual(row["region"], "营运区")
            self.assertEqual(row["activity_intro"], "电话活动介绍")
            self.assertIn("620450416034897920", row["create_url"])

    def test_unified_mapping_rejects_smart_phone_combo(self):
        with tempfile.TemporaryDirectory() as td:
            csv_path = Path(td) / "plan.csv"
            headers = ["name", "channels", "theme", "activity_intro", "start_time", "end_time", "send_time"]
            with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerow(
                    {
                        "name": "智能电话组合",
                        "channels": "智能电话、短信",
                        "theme": "其他",
                        "activity_intro": "测试",
                        "start_time": "2026-06-01",
                        "end_time": "2026-06-08",
                        "send_time": "2026-06-02 10:00",
                    }
                )

            with self.assertRaises(Exception) as ctx:
                server.apply_unified_field_mapping_and_refs(csv_path, "unit-simple", "", {})

            self.assertIn("智能电话当前仅支持单渠道", str(ctx.exception))

    def test_success_task_has_no_error_summary(self):
        task = SimpleNamespace(status="success", logs=[], error="")

        self.assertEqual(server._extract_error_summary(task), "")

    def test_task_parser_prefers_real_review_link(self):
        runner = server.TaskRunner(workers=1)
        task = server.Task(
            id="unit",
            filename="unit.csv",
            file_path="/tmp/unit.csv",
            options=server.TaskOptions(),
        )

        runner._parse_generated_links(
            task,
            "创建链接: https://precision.dslyy.com/admin#/marketingTemplate/use?useId=1",
        )
        runner._parse_generated_links(
            task,
            "复核链接: https://precision.dslyy.com/admin#/marketingPlan/editPlan?activityId=600000000000000001",
        )
        runner._parse_generated_links(
            task,
            "上下文页检测到已跳转URL: https://precision.dslyy.com/admin#/marketingPlan/editPlan?activityId=old",
        )
        runner._parse_generated_links(
            task,
            "上下文页URL: ['https://precision.dslyy.com/admin#/marketingPlan/editPlan?activityId=older']",
        )

        self.assertEqual(
            task._latest_link_for_ui(),
            "https://precision.dslyy.com/admin#/marketingPlan/editPlan?activityId=600000000000000001",
        )

    def test_task_parser_extracts_field_results(self):
        runner = server.TaskRunner(workers=1)
        task = server.Task(
            id="unit",
            filename="unit.csv",
            file_path="/tmp/unit.csv",
            options=server.TaskOptions(),
        )

        runner._parse_progress(task, "      ✅ 第2步-商品编码")
        runner._parse_progress(task, "      ⚪ 第2步-主消费营运区")
        runner._parse_progress(task, "      ❌ 第3步-执行员工")

        self.assertEqual(
            task.field_results,
            [
                {"name": "第2步-商品编码", "status": "ok"},
                {"name": "第2步-主消费营运区", "status": "warn"},
                {"name": "第3步-执行员工", "status": "fail"},
            ],
        )
        self.assertEqual(task.to_dict()["field_result_counts"], {"ok": 1, "warn": 1, "fail": 1, "total": 3})

    def test_error_summary_prefers_runtime_error_line(self):
        task = server.Task(
            id="unit",
            filename="unit.csv",
            file_path="/tmp/unit.csv",
            options=server.TaskOptions(),
        )
        task.status = "failed"
        task.error = "exit_code=1"
        task.logs = [
            "   ❌ 计划 1 失败 (尝试 1/2)",
            "      错误: 第1步失败：营销主题未选择成功",
        ]

        self.assertEqual(
            server._extract_error_summary(task),
            "错误: 第1步失败：营销主题未选择成功",
        )
        self.assertEqual(
            task.to_dict()["error_summary"],
            "错误: 第1步失败：营销主题未选择成功",
        )

    def test_build_review_payload_for_extension(self):
        payload = server._build_review_payload(
            {
                "name": "复核计划",
                "channels": "短信、会员通-发客户消息",
                "theme": "其他、新店营销",
                "start_time": "2026-06-01 00:00:00",
                "end_time": "2026-06-10 23:59:59",
                "send_time": "2026-06-02 09:00:00",
                "sms_content": "短信内容",
                "send_content": "客户消息内容",
            },
            source_text="计划名称: 复核计划",
            image_count=2,
        )

        fields = {item["name"]: item["value"] for item in payload["expected_fields"]}
        self.assertEqual(payload["source"], "simple")
        self.assertEqual(fields["计划名称"], "复核计划")
        self.assertEqual(fields["发送渠道"], "短信、会员通-发客户消息")
        self.assertEqual(fields["图片数量"], "2")

    def test_build_review_payload_includes_activity_intro(self):
        payload = server._build_review_payload(
            {
                "name": "智能电话",
                "channels": "智能电话",
                "activity_intro": "电话介绍内容",
            },
            source_text="计划名称: 智能电话",
        )

        fields = {item["name"]: item["value"] for item in payload["expected_fields"]}
        self.assertEqual(fields["活动介绍"], "电话介绍内容")

    def test_extract_ark_output_text_responses_shape(self):
        text = server._extract_ark_output_text(
            {
                "output": [
                    {
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"fields":[{"name":"计划名称","page_value":"A"}]}',
                            }
                        ]
                    }
                ]
            }
        )

        self.assertIn('"fields"', text)

    def test_parse_json_object_from_text_with_wrapped_json(self):
        parsed = server._parse_json_object_from_text(
            '结果如下：{"fields":[{"name":"计划名称","status":"match"}]}'
        )

        self.assertEqual(parsed["fields"][0]["name"], "计划名称")

    def test_simple_page_accumulates_images_per_row(self):
        html = server.SIMPLE_HTML

        self.assertIn("let rowImages = new Map();", html)
        self.assertIn("let rowStoreFiles = new Map();", html)
        self.assertIn("function appendRowImages(row, files)", html)
        self.assertIn("current.concat(added)", html)
        self.assertIn("function clearRowImages(id)", html)
        self.assertIn("function clearRowStoreFile(id)", html)
        self.assertIn("function setRowStoreFile(row, file)", html)
        self.assertIn("rowImages.get(String(row.dataset.rowId", html)
        self.assertIn("fd.append(`images_${idx}`, file)", html)
        self.assertIn("fd.append(`store_${idx}`, storeFile)", html)
        self.assertIn('class="store-input" type="file" accept=".xlsx,.xls"', html)
        self.assertIn("用于第2步“主消费门店”", html)
        self.assertIn("客户消息/朋友圈会自动复用到第3步上传门店", html)
        self.assertIn("社群和智能电话不自动复用", html)

    def test_simple_page_shows_plan_count_and_splits_pasted_blocks(self):
        html = server.SIMPLE_HTML

        self.assertIn('id="planCount"', html)
        self.assertIn("countEl.textContent = `${count} 个文本计划`", html)
        self.assertIn('id="addCount" type="number" min="1" max="100" value="1"', html)
        self.assertIn('onclick="addRowsFromCount()">新增粘贴框</button>', html)
        self.assertNotIn("批量新增", html)
        self.assertIn('class="toolbar-card"', html)
        self.assertIn('class="toolbar-row"', html)
        self.assertIn('class="toolbar-group"', html)
        self.assertIn('<summary>高级设置</summary>', html)
        self.assertIn('id="holdSeconds" type="number" min="0" value="5"', html)
        self.assertIn("document.getElementById('holdSeconds').value || '5'", html)
        self.assertIn("function handlePlanTextPaste(row, event)", html)
        self.assertIn("split(/^\\s*--+\\s*$/m)", html)
        self.assertIn("blocks.slice(1).forEach(block => addRow(block))", html)

    def test_simple_page_supports_text_draft_and_download(self):
        html = server.SIMPLE_HTML

        self.assertIn("const DRAFT_KEY = 'pm_simple_text_draft_v1';", html)
        self.assertIn("const DRAFT_DB = 'pm_simple_draft_db_v1';", html)
        self.assertIn('onclick="saveDraft()"', html)
        self.assertNotIn('onclick="restoreDraft()"', html)
        self.assertIn('onclick="clearDraft()"', html)
        self.assertNotIn('onclick="downloadPlanTexts()"', html)
        self.assertNotIn('id="txtFiles"', html)
        self.assertNotIn("document.getElementById('txtFiles')", html)
        self.assertIn("function openDraftDb()", html)
        self.assertIn("async function fileToDraft(file)", html)
        self.assertIn("function draftToFile(item)", html)
        self.assertIn("async function autoRestoreDraft()", html)
        self.assertIn("autoRestoreDraft();", html)
        self.assertIn("replaceRowsWithDraftRows([{text:'', images:[], storeFile:null}])", html)
        self.assertIn("localStorage.setItem(DRAFT_KEY", html)
        self.assertIn("storeFile: storeFile ? await fileToDraft(storeFile) : null", html)
        self.assertIn("storeFile: row.storeFile ? draftToFile(row.storeFile) : null", html)

    def test_simple_submit_accepts_step2_store_file_per_row(self):
        source = Path(server.__file__).read_text(encoding="utf-8")

        self.assertIn('store_upload = form.get(f"store_{idx}")', source)
        self.assertIn("save_uploaded_main_store_file(", source)
        self.assertIn("inject_step2_main_store_file_to_csv(dst, store_path)", source)
        self.assertIn("sync_step2_store_file_to_step3_for_customer_message_moments(dst, store_path)", source)

    def test_sync_step2_store_file_to_step3_only_customer_message_and_moments(self):
        with tempfile.TemporaryDirectory() as td:
            csv_path = Path(td) / "plans.csv"
            headers = ["name", "channels", "upload_stores", "store_file_path"]
            rows = [
                {"name": "客户消息", "channels": "会员通-发客户消息"},
                {"name": "朋友圈", "channels": "会员通-发客户朋友圈"},
                {"name": "社群", "channels": "会员通-发送社群"},
                {"name": "智能电话", "channels": "智能电话"},
            ]
            with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows)

            server.sync_step2_store_file_to_step3_for_customer_message_moments(csv_path, "/tmp/store.xlsx")

            with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
                got = {row["name"]: row for row in csv.DictReader(f)}
            self.assertEqual(got["客户消息"]["upload_stores"], "是")
            self.assertEqual(got["客户消息"]["store_file_path"], "/tmp/store.xlsx")
            self.assertEqual(got["朋友圈"]["upload_stores"], "是")
            self.assertEqual(got["朋友圈"]["store_file_path"], "/tmp/store.xlsx")
            self.assertEqual(got["社群"]["upload_stores"], "")
            self.assertEqual(got["智能电话"]["store_file_path"], "")

    def test_simple_page_supports_retry_and_summary(self):
        html = server.SIMPLE_HTML

        self.assertIn('id="executionSummary"', html)
        self.assertIn("执行结果：成功 ${success} 个、失败 ${failed} 个、执行中 ${running} 个", html)
        self.assertIn('onclick="retryAllFailedRows()"', html)
        self.assertIn('onclick="retryFailedRow(${id})"', html)
        self.assertIn('onclick="copyTaskLogs(${id})"', html)
        self.assertIn("async function copyTaskLogs(rowId)", html)
        self.assertIn("/api/tasks/${taskId}/logs?offset=0&limit=5000", html)
        self.assertIn("async function submitRows(rows)", html)
        self.assertIn("async function retryFailedRow(rowId)", html)
        self.assertIn("async function retryAllFailedRows()", html)
        self.assertIn("['failed','generate_failed'].includes(row.dataset.status || '')", html)

    def test_simple_page_rolls_back_control_console_layout(self):
        html = server.SIMPLE_HTML

        self.assertNotIn("Batch Creation Console", html)
        self.assertNotIn("class=\"page-head\"", html)
        self.assertNotIn("class=\"action-bar\"", html)
        self.assertNotIn("backdrop-filter:saturate(180%) blur(14px)", html)
        self.assertIn("--bg:#f7f8fa", html)
        self.assertIn("grid-template-columns:minmax(420px,1.2fr) minmax(320px,.8fr) 260px", html)
        self.assertIn('<button id="submitBtn" type="button" onclick="submitPlans()">开始执行</button>', html)

    def test_simple_page_exposes_template_and_field_list_downloads(self):
        html = server.SIMPLE_HTML
        route_paths = {getattr(route, "path", "") for route in server.app.routes}

        self.assertIn('<a class="button-link secondary" href="/api/simple/template" download>下载模版</a>', html)
        self.assertIn('<a class="button-link secondary" href="/api/simple/fields" download>字段清单</a>', html)
        self.assertIn("/api/simple/template", route_paths)
        self.assertIn("/api/simple/fields", route_paths)
        self.assertIn("活动介绍", server.SIMPLE_AUTOMATION_FIELDS_MD)
        self.assertIn("主消费门店文件", server.SIMPLE_AUTOMATION_FIELDS_MD)
        self.assertIn("社群任务分配方式", server.SIMPLE_AUTOMATION_FIELDS_MD)
        self.assertIn("## 基础信息", server.SIMPLE_TEXT_TEMPLATE_TXT)
        self.assertIn("发送渠道: 短信、会员通-发客户消息", server.SIMPLE_TEXT_TEMPLATE_TXT)
        self.assertIn("购买目标商品编码: 1010002、1012058", server.SIMPLE_TEXT_TEMPLATE_TXT)
        self.assertIn("活动介绍: |", server.SIMPLE_TEXT_TEMPLATE_TXT)
        self.assertIn("客户消息/朋友圈会自动复用到第3步上传门店", server.SIMPLE_TEXT_TEMPLATE_TXT)
        self.assertIn("社群和智能电话不自动复用", server.SIMPLE_TEXT_TEMPLATE_TXT)
        self.assertNotIn("```", server.SIMPLE_TEXT_TEMPLATE_TXT)
        self.assertNotIn("/Users/liminrong/precision-marketing-auto/ui_uploads", server.SIMPLE_TEXT_TEMPLATE_TXT)

    def test_review_extension_has_only_two_primary_action_buttons_and_no_token(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / "browser_extension/review_assistant/sidepanel.html").read_text(encoding="utf-8")
        js = (root / "browser_extension/review_assistant/sidepanel.js").read_text(encoding="utf-8")

        self.assertIn('id="textReviewBtn"', html)
        self.assertIn('id="screenshotReviewBtn"', html)
        for old_id in ["serviceTokenInput", "saveSettingsBtn", "loadBtn", "reviewBtn", "visionBtn", "autoReview"]:
            self.assertNotIn(old_id, html)
            self.assertNotIn(old_id, js)
        self.assertNotIn("X-Review-Token", js)
        self.assertNotIn("reviewApiToken", js)
        self.assertIn("els.textReviewBtn.addEventListener", js)
        self.assertIn("els.screenshotReviewBtn.addEventListener", js)

    def test_runtime_info_exposes_version_paths_and_pid(self):
        route_paths = {getattr(route, "path", "") for route in server.app.routes}

        self.assertIn("/api/runtime", route_paths)
        self.assertTrue(server.APP_VERSION)
        self.assertTrue(str(server.ROOT))
        self.assertTrue(str(server.DATA_DIR))

    def test_business_pages_display_runtime_version(self):
        self.assertIn('id="runtimeVersion"', server.UI_HTML)
        self.assertIn('id="runtimeVersion"', server.SIMPLE_HTML)
        self.assertIn("async function loadRuntimeVersion()", server.UI_HTML)
        self.assertIn("async function loadRuntimeVersion()", server.SIMPLE_HTML)
        self.assertIn("fetch('/api/runtime', {cache:'no-store'})", server.UI_HTML)
        self.assertIn("fetch('/api/runtime', {cache:'no-store'})", server.SIMPLE_HTML)
        self.assertIn("loadRuntimeVersion();", server.UI_HTML)
        self.assertIn("loadRuntimeVersion();", server.SIMPLE_HTML)

    def test_release_launchers_detect_stale_running_ui(self):
        root = Path(__file__).resolve().parents[1]
        mac_launcher = (root / "scripts/deploy/start.command").read_text(encoding="utf-8")
        win_launcher = (root / "scripts/deploy/start.bat").read_text(encoding="utf-8")

        self.assertIn("/api/runtime", mac_launcher)
        self.assertIn("check_existing_ui || true", mac_launcher)
        self.assertLess(mac_launcher.index("auto_update.sh"), mac_launcher.index("check_existing_ui || true"))
        self.assertIn("stop_existing_ui", mac_launcher)

        self.assertIn("/api/runtime", win_launcher)
        self.assertIn(":CHECK_EXISTING_UI", win_launcher)
        self.assertLess(win_launcher.index("auto_update.ps1"), win_launcher.index("call :CHECK_EXISTING_UI"))
        self.assertIn("Stop-Process", win_launcher)

    def test_windows_launcher_keeps_failure_visible_and_logs_outer_startup(self):
        root = Path(__file__).resolve().parents[1]
        win_launcher = (root / "scripts/deploy/start.bat").read_text(encoding="utf-8")

        self.assertIn("PM_AUTO_START_INNER", win_launcher)
        self.assertIn("launcher.log", win_launcher)
        self.assertIn("start.bat.pending", win_launcher)
        self.assertIn("apply_launcher_update.bat", win_launcher)
        self.assertIn("Please send this log to support", win_launcher)
        self.assertIn("pause", win_launcher)
        self.assertIn('if not exist "%APP_DIR%\\ui_app\\server.py"', win_launcher)
        self.assertIn("Please extract the zip first", win_launcher)

    def test_windows_launcher_avoids_unescaped_parentheses_in_echo_blocks(self):
        root = Path(__file__).resolve().parents[1]
        win_launcher = (root / "scripts/deploy/start.bat").read_text(encoding="utf-8")

        self.assertNotIn("Installing dependencies (", win_launcher)
        self.assertIn("Installing dependencies - first run may take a minute", win_launcher)

    def test_release_package_self_heals_outer_launchers(self):
        root = Path(__file__).resolve().parents[1]
        build_script = (root / "scripts/deploy/build_release.py").read_text(encoding="utf-8")
        mac_updater = (root / "scripts/deploy/auto_update.sh").read_text(encoding="utf-8")
        win_updater = (root / "scripts/deploy/auto_update.ps1").read_text(encoding="utf-8")

        self.assertIn('"start.bat"', build_script)
        self.assertIn('"start.command"', build_script)
        server_source = Path(server.__file__).read_text(encoding="utf-8")
        self.assertIn("def _refresh_parent_launchers()", server_source)
        self.assertIn('"start.bat.pending" if name == "start.bat" else name', server_source)
        self.assertIn('cp "$NEW_ROOT/start.command" "$BASE_DIR/start.command"', mac_updater)
        self.assertIn('Copy-Item $newStartBat (Join-Path $BaseDir "start.bat.pending") -Force', win_updater)
        self.assertNotIn('Copy-Item $newStartBat (Join-Path $BaseDir "start.bat") -Force', win_updater)

    def test_uploaded_png_images_are_normalized_to_jpeg(self):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGBA", (2, 2), (255, 0, 0, 128)).save(buf, format="PNG")
        png_bytes = buf.getvalue()
        with tempfile.TemporaryDirectory() as td, patch.object(server, "UPLOAD_DIR", Path(td)):
            paths = server.save_uploaded_moments_images("unit", [("01_dashenlin-reference.png", png_bytes)])

            self.assertEqual(len(paths), 1)
            saved = Path(paths[0])
            self.assertEqual(saved.suffix.lower(), ".jpg")
            self.assertTrue(saved.read_bytes().startswith(b"\xff\xd8"))

    def test_invalid_image_bytes_are_rejected_before_upload(self):
        with tempfile.TemporaryDirectory() as td, patch.object(server, "UPLOAD_DIR", Path(td)):
            with self.assertRaises(Exception) as ctx:
                server.save_uploaded_moments_images("unit", [("fake.png", b"not a real image")])

        self.assertIn("不是有效的 jpg/png 图片", str(ctx.exception))

    def test_launchers_reinstall_dependencies_per_app_version(self):
        root = Path(__file__).resolve().parents[1]
        mac_launcher = (root / "scripts/deploy/start.command").read_text(encoding="utf-8")
        win_launcher = (root / "scripts/deploy/start.bat").read_text(encoding="utf-8")

        self.assertIn(".deps_ready_${APP_VERSION:-unknown}", mac_launcher)
        self.assertIn(".deps_ready_%APP_VERSION%", win_launcher)

    def test_windows_release_wheelhouse_includes_colorama(self):
        root = Path(__file__).resolve().parents[1]
        build_script = (root / "scripts/deploy/build_release.py").read_text(encoding="utf-8")

        self.assertIn('RUNTIME_VERSION = f"win-python-{WIN_PYTHON_VERSION}-wheelhouse-v2"', build_script)
        self.assertIn('"colorama"', build_script)


if __name__ == "__main__":
    unittest.main()
