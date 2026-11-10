from datetime import datetime
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "test.sqlite3"
        self.legacy_file = Path(self.temp_dir.name) / "legacy.json"
        self.legacy_file.write_text("{}", encoding="utf-8")
        self.legacy_patch = patch("store.LEGACY_FILE", self.legacy_file)
        self.legacy_patch.start()
        self.store = Store(self.database)

    def tearDown(self):
        self.legacy_patch.stop()
        self.temp_dir.cleanup()

    def test_password_authentication_and_case_insensitive_usernames(self):
        teacher_id = self.store.create_user("teacher", "secret-password", "teacher")
        self.assertGreater(teacher_id, 0)
        self.assertEqual(self.store.authenticate("TEACHER", "secret-password")["role"], "teacher")
        self.assertIsNone(self.store.authenticate("teacher", "wrong"))
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.create_user("Teacher", "another-password", "teacher")

    def test_tasks_are_private_and_public_information_is_shared(self):
        class_id = self.store.create_class("1年A組")
        first_id = self.store.create_student("student-a", "password-a", class_id)
        second_id = self.store.create_student("student-b", "password-b", class_id)
        self.store.add_item("tasks", {"text": "first task", "done": False}, first_id)
        self.store.add_item("tasks", {"text": "second task", "done": False}, second_id)
        self.store.add_item("timetable", {"day": "月", "time": "09:00", "subject": "数学"})

        self.assertEqual([task["text"] for task in self.store.list_items("tasks", first_id)],
                         ["first task"])
        self.assertEqual([task["text"] for task in self.store.list_items("tasks", second_id)],
                         ["second task"])
        self.assertEqual(len(self.store.list_items("timetable")), 1)

    def test_assignment_submission_status_is_tracked_per_student(self):
        class_id = self.store.create_class("1年A組")
        first_id = self.store.create_student("student-a", "password-a", class_id)
        second_id = self.store.create_student("student-b", "password-b", class_id)
        assignment_id = self.store.add_item("assignments", {
            "subject": "数学",
            "due": "2026-11-20",
            "destination": "数学科教員室",
        })

        self.assertFalse(self.store.assignment_submitted(assignment_id, first_id))
        self.store.set_assignment_submitted(assignment_id, first_id, True)

        self.assertTrue(self.store.assignment_submitted(assignment_id, first_id))
        self.assertFalse(self.store.assignment_submitted(assignment_id, second_id))
        statuses = self.store.list_assignment_submission_statuses(assignment_id)
        self.assertEqual(
            [(status["username"], bool(status["submitted"])) for status in statuses],
            [("student-a", True), ("student-b", False)],
        )

        self.store.delete_item("assignments", assignment_id)
        with self.store._connect() as connection:
            remaining = connection.execute(
                "SELECT COUNT(*) FROM assignment_submissions"
            ).fetchone()[0]
        self.assertEqual(remaining, 0)

    def test_weekday_timetable_can_be_updated_by_day_and_period(self):
        lesson = {"day": "月", "period": "1", "time": "09:00-10:30",
                  "subject": "数学", "teacher": "山田先生"}
        item_id = self.store.add_item("timetable", lesson)
        lesson["subject"] = "英語"
        lesson["teacher"] = "佐藤先生"
        self.store.update_item("timetable", item_id, lesson)

        saved = self.store.list_items("timetable")
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["subject"], "英語")
        self.assertEqual(saved[0]["teacher"], "佐藤先生")

    def test_automatic_timetable_delivery_schedule_and_per_day_snapshots(self):
        for day in ("月", "火", "水", "金"):
            self.store.add_item("timetable", {
                "day": day, "period": "1", "time": "09:00-10:00",
                "subject": f"{day}曜の授業", "teacher": "先生",
            })

        self.assertEqual(
            self.store.publish_due_timetables(datetime(2026, 11, 11, 14, 59)), []
        )
        self.assertEqual(
            self.store.publish_due_timetables(datetime(2026, 11, 11, 15, 0)), ["火"]
        )
        self.assertEqual(
            self.store.publish_due_timetables(datetime(2026, 11, 11, 15, 1)), []
        )
        self.assertEqual(
            self.store.published_timetable_for_day("火")["lessons"][0]["subject"],
            "火曜の授業",
        )
        self.assertEqual(
            self.store.published_timetable_for_day("月")["lessons"], []
        )

        self.assertEqual(
            self.store.publish_due_timetables(datetime(2026, 11, 12, 15, 0)),
            ["水", "金"],
        )
        self.assertEqual(
            self.store.publish_due_timetables(datetime(2026, 11, 13, 15, 0)), ["月"]
        )
        self.assertEqual(
            self.store.published_timetable_for_day("水")["lessons"][0]["subject"],
            "水曜の授業",
        )
        self.assertEqual(
            self.store.published_timetable_for_day("金")["lessons"][0]["subject"],
            "金曜の授業",
        )
        self.assertEqual(
            self.store.published_timetable_for_day("月")["lessons"][0]["subject"],
            "月曜の授業",
        )

    def test_manual_timetable_publish_still_publishes_all_weekdays(self):
        for day in ("月", "火"):
            self.store.add_item("timetable", {
                "day": day, "period": "1", "time": "09:00-10:00",
                "subject": f"{day}曜の授業", "teacher": "先生",
            })

        self.store.publish_timetable("2026-11-09 12:00:00")

        self.assertTrue(self.store.published_timetable_for_day("月")["published_at"])
        self.assertTrue(self.store.published_timetable_for_day("火")["published_at"])

    def test_reminder_content_and_schedule_can_be_updated(self):
        item_id = self.store.add_item("reminders", {
            "title": "提出物を確認",
            "when": "2026-11-10 07:00",
        })

        self.store.update_item("reminders", item_id, {
            "title": "数学の課題を提出",
            "when": "2026-11-09 18:30",
        })

        reminder = self.store.list_items("reminders")[0]
        self.assertEqual(reminder["title"], "数学の課題を提出")
        self.assertEqual(reminder["when"], "2026-11-09 18:30")

    def test_test_schedule_and_range_are_saved(self):
        item_id = self.store.add_item("tests", {
            "subject": "数学",
            "date": "2026-11-10",
            "time": "09:00",
            "detail": "教科書 p.10-30",
        })

        test = self.store.list_items("tests")[0]
        self.assertEqual(test["subject"], "数学")
        self.assertEqual(test["date"], "2026-11-10")
        self.assertEqual(test["time"], "09:00")
        self.assertEqual(test["detail"], "教科書 p.10-30")
        self.assertFalse(test["published"])

        self.assertTrue(self.store.set_test_published(item_id, True))
        self.store.update_item("tests", item_id, {
            "subject": "数学",
            "date": "2026-11-10",
            "time": "09:00",
            "detail": "教科書 p.10-35",
        })
        self.assertTrue(self.store.list_items("tests")[0]["published"])

    def test_existing_tests_without_publication_flag_remain_visible_to_students(self):
        with self.store._connect() as connection:
            connection.execute(
                "INSERT INTO items (collection, owner_id, payload) VALUES ('tests', NULL, ?)",
                ('{"subject":"既存のテスト","date":"2026-11-10","time":"09:00","detail":"範囲"}',),
            )

        reopened_store = Store(self.database)

        self.assertTrue(reopened_store.list_items("tests")[0]["published"])

    def test_publish_all_tests_publishes_only_unpublished_items(self):
        first_id = self.store.add_item("tests", {"subject": "数学"})
        second_id = self.store.add_item("tests", {"subject": "英語"})
        self.store.set_test_published(first_id, True)

        self.assertEqual(self.store.publish_all_tests(), 1)
        self.assertEqual(self.store.publish_all_tests(), 0)
        self.assertTrue(all(item["published"] for item in self.store.list_items("tests")))

    def test_test_subject_lists_are_persisted_per_grade(self):
        self.assertEqual(
            self.store.list_test_subjects("1年生"),
            ["数学", "英語", "言語文化", "現代国", "地基", "歴史", "人間学", "家庭科"],
        )
        self.assertEqual(self.store.list_test_subjects("2年生"), [])

        self.assertTrue(self.store.add_test_subject("2年生", "化学"))
        self.assertFalse(self.store.add_test_subject("2年生", "化学"))

        reopened_store = Store(self.database)
        self.assertEqual(reopened_store.list_test_subjects("2年生"), ["化学"])
        self.assertEqual(reopened_store.list_test_subjects("3年生"), [])

    def test_date_override_replaces_weekly_schedule_and_upserts_periods(self):
        self.store.add_item("timetable", {
            "day": "月", "period": "1", "time": "09:00-10:30",
            "subject": "通常授業", "teacher": "通常の先生",
        })
        self.store.save_timetable_exception("2026-10-26", "schedule", "短縮授業")
        self.store.save_timetable_exception("2026-10-26", "schedule", "短縮授業", {
            "period": "1", "time": "09:00-09:35", "subject": "数学", "teacher": "山田先生",
        })
        self.store.save_timetable_exception("2026-10-26", "schedule", "短縮授業", {
            "period": "2", "time": "09:40-10:15", "subject": "英語", "teacher": "佐藤先生",
        })
        self.store.save_timetable_exception("2026-10-26", "schedule", "短縮授業", {
            "period": "1", "time": "09:00-09:30", "subject": "国語", "teacher": "鈴木先生",
        })

        exceptions = self.store.list_timetable_exceptions()
        self.assertEqual(len(exceptions), 1)
        self.assertEqual([lesson["period"] for lesson in exceptions[0]["lessons"]], ["1", "2"])
        self.assertEqual(exceptions[0]["lessons"][0]["subject"], "国語")
        self.assertEqual(exceptions[0]["lessons"][0]["teacher"], "鈴木先生")

        self.store.save_timetable_exception("2026-10-26", "holiday", "文化祭")
        holiday = self.store.list_timetable_exceptions()[0]
        self.assertEqual(holiday["kind"], "holiday")
        self.assertEqual(holiday["title"], "文化祭")
        self.assertEqual(holiday["lessons"], [])
        self.store.delete_timetable_exception("2026-10-26")
        self.assertEqual(self.store.list_timetable_exceptions(), [])

    def test_timetable_exception_requires_iso_date_and_holiday_note(self):
        with self.assertRaises(ValueError):
            self.store.save_timetable_exception("2026/10/26", "schedule", "")
        with self.assertRaises(ValueError):
            self.store.save_timetable_exception("2026-10-26", "holiday", "")

    def test_chat_membership_is_limited_to_teacher_student_and_class(self):
        teacher_id = self.store.create_user("teacher", "password-1", "teacher")
        other_teacher_id = self.store.create_user("other-teacher", "password-2", "teacher")
        first_class = self.store.create_class("1年A組")
        second_class = self.store.create_class("1年B組")
        first_student_id = self.store.create_student("student-a", "password-a", first_class)
        second_student_id = self.store.create_student("student-b", "password-b", second_class)
        teacher = self.store.authenticate("teacher", "password-1")
        student = self.store.authenticate("student-a", "password-a")
        stranger = self.store.authenticate("student-b", "password-b")
        direct_chat = self.store.direct_conversation_id(teacher_id, first_student_id)

        self.assertTrue(self.store.can_access_conversation(teacher, direct_chat))
        self.assertTrue(self.store.can_access_conversation(student, direct_chat))
        self.assertFalse(self.store.can_access_conversation(stranger, direct_chat))
        self.assertFalse(self.store.can_access_conversation(
            teacher, self.store.direct_conversation_id(teacher_id, other_teacher_id)))
        self.assertTrue(self.store.can_access_conversation(student, f"class:{first_class}"))
        self.assertFalse(self.store.can_access_conversation(student, f"class:{second_class}"))

        self.store.send_message(student, direct_chat, "こんにちは")
        self.assertEqual(self.store.list_messages(direct_chat)[0]["body"], "こんにちは")
        with self.assertRaises(PermissionError):
            self.store.send_message(stranger, direct_chat, "見えないはず")


if __name__ == "__main__":
    unittest.main()
