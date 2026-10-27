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
