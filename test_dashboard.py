from datetime import date, timedelta
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
        refresh_button = student_panel.content.controls[3]
        refresh_button.on_click(None)
        student_panel = student_page.controls[0].content.controls[2].content.controls[1].controls[4].controls[0]
        cards = student_panel.content.controls[4].controls
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
        student_panel.content.controls[3].on_click(None)
        student_panel = student_page.controls[0].content.controls[2].content.controls[1].controls[4].controls[0]
        cards = student_panel.content.controls[4].controls
        test_card = cards[0]
        self.assertEqual(test_card.content.controls[0].value, "理科")
        self.assertEqual(test_card.content.controls[1].value, "試験日時: 2026-11-13 10:00")
        self.assertEqual(test_card.content.controls[3].value, "試験範囲")
        self.assertEqual(test_card.content.controls[4].value, "教科書 p.31-40")

    def test_student_can_select_test_grade(self):
        self.store.add_item("tests", {
            "grade": "1年生", "subject": "数学", "date": "2026-11-12",
            "time": "09:00", "detail": "一次関数", "published": True,
        })
        self.store.add_item("tests", {
            "grade": "2年生", "subject": "化学", "date": "2026-11-13",
            "time": "10:00", "detail": "酸化還元", "published": True,
        })
        self.store.add_item("tests", {
            "grade": "2年生", "subject": "物理", "date": "2026-11-14",
            "time": "11:00", "detail": "力学", "published": False,
        })

        page = FakePage()
        dashboard.main(page)
        picker_controls = page.controls[0].content.controls
        picker_controls[3].controls[1].on_click(None)

        student_panel = page.controls[0].content.controls[2].content.controls[1].controls[4].controls[0]
        grade_dropdown = student_panel.content.controls[2]
        self.assertEqual(grade_dropdown.value, "1年生")
        self.assertEqual(
            [option.key for option in grade_dropdown.options],
            ["1年生", "2年生", "3年生"],
        )
        self.assertEqual(
            student_panel.content.controls[4].controls[0].content.controls[0].value,
            "数学",
        )

        grade_dropdown.value = "2年生"
        grade_dropdown.on_select(None)

        student_panel = page.controls[0].content.controls[2].content.controls[1].controls[4].controls[0]
        self.assertEqual(student_panel.content.controls[2].value, "2年生")
        cards = student_panel.content.controls[4].controls
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].content.controls[0].value, "化学")

    def test_student_dashboard_starts_automatic_test_refresh(self):
        page = FakePage()
        dashboard.main(page)
        picker_controls = page.controls[0].content.controls
        picker_controls[3].controls[1].on_click(None)

        self.assertTrue(getattr(page, "_student_auto_refresh_active", False))

    def test_assignment_management_tracks_status_and_shows_due_notice(self):
        student_user = self.store.get_development_user("student")
        due_date = (date.today() + timedelta(days=1)).isoformat()

        teacher_page = FakePage()
        dashboard.main(teacher_page)
        picker_controls = teacher_page.controls[0].content.controls
        picker_controls[3].controls[0].on_click(None)
        assignment_view = teacher_page.controls[0].content.controls[2].content.controls[1].controls[4]
        assignment_panel = assignment_view.controls[0]
        assignment_form = assignment_panel.content.controls[2]
        fields = assignment_form.content.controls
        fields[0].value = "数学"
        fields[1].value = "教科書 p.20-30 の問題を解く"
        fields[2].value = due_date
        fields[3].value = "数学科教員室"
        fields[4].on_click(None)
        assignment_id = self.store.list_items("assignments")[0]["id"]
        self.assertEqual(
            self.store.list_items("assignments")[0]["content"],
            "教科書 p.20-30 の問題を解く",
        )

        assignment_view = teacher_page.controls[0].content.controls[2].content.controls[1].controls[4]
        assignment_panel = assignment_view.controls[0]
        assignment_card = assignment_panel.content.controls[3].controls[0]
        self.assertEqual(
            assignment_card.content.controls[2].value,
            "提出内容: 教科書 p.20-30 の問題を解く",
        )
        submission_rows = assignment_card.content.controls[4].controls
        student_row = next(
            row for row in submission_rows
            if student_user["username"] in row.controls[0].value
        )
        status_dropdown = student_row.controls[1]
        status_dropdown.value = "submitted"
        status_dropdown.on_select(SimpleNamespace(control=status_dropdown))

        self.assertTrue(self.store.assignment_submitted(
            assignment_id, student_user["id"]
        ))

        student_page = FakePage()
        dashboard.main(student_page)
        picker_controls = student_page.controls[0].content.controls
        picker_controls[3].controls[1].on_click(None)
        assignment_view = student_page.controls[0].content.controls[2].content.controls[1].controls[5]
        assignment_card = assignment_view.controls[0].content.controls[2].controls[0]
        self.assertEqual(
            assignment_card.content.controls[2].value,
            "提出内容: 教科書 p.20-30 の問題を解く",
        )
        self.assertEqual(assignment_card.content.controls[3].value, "提出状況: 提出済み")
        self.assertEqual(len(assignment_view.controls[0].content.controls[2].controls), 1)
        self.assertEqual(
            len(student_page.controls[0].content.controls[1].controls), 2
        )

        self.store.set_assignment_submitted(
            assignment_id, student_user["id"], False
        )
        dashboard.main(student_page)
        picker_controls = student_page.controls[0].content.controls
        picker_controls[3].controls[1].on_click(None)
        heading = student_page.controls[0].content.controls[1]
        notice = heading.controls[2]
        self.assertEqual(notice.content.controls[0].value, "未提出の課題があります")
        self.assertIn("明日が提出日です", notice.content.controls[1].value)

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
