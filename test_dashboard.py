import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import dashboard
from store import Store


class FakePage:
    def __init__(self):
        self.width = 900
        self.controls = []

    def add(self, control):
        self.controls.append(control)

    def update(self):
        pass


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        legacy_path = Path(self.temp_dir.name) / "legacy.json"
        legacy_path.write_text("{}", encoding="utf-8")
        self.legacy_patch = patch("store.LEGACY_FILE", legacy_path)
        self.legacy_patch.start()
        self.store = Store(Path(self.temp_dir.name) / "dashboard.sqlite3")
        class_id = self.store.create_class("1年A組")
        self.store.create_user("teacher", "teacher-password", "teacher")
        self.store.create_student("student", "student-password", class_id)
        self.store_patch = patch("dashboard.Store", return_value=self.store)
        self.store_patch.start()

    def tearDown(self):
        self.store_patch.stop()
        self.legacy_patch.stop()
        self.temp_dir.cleanup()

    def test_development_mode_opens_role_specific_dashboard_without_login(self):
        expected_tabs = {
            "teacher": ("クラス管理", "自分のタスク"),
            "student": ("自分のタスク", "クラス管理"),
        }
        for username, (visible, hidden) in expected_tabs.items():
            with self.subTest(role=username):
                page = FakePage()
                dashboard.main(page)
                picker_controls = page.controls[0].content.controls
                role_button = picker_controls[3].controls[
                    0 if username == "teacher" else 1
                ]
                role_button.on_click(None)

                tabs = page.controls[0].content.controls[2]
                labels = [tab.label for tab in tabs.content.controls[0].tabs]
                self.assertIn(visible, labels)
                self.assertNotIn(hidden, labels)

    def test_login_mode_still_shows_login_form(self):
        page = FakePage()
        dashboard.main(page, require_login=True)
        controls = page.controls[0].content.controls
        self.assertEqual(controls[0].value, "ログイン")
        self.assertEqual(controls[1].label, "ユーザー名")


if __name__ == "__main__":
    unittest.main()
