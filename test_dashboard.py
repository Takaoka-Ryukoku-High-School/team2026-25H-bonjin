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

    def test_students_only_see_teacher_published_tests(self):
        teacher_page = FakePage()
        dashboard.main(teacher_page)
        picker_controls = teacher_page.controls[0].content.controls
        picker_controls[3].controls[0].on_click(None)
        tabs = teacher_page.controls[0].content.controls[2]
        teacher_test_view = tabs.content.controls[1].controls[3]
        test_panel = teacher_test_view.controls[0]
        test_rows = test_panel.content.controls[4]
        self.assertEqual(
            [
                row.content.controls[0].value
                for row in test_rows.controls
            ],
            ["数学", "英語", "言語文化", "現代国", "地基", "歴史", "人間学", "家庭科"],
        )
        new_row = test_rows.controls[0]
        subject, date, time, detail = new_row.content.controls[:4]
        subject.value = "理科"
        date.value = "2026-11-12"
        time.value = "09:00"
        detail.value = "教科書 p.20-30"
        publish_button = new_row.content.controls[4].controls[0]
        publish_button.on_click(None)

        test = self.store.list_items("tests")[-1]
        self.assertEqual(test["subject"], "理科")
        self.assertEqual(test["date"], "2026-11-12")
        self.assertEqual(test["time"], "09:00")
        self.assertEqual(test["detail"], "教科書 p.20-30")
        self.assertTrue(self.store.list_items("tests")[-1]["published"])

        student_page = FakePage()
        dashboard.main(student_page)
        picker_controls = student_page.controls[0].content.controls
        picker_controls[3].controls[1].on_click(None)
        tabs = student_page.controls[0].content.controls[2]
        student_test_view = tabs.content.controls[1].controls[4]
        student_panel = student_test_view.controls[0]
        refresh_button = student_panel.content.controls[2]
        refresh_button.on_click(None)
        student_panel = student_page.controls[0].content.controls[2].content.controls[1].controls[4].controls[0]
        cards = student_panel.content.controls[3].controls
        test_card = cards[0]
        self.assertEqual(test_card.content.controls[0].value, "理科")
        self.assertEqual(test_card.content.controls[1].value, "試験日時: 2026-11-12 09:00")
        self.assertEqual(test_card.content.controls[4].value, "教科書 p.20-30")

        teacher_page = FakePage()
        dashboard.main(teacher_page)
        picker_controls = teacher_page.controls[0].content.controls
        picker_controls[3].controls[0].on_click(None)
        tabs = teacher_page.controls[0].content.controls[2]
        teacher_test_view = tabs.content.controls[1].controls[3]
        test_panel = teacher_test_view.controls[0]
        row = test_panel.content.controls[4].controls[0]
        subject, date, time, detail = row.content.controls[:4]
        subject.value = "理科"
        date.value = "2026-11-13"
        time.value = "10:00"
        detail.value = "教科書 p.31-40"
        publish_button = row.content.controls[4].controls[1]
        publish_button.on_click(None)

        updated_test = self.store.list_items("tests")[-1]
        self.assertEqual(updated_test["subject"], "理科")
        self.assertEqual(updated_test["date"], "2026-11-13")
        self.assertEqual(updated_test["time"], "10:00")
        self.assertEqual(updated_test["detail"], "教科書 p.31-40")
        self.assertTrue(updated_test["published"])

        student_panel = student_page.controls[0].content.controls[2].content.controls[1].controls[4].controls[0]
        student_panel.content.controls[2].on_click(None)
        student_panel = student_page.controls[0].content.controls[2].content.controls[1].controls[4].controls[0]
        cards = student_panel.content.controls[3].controls
        test_card = cards[0]
        self.assertEqual(test_card.content.controls[0].value, "理科")
        self.assertEqual(test_card.content.controls[1].value, "試験日時: 2026-11-13 10:00")
        self.assertEqual(test_card.content.controls[3].value, "試験範囲")
        self.assertEqual(test_card.content.controls[4].value, "教科書 p.31-40")

    def test_teacher_can_add_subjects_for_other_grades(self):
        page = FakePage()
        dashboard.main(page)
        picker_controls = page.controls[0].content.controls
        picker_controls[3].controls[0].on_click(None)
        tabs = page.controls[0].content.controls[2]
        test_view = tabs.content.controls[1].controls[3]
        test_panel = test_view.controls[0]
        grade_dropdown = test_panel.content.controls[2].controls[0]
        grade_dropdown.value = "2年生"
        grade_dropdown.on_select(None)

        tabs = page.controls[0].content.controls[2]
        test_view = tabs.content.controls[1].controls[3]
        test_panel = test_view.controls[0]
        subject_row = test_panel.content.controls[2]
        subject_row.controls[1].value = "化学"
        subject_row.controls[2].on_click(None)

        self.assertEqual(self.store.list_test_subjects("2年生"), ["化学"])
        tabs = page.controls[0].content.controls[2]
        test_view = tabs.content.controls[1].controls[3]
        test_rows = test_view.controls[0].content.controls[4]
        card_fields = test_rows.controls[0].content.controls
        self.assertEqual(card_fields[0].value, "化学")
        self.assertEqual(
            [field.label for field in card_fields[:4]],
            ["科目", "試験日", "時刻", "範囲"],
        )


if __name__ == "__main__":
    unittest.main()
