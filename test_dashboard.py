import asyncio
from datetime import date, timedelta
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import dashboard
from store import Store


class FakePage:
    def __init__(self):
        self.width = 900
        self.controls = []
        self.services = []
        self.thread_callbacks = []

    def add(self, control):
        self.controls.append(control)

    def run_thread(self, callback):
        self.thread_callbacks.append(callback)

    def update(self):
        pass


def find_control_by_data(control, data):
    if getattr(control, "data", None) == data:
        return control
    content = getattr(control, "content", None)
    if content is not None:
        match = find_control_by_data(content, data)
        if match is not None:
            return match
    for child in getattr(control, "controls", []):
        match = find_control_by_data(child, data)
        if match is not None:
            return match
    return None


def iter_controls(control):
    yield control
    content = getattr(control, "content", None)
    if content is not None:
        yield from iter_controls(content)
    for child in getattr(control, "controls", []):
        yield from iter_controls(child)


def dashboard_view(page):
    active_view = find_control_by_data(page.controls[0], "dashboard-active-view")
    return active_view.content


def open_dashboard_view(page, label):
    nav_item = find_control_by_data(page.controls[0], f"dashboard-nav:{label}")
    nav_item.on_click(None)
    return dashboard_view(page)


def dashboard_navigation_labels(page):
    def labels(control):
        result = []
        data = getattr(control, "data", None)
        if isinstance(data, str) and data.startswith("dashboard-nav:"):
            result.append(data.removeprefix("dashboard-nav:"))
        content = getattr(control, "content", None)
        if content is not None:
            result.extend(labels(content))
        for child in getattr(control, "controls", []):
            result.extend(labels(child))
        return result

    return labels(page.controls[0])


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
        expected_navigation = {
            "teacher": ("クラス管理", "自分のタスク"),
            "student": ("自分のタスク", "クラス管理"),
        }
        for role, (visible, hidden) in expected_navigation.items():
            with self.subTest(role=role):
                page = FakePage()
                dashboard.main(page)
                picker_controls = page.controls[0].content.controls
                role_button = picker_controls[3].controls[
                    0 if role == "teacher" else 1
                ]
                role_button.on_click(None)

                labels = dashboard_navigation_labels(page)
                self.assertIn(visible, labels)
                self.assertNotIn(hidden, labels)

    def test_student_can_write_and_draw_a_private_note(self):
        page = FakePage()
        dashboard.main(page)
        picker_controls = page.controls[0].content.controls
        picker_controls[3].controls[1].on_click(None)
        task_view = open_dashboard_view(page, "自分のタスク")
        self.assertEqual(
            task_view.controls[0].controls[0].content.controls[0].value,
            "メモ",
        )
        self.assertEqual(len(task_view.controls[0].controls), 1)

        find_control_by_data(page.controls[0], "student-note-add").on_click(None)
        memo = find_control_by_data(page.controls[0], "student-note-text:new")
        canvas = find_control_by_data(page.controls[0], "student-note-canvas:new")
        self.assertIsNotNone(memo)
        self.assertIsNotNone(canvas)
        memo.value = "数学の復習メモ"

        drawing_stack = canvas.content
        with patch.object(drawing_stack, "update"):
            canvas.on_pan_start(SimpleNamespace(
                local_position=SimpleNamespace(x=20, y=30)
            ))
            canvas.on_pan_update(SimpleNamespace(
                local_position=SimpleNamespace(x=80, y=60)
            ))
            canvas.on_pan_end(None)

        find_control_by_data(
            page.controls[0], "student-note-save:new"
        ).on_click(None)

        student_id = self.store.get_development_user("student")["id"]
        notes = self.store.list_items("notes", student_id)
        self.assertEqual(notes[0]["text"], "数学の復習メモ")
        self.assertGreater(len(notes[0]["strokes"][0]), 1)
        self.assertEqual(
            self.store.list_items("notes", self.store.get_development_user("teacher")["id"]),
            [],
        )

        note_key = notes[0]["id"]
        saved_memo = find_control_by_data(
            page.controls[0], f"student-note-text:{note_key}"
        )
        self.assertEqual(saved_memo.value, "数学の復習メモ")
        saved_canvas = find_control_by_data(
            page.controls[0], f"student-note-canvas:{note_key}"
        )
        self.assertGreater(len(saved_canvas.content.controls), 1)

        updated_memo = find_control_by_data(
            page.controls[0], f"student-note-text:{note_key}"
        )
        updated_memo.value = "数学の復習メモ（更新）"
        find_control_by_data(
            page.controls[0], f"student-note-save:{note_key}"
        ).on_click(None)
        notes = self.store.list_items("notes", student_id)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["text"], "数学の復習メモ（更新）")

        find_control_by_data(page.controls[0], "student-note-add").on_click(None)
        new_memo = find_control_by_data(page.controls[0], "student-note-text:new")
        new_memo.value = "英語の単語"
        find_control_by_data(
            page.controls[0], "student-note-save:new"
        ).on_click(None)
        notes = self.store.list_items("notes", student_id)
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0]["text"], "英語の単語")

        first_note_key = notes[0]["id"]
        find_control_by_data(
            page.controls[0], f"student-note-delete:{first_note_key}"
        ).on_click(None)
        remaining_notes = self.store.list_items("notes", student_id)
        self.assertEqual(len(remaining_notes), 1)
        self.assertEqual(remaining_notes[0]["text"], "数学の復習メモ（更新）")

        find_control_by_data(page.controls[0], "student-note-add").on_click(None)
        find_control_by_data(
            page.controls[0], "student-note-delete:new"
        ).on_click(None)
        self.assertEqual(len(self.store.list_items("notes", student_id)), 1)
        self.assertIsNone(
            find_control_by_data(page.controls[0], "student-note-text:new")
        )

    def test_teacher_can_publish_a_date_specific_flyer_to_students(self):
        image_bytes = b"\x89PNG\r\n\x1a\nflyer"
        image_file = SimpleNamespace(
            name="event.png",
            size=len(image_bytes),
            bytes=image_bytes,
        )
        teacher_page = FakePage()
        dashboard.main(teacher_page)
        picker_controls = teacher_page.controls[0].content.controls
        picker_controls[3].controls[0].on_click(None)
        open_dashboard_view(teacher_page, "時間割")

        with patch.object(
            dashboard.ft.FilePicker,
            "pick_files",
            new=AsyncMock(return_value=[image_file]),
        ):
            asyncio.run(find_control_by_data(
                teacher_page.controls[0], "timetable-exception-image-picker"
            ).on_click(None))

        exception_date = find_control_by_data(
            teacher_page.controls[0], "timetable-exception-date"
        )
        exception_kind = find_control_by_data(
            teacher_page.controls[0], "timetable-exception-kind"
        )
        exception_title = find_control_by_data(
            teacher_page.controls[0], "timetable-exception-title"
        )
        exception_notice = find_control_by_data(
            teacher_page.controls[0], "timetable-exception-notice"
        )
        flyer_paper = find_control_by_data(
            teacher_page.controls[0], "timetable-exception-flyer-paper"
        )
        self.assertIsNotNone(flyer_paper)
        self.assertIsNotNone(find_control_by_data(
            flyer_paper, "timetable-exception-image-picker"
        ))
        exception_date.value = "2026-11-25"
        exception_kind.value = "holiday"
        exception_title.value = "文化祭"
        exception_notice.value = "集合場所は体育館です。"
        find_control_by_data(
            teacher_page.controls[0], "timetable-exception-save"
        ).on_click(None)

        saved_exception = self.store.list_timetable_exceptions()[0]
        self.assertEqual(saved_exception["notice"], "集合場所は体育館です。")
        self.assertEqual(saved_exception["attachments"][0]["name"], "event.png")

        student_page = FakePage()
        dashboard.main(student_page)
        picker_controls = student_page.controls[0].content.controls
        picker_controls[3].controls[1].on_click(None)
        open_dashboard_view(student_page, "時間割")
        flyer = find_control_by_data(
            student_page.controls[0], "timetable-exception-flyer:2026-11-25"
        )
        self.assertIsNotNone(flyer)
        flyer_controls = list(iter_controls(flyer))
        self.assertTrue(any(
            isinstance(control, dashboard.ft.Text)
            and control.value == "集合場所は体育館です。"
            for control in flyer_controls
        ))
        self.assertTrue(any(
            isinstance(control, dashboard.ft.Image)
            and control.src.startswith("data:image/png;base64,")
            for control in flyer_controls
        ))

    def test_login_mode_still_shows_login_form(self):
        page = FakePage()
        dashboard.main(page, require_login=True)
        controls = page.controls[0].content.controls
        self.assertEqual(controls[0].value, "ログイン")
        self.assertEqual(controls[1].label, "ユーザー名")

    def test_assignment_image_type_detection(self):
        supported_images = [
            (b"\x89PNG\r\n\x1a\n", "image/png"),
            (b"\xff\xd8\xff", "image/jpeg"),
            (b"GIF89a", "image/gif"),
            (b"RIFF\x00\x00\x00\x00WEBP", "image/webp"),
        ]
        for contents, expected_type in supported_images:
            with self.subTest(media_type=expected_type):
                self.assertEqual(dashboard.image_media_type(contents), expected_type)
        self.assertIsNone(dashboard.image_media_type(b"not an image"))

    def test_assignment_can_be_registered_with_image_only(self):
        image_bytes = b"\x89PNG\r\n\x1a\nimage"
        image_file = SimpleNamespace(
            name="worksheet.png",
            size=len(image_bytes),
            bytes=image_bytes,
        )
        teacher_page = FakePage()
        dashboard.main(teacher_page)
        picker_controls = teacher_page.controls[0].content.controls
        picker_controls[3].controls[0].on_click(None)
        assignment_panel = open_dashboard_view(teacher_page, "課題").controls[0]
        upload_button = find_control_by_data(
            teacher_page.controls[0], "assignment-image-picker"
        )
        with patch.object(
            dashboard.ft.FilePicker,
            "pick_files",
            new=AsyncMock(return_value=[image_file]),
        ):
            asyncio.run(upload_button.on_click(None))

        assignment_form = assignment_panel.content.controls[2]
        fields = assignment_form.content.controls
        fields[0].value = "数学"
        fields[2].value = "2026-11-20"
        fields[3].value = "教室"
        fields[4].on_click(None)

        assignment = self.store.list_items("assignments")[-1]
        self.assertEqual(assignment["content"], "")
        self.assertEqual(
            assignment["attachments"][0]["name"],
            "worksheet.png",
        )
        self.assertEqual(
            dashboard.base64.b64decode(assignment["attachments"][0]["data"]),
            image_bytes,
        )

        student_page = FakePage()
        dashboard.main(student_page)
        picker_controls = student_page.controls[0].content.controls
        picker_controls[3].controls[1].on_click(None)
        open_dashboard_view(student_page, "課題")
        images = [
            control
            for control in iter_controls(student_page.controls[0])
            if isinstance(control, dashboard.ft.Image)
        ]
        self.assertEqual(len(images), 1)
        self.assertTrue(images[0].src.startswith("data:image/png;base64,"))

    def test_assignment_can_target_a_grade_or_class(self):
        second_class = self.store.create_class("2年A組")
        self.store.create_student("student-b", "student-b-password", second_class)

        teacher_page = FakePage()
        dashboard.main(teacher_page)
        picker_controls = teacher_page.controls[0].content.controls
        picker_controls[3].controls[0].on_click(None)

        open_dashboard_view(teacher_page, "課題")
        target_scope = find_control_by_data(
            teacher_page.controls[0], "assignment-target-scope"
        )
        target_value = find_control_by_data(
            teacher_page.controls[0], "assignment-target-value"
        )
        assignment_panel = dashboard_view(teacher_page).controls[0]
        fields = assignment_panel.content.controls[2].content.controls
        fields[0].value = "数学"
        fields[1].value = "一次関数"
        fields[2].value = "2026-11-20"
        fields[3].value = "教室"
        target_scope.value = "grade"
        target_scope.on_select(SimpleNamespace(control=target_scope))
        target_value.value = "1年生"
        fields[4].on_click(None)

        grade_assignment = self.store.list_items("assignments")[-1]
        self.assertEqual(grade_assignment["target_type"], "grade")
        self.assertEqual(grade_assignment["target_grade"], "1年生")
        grade_statuses = self.store.list_assignment_submission_statuses(
            grade_assignment["id"]
        )
        self.assertEqual([status["username"] for status in grade_statuses], ["student"])

        open_dashboard_view(teacher_page, "課題")
        target_scope = find_control_by_data(
            teacher_page.controls[0], "assignment-target-scope"
        )
        target_value = find_control_by_data(
            teacher_page.controls[0], "assignment-target-value"
        )
        assignment_panel = dashboard_view(teacher_page).controls[0]
        fields = assignment_panel.content.controls[2].content.controls
        fields[0].value = "英語"
        fields[1].value = "英単語"
        fields[2].value = "2026-11-20"
        fields[3].value = "教室"
        target_scope.value = "class"
        target_scope.on_select(SimpleNamespace(control=target_scope))
        target_value.value = str(second_class)
        fields[4].on_click(None)

        class_assignment = self.store.list_items("assignments")[-1]
        self.assertEqual(class_assignment["target_type"], "class")
        self.assertEqual(
            class_assignment["target_class_id"],
            str(second_class),
        )
        class_statuses = self.store.list_assignment_submission_statuses(
            class_assignment["id"]
        )
        self.assertEqual([status["username"] for status in class_statuses], ["student-b"])

        student_page = FakePage()
        dashboard.main(student_page, require_login=True)
        login_controls = student_page.controls[0].content.controls
        login_controls[1].value = "student"
        login_controls[2].value = "student-password"
        login_controls[3].on_click(None)
        assignment_panel = open_dashboard_view(student_page, "課題").controls[0]
        cards = assignment_panel.content.controls[2].controls
        self.assertEqual(len(cards), 1)
        self.assertTrue(cards[0].content.controls[0].value.startswith("数学"))

    def test_teacher_assigns_a_grade_when_creating_a_class(self):
        page = FakePage()
        dashboard.main(page)
        picker_controls = page.controls[0].content.controls
        picker_controls[3].controls[0].on_click(None)
        class_view = open_dashboard_view(page, "クラス管理").controls[0]
        class_panel = class_view.controls[0]
        class_form = class_panel.content.controls[2]
        fields = class_form.content.controls
        fields[0].value = "3年C組"
        fields[1].value = "3年生"
        fields[2].on_click(None)

        created_class = next(
            class_info for class_info in self.store.list_classes()
            if class_info["name"] == "3年C組"
        )
        self.assertEqual(created_class["grade"], "3年生")

    def test_students_only_see_teacher_published_tests(self):
        teacher_page = FakePage()
        dashboard.main(teacher_page)
        picker_controls = teacher_page.controls[0].content.controls
        picker_controls[3].controls[0].on_click(None)
        teacher_test_view = open_dashboard_view(teacher_page, "テスト")
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
        student_test_view = open_dashboard_view(student_page, "テスト")
        student_panel = student_test_view.controls[0]
        refresh_button = student_panel.content.controls[3]
        refresh_button.on_click(None)
        student_panel = dashboard_view(student_page).controls[0]
        cards = student_panel.content.controls[4].controls
        test_card = cards[0]
        self.assertEqual(test_card.content.controls[0].value, "理科")
        self.assertEqual(test_card.content.controls[1].value, "試験日時: 2026-11-12 09:00")
        self.assertEqual(test_card.content.controls[4].value, "教科書 p.20-30")

        teacher_page = FakePage()
        dashboard.main(teacher_page)
        picker_controls = teacher_page.controls[0].content.controls
        picker_controls[3].controls[0].on_click(None)
        teacher_test_view = open_dashboard_view(teacher_page, "テスト")
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

        student_panel = dashboard_view(student_page).controls[0]
        student_panel.content.controls[3].on_click(None)
        student_panel = dashboard_view(student_page).controls[0]
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

        student_panel = open_dashboard_view(page, "テスト").controls[0]
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

        student_panel = dashboard_view(page).controls[0]
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

    def test_sidebar_opens_chat_and_stays_visible_on_narrow_pages(self):
        page = FakePage()
        dashboard.main(page)
        picker_controls = page.controls[0].content.controls
        picker_controls[3].controls[0].on_click(None)

        teacher = self.store.get_development_user("teacher")
        contact = self.store.list_contacts(teacher)[-1]
        contact_item = find_control_by_data(
            page.controls[0], f"dashboard-contact:{contact['conversation_id']}"
        )
        self.assertIsNotNone(contact_item)
        contact_item.on_click(None)

        chat_panel = dashboard_view(page).controls[0]
        conversation_header = chat_panel.content.controls[2]
        self.assertEqual(
            conversation_header.controls[1].controls[0].value,
            contact["label"],
        )

        page.width = 600
        page.on_resize(None)
        sidebar = find_control_by_data(page.controls[0], "dashboard-sidebar")
        self.assertEqual(sidebar.width, 200)
        self.assertEqual(
            page.horizontal_alignment,
            dashboard.ft.CrossAxisAlignment.START,
        )

    def test_old_dashboard_refresh_stops_after_switching_roles(self):
        page = FakePage()
        threads = []

        class CapturedThread:
            def __init__(self, target, daemon):
                self.target = target
                threads.append(self)

            def start(self):
                pass

        with patch("dashboard.threading.Thread", CapturedThread):
            dashboard.main(page)
            picker_controls = page.controls[0].content.controls
            picker_controls[3].controls[0].on_click(None)

            find_control_by_data(
                page.controls[0], "dashboard-logout"
            ).on_click(None)
            picker_controls = page.controls[0].content.controls
            picker_controls[3].controls[1].on_click(None)

            with patch(
                "dashboard.time.sleep",
                side_effect=lambda _: setattr(
                    page, "_dashboard_auto_refresh_active", False
                ),
            ):
                threads[0].target()

        self.assertEqual(page.thread_callbacks, [])
        labels = dashboard_navigation_labels(page)
        self.assertIn("自分のタスク", labels)
        self.assertNotIn("クラス管理", labels)

    def test_assignment_management_tracks_status_and_shows_due_notice(self):
        student_user = self.store.get_development_user("student")
        due_date = (date.today() + timedelta(days=1)).isoformat()

        teacher_page = FakePage()
        dashboard.main(teacher_page)
        picker_controls = teacher_page.controls[0].content.controls
        picker_controls[3].controls[0].on_click(None)
        assignment_view = open_dashboard_view(teacher_page, "課題")
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

        assignment_view = dashboard_view(teacher_page)
        assignment_panel = assignment_view.controls[0]
        assignment_card = assignment_panel.content.controls[5].controls[0]
        self.assertEqual(
            assignment_card.content.controls[2].value,
            "提出内容: 教科書 p.20-30 の問題を解く",
        )
        submission_rows = assignment_card.content.controls[5].controls
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
        assignment_view = open_dashboard_view(student_page, "課題")
        assignment_card = assignment_view.controls[0].content.controls[2].controls[0]
        self.assertEqual(
            assignment_card.content.controls[2].value,
            "提出内容: 教科書 p.20-30 の問題を解く",
        )
        self.assertEqual(assignment_card.content.controls[3].value, "提出状況: 提出済み")
        self.assertEqual(len(assignment_view.controls[0].content.controls[2].controls), 1)
        self.assertIsNone(find_control_by_data(
            student_page.controls[0], "dashboard-due-notices"
        ))

        self.store.set_assignment_submitted(
            assignment_id, student_user["id"], False
        )
        dashboard.main(student_page)
        picker_controls = student_page.controls[0].content.controls
        picker_controls[3].controls[1].on_click(None)
        notice = find_control_by_data(
            student_page.controls[0], "dashboard-due-notices"
        )
        self.assertEqual(notice.content.controls[0].value, "未提出の課題があります")
        self.assertIn("明日が提出日です", notice.content.controls[1].value)

    def test_teacher_can_add_subjects_for_other_grades(self):
        page = FakePage()
        dashboard.main(page)
        picker_controls = page.controls[0].content.controls
        picker_controls[3].controls[0].on_click(None)
        test_view = open_dashboard_view(page, "テスト")
        test_panel = test_view.controls[0]
        grade_dropdown = test_panel.content.controls[2].controls[0]
        grade_dropdown.value = "2年生"
        grade_dropdown.on_select(None)

        test_view = dashboard_view(page)
        test_panel = test_view.controls[0]
        subject_row = test_panel.content.controls[2]
        subject_row.controls[1].value = "化学"
        subject_row.controls[2].on_click(None)

        self.assertEqual(self.store.list_test_subjects("2年生"), ["化学"])
        test_view = dashboard_view(page)
        test_rows = test_view.controls[0].content.controls[4]
        card_fields = test_rows.controls[0].content.controls
        self.assertEqual(card_fields[0].value, "化学")
        self.assertEqual(
            [field.label for field in card_fields[:4]],
            ["科目", "試験日", "時刻", "範囲"],
        )


if __name__ == "__main__":
    unittest.main()
