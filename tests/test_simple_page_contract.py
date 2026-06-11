import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class SimplePageContractTests(unittest.TestCase):
    def setUp(self):
        self.server_source = (REPO_ROOT / "ui_app" / "server.py").read_text(encoding="utf-8")

    def test_simple_page_keeps_new_text_first_flow(self):
        source = self.server_source

        self.assertIn('@app.get("/simple"', source)
        self.assertIn('@app.post("/api/simple/submit"', source)
        self.assertIn("新增粘贴框", source)
        self.assertIn("下载模版", source)
        self.assertIn("保存草稿", source)
        self.assertIn("清空草稿", source)
        self.assertIn("copyTaskLogs", source)

    def test_simple_page_supports_images_and_store_file(self):
        source = self.server_source

        self.assertIn("images_${idx}", source)
        self.assertIn("store_${idx}", source)
        self.assertIn("step2_store_file_path", source)


if __name__ == "__main__":
    unittest.main()
