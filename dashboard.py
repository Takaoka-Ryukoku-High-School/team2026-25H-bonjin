import base64
import math
import sqlite3
import threading
import time
from datetime import datetime, timedelta

import flet as ft

from store import PUBLIC_COLLECTIONS, TEST_GRADES, Store


GREEN = "#2E6654"
GREEN_LIGHT = "#E2EDE5"
PAPER = "#F6F5EF"
INK = "#202C2A"
MUTED = "#77807B"
WHITE = "#FFFEFA"
WEEKDAY_OPTIONS = ("月", "火", "水", "木", "金")
MAX_ASSIGNMENT_IMAGES = 5
MAX_ASSIGNMENT_IMAGE_SIZE = 5 * 1024 * 1024
MAX_ASSIGNMENT_IMAGES_SIZE = 10 * 1024 * 1024
PERIOD_TIMES = {
    "1": "09:00-09:50",
    "2": "10:00-10:50",
    "3": "11:00-11:50",
    "4": "13:00-13:50",
    "5": "14:00-14:50",
    "6": "15:00-15:50",
    "7": "16:00-16:50",
}


def image_media_type(contents):
    if contents.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if contents.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if contents[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if contents.startswith(b"RIFF") and contents[8:12] == b"WEBP":
        return "image/webp"
    return None


def assignment_visible_to_user(assignment, user, classes):
    if user["role"] != "student":
        return True
    target_type = assignment.get("target_type", "all")
    if target_type == "all":
        return True

    student_class = next(
        (
            class_info for class_info in classes
            if str(class_info["id"]) == str(user.get("class_id"))
        ),
        None,
    )
    if student_class is None:
        return False
    if target_type == "grade":
        return student_class.get("grade") == assignment.get("target_grade")
    if target_type == "class":
        return str(student_class["id"]) == str(assignment.get("target_class_id"))
    return False


def text_field(label, hint, expand=True, width=None, password=False, on_submit=None):
    return ft.TextField(
        label=label,
        hint_text=hint,
        expand=expand,
        width=width,
        password=password,
        can_reveal_password=password,
        on_submit=on_submit,
        border_radius=6,
        border_color="#D4DED5",
        focused_border_color=GREEN,
        bgcolor=WHITE,
        text_size=14,
    )


def main(page: ft.Page, require_login=False):
    store = Store()
    assignment_image_picker = next(
        (service for service in page.services if isinstance(service, ft.FilePicker)),
        None,
    )
    if assignment_image_picker is None:
        assignment_image_picker = ft.FilePicker()
        page.services.append(assignment_image_picker)
    dashboard_layout = [None]
    page.title = "今日の段取り | 学生ダッシュボード"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = "#ECEFEC"
    page.padding = 0
    page.horizontal_alignment = ft.CrossAxisAlignment.START
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.scroll = ft.ScrollMode.AUTO
    page.on_resize = lambda e: resize_page()

    def show_role_picker():
        page._dashboard_auto_refresh_token = None
        page._dashboard_auto_refresh_active = False
        page._student_auto_refresh_active = False
        page._teacher_auto_refresh_active = False
        dashboard_layout[0] = None

        def enter_role(role):
            try:
                store.get_development_user("teacher")
                store.get_development_user("student")
                user = store.get_development_user(role)
            except (OSError, sqlite3.Error, ValueError) as error:
                page.controls.clear()
                page.add(ft.Text(f"開発用アカウントを準備できませんでした: {error}",
                                 color=INK, size=14))
                page.update()
                return
            show_dashboard(user)

        content = ft.Container(
            content=ft.Column([
                ft.Text("開発モード", size=22, color=INK, weight=ft.FontWeight.W_600),
                ft.Text("ログインせずに先生用・生徒用の画面を確認できます。",
                        size=14, color=MUTED),
                ft.Text("開発中専用です。画面を開ける人は先生用機能も利用できます。",
                        size=12, color=MUTED),
                ft.Row([
                    ft.Button("先生用で開く", bgcolor=GREEN, color="white",
                              on_click=lambda e: enter_role("teacher")),
                    ft.Button("生徒用で開く", bgcolor=GREEN, color="white",
                              on_click=lambda e: enter_role("student")),
                ], spacing=12, wrap=True),
                ft.TextButton("ログイン画面へ", on_click=lambda e: show_login())
                if require_login else ft.Container(),
            ], spacing=14),
            width=460,
            padding=24,
            bgcolor=WHITE,
            border=ft.Border.all(1, "#E3E3D9"),
            border_radius=8,
        )
        page.controls.clear()
        page.add(content)
        resize_page()
        page.update()

    def show_login(message=""):
        page._dashboard_auto_refresh_token = None
        page._dashboard_auto_refresh_active = False
        page._student_auto_refresh_active = False
        page._teacher_auto_refresh_active = False
        dashboard_layout[0] = None

        username = text_field("ユーザー名", "ユーザー名")
        password = text_field("パスワード", "パスワード", password=True)
        status = ft.Text(message, color=MUTED, size=12)

        def login(e):
            user = store.authenticate(username.value or "", password.value or "")
            if user is None:
                status.value = "ユーザー名またはパスワードが違います。"
                page.update()
                return
            show_dashboard(user)

        controls = [
            ft.Text("ログイン", size=22, color=INK, weight=ft.FontWeight.W_600),
            username,
            password,
            ft.Button("ログイン", bgcolor=GREEN, color="white", on_click=login),
            status,
        ]
        if not store.has_teacher():
            controls.append(ft.Text(
                "先生アカウントがまだありません。管理者が `python main.py create-teacher` を実行してください。",
                color=MUTED,
                size=12,
            ))
        content = ft.Container(
            content=ft.Column(controls, spacing=14),
            width=460,
            padding=24,
            bgcolor=WHITE,
            border=ft.Border.all(1, "#E3E3D9"),
            border_radius=8,
        )
        page.controls.clear()
        page.add(content)
        resize_page()
        page.update()

    def show_dashboard(user):
        auto_refresh_token = object()
        page._dashboard_auto_refresh_token = auto_refresh_token
        auto_refresh_started = [False]
        status = ft.Text(color=MUTED, size=12)
        selected_conversation = [None]
        selected_tab = [0]
        selected_timetable_class = [None]
        selected_timetable_day = ["月"]
        selected_test_grade = ["1年生"]
        selected_reminder_to_edit = [None]
        new_note_pending = [False]

        def refresh(message=None):
            if message:
                status.value = message
            page.update()

        def fail(message):
            status.value = message
            page.update()

        def row(collection, item, title, detail="", editable=False, on_edit=None):
            controls = []
            if collection == "tasks":
                controls.append(ft.Checkbox(
                    value=item.get("done", False),
                    active_color=GREEN,
                    on_change=lambda e, item_id=item["id"]: toggle_task(item_id),
                ))
            else:
                controls.append(ft.Container(width=8))
            style = ft.TextStyle(
                color="#929992" if item.get("done") else INK,
                decoration=ft.TextDecoration.LINE_THROUGH if item.get("done") else None,
                size=14,
            )
            labels = [ft.Text(title, style=style)]
            if detail:
                labels.append(ft.Text(detail, size=12, color=MUTED))
            controls.append(ft.Column(labels, spacing=3, expand=True))
            if editable:
                if on_edit:
                    controls.append(ft.IconButton(
                        icon=ft.Icons.EDIT_OUTLINED,
                        icon_color=MUTED,
                        tooltip="編集",
                        on_click=lambda e: on_edit(),
                    ))
                controls.append(ft.IconButton(
                    icon=ft.Icons.DELETE_OUTLINE,
                    icon_color=MUTED,
                    tooltip="削除",
                    on_click=lambda e, item_id=item["id"]: remove_item(collection, item_id),
                ))
            return ft.Container(
                content=ft.Row(controls, spacing=8),
                padding=ft.Padding.symmetric(vertical=9, horizontal=14),
                border=ft.Border.only(bottom=ft.BorderSide(1, "#DEDFD5")),
            )

        def panel(title, subtitle, controls):
            return ft.Container(
                content=ft.Column(
                    [ft.Text(title, size=20, color=INK, weight=ft.FontWeight.W_600),
                     ft.Text(subtitle, size=12, color=MUTED)] + controls,
                    spacing=10,
                ),
                bgcolor=WHITE,
                border=ft.Border.all(1, "#E3E3D9"),
                border_radius=8,
                padding=18,
            )

        def form(inputs, button_text, callback):
            return ft.Container(
                content=ft.Row(
                    inputs + [ft.Button(button_text, bgcolor=GREEN, color="white",
                                        height=42, on_click=callback)],
                    spacing=8,
                    wrap=True,
                ),
                padding=12,
                bgcolor=GREEN_LIGHT,
            )

        def add_item(collection, payload, success_message):
            if user["role"] != "teacher" or collection not in PUBLIC_COLLECTIONS:
                fail("この操作を行う権限がありません。")
                return
            try:
                store.add_item(collection, payload)
            except (OSError, sqlite3.Error) as error:
                fail(f"保存できませんでした: {error}")
                return
            render_all(success_message)

        def remove_item(collection, item_id):
            if collection != "tasks" and user["role"] != "teacher":
                fail("この操作を行う権限がありません。")
                return
            try:
                if collection == "timetable_exceptions":
                    store.delete_timetable_exception(item_id)
                else:
                    store.delete_item(
                        collection,
                        item_id,
                        owner_id=user["id"] if collection == "tasks" else None,
                    )
                if (collection == "reminders" and selected_reminder_to_edit[0]
                        and selected_reminder_to_edit[0]["id"] == item_id):
                    selected_reminder_to_edit[0] = None
            except (OSError, sqlite3.Error) as error:
                fail(f"削除できませんでした: {error}")
                return
            render_all("削除しました")

        def toggle_task(item_id):
            if user["role"] != "student":
                fail("この操作を行う権限がありません。")
                return
            tasks = store.list_items("tasks", user["id"])
            item = next((task for task in tasks if task["id"] == item_id), None)
            if item is None:
                fail("タスクが見つかりません。")
                return
            item["done"] = not item.get("done", False)
            store.update_item("tasks", item_id, item, user["id"])
            render_all("保存しました")

        def items_panel(collection, title, description):
            title_display = lambda item: ""
            detail_display = lambda item: ""
            on_edit_item = lambda item: None
            if collection == "timetable":
                day = ft.Dropdown(
                    label="曜日",
                    options=[ft.dropdown.Option(value) for value in WEEKDAY_OPTIONS],
                    width=100,
                )
                time = text_field("時間", "例 09:00-10:30")
                subject = text_field("科目", "科目名")
                inputs = [day, time, subject]

                def add(e):
                    if day.value and time.value and time.value.strip() and subject.value and subject.value.strip():
                        add_item(collection, {"day": day.value, "time": time.value.strip(),
                                              "subject": subject.value.strip()}, "時間割を登録しました")

                title_display = lambda item: f"{item['day']}曜日  {item['time']}"
                detail_display = lambda item: item["subject"]
            elif collection == "reminders":
                editing_reminder = selected_reminder_to_edit
                reminder_title = ft.TextField(
                    label="通知内容",
                    hint_text="例 レポート提出を確認",
                    multiline=True,
                    min_lines=1,
                    max_lines=4,
                    expand=True,
                )
                reminder_date = text_field("通知日", "YYYY-MM-DD", expand=False, width=150)
                reminder_time = text_field("通知時刻", "HH:MM", expand=False, width=120)
                inputs = [reminder_title, reminder_date, reminder_time]
                if editing_reminder[0]:
                    reminder_title.value = editing_reminder[0]["title"]
                    date_value, _, time_value = editing_reminder[0].get("when", "").partition(" ")
                    reminder_date.value = date_value
                    reminder_time.value = time_value

                def set_reminder_form(item=None):
                    selected_reminder_to_edit[0] = item
                    render_all()

                def add(e):
                    content = (reminder_title.value or "").strip()
                    date_value = (reminder_date.value or "").strip()
                    time_value = (reminder_time.value or "").strip()
                    if not content or not date_value or not time_value:
                        fail("通知内容・通知日・通知時刻を入力してください。")
                        return
                    try:
                        scheduled_at = datetime.strptime(
                            f"{date_value} {time_value}", "%Y-%m-%d %H:%M"
                        ).strftime("%Y-%m-%d %H:%M")
                        item = editing_reminder[0]
                        if item:
                            store.update_item(collection, item["id"], {
                                "title": content,
                                "when": scheduled_at,
                            })
                            selected_reminder_to_edit[0] = None
                            render_all("通知を更新しました")
                        else:
                            add_item(collection, {"title": content, "when": scheduled_at},
                                     "通知を登録しました")
                    except ValueError:
                        fail("通知日は YYYY-MM-DD、通知時刻は HH:MM 形式で入力してください。")
                    except (OSError, sqlite3.Error) as error:
                        fail(f"通知を保存できませんでした: {error}")

                title_display = lambda item: item["title"]
                detail_display = lambda item: f"通知時刻: {item['when']}"
                on_edit_item = lambda item: set_reminder_form(item)
            elif collection == "tests":
                title_display = lambda item: (
                    f"{item['subject']}  {item['date']} {item.get('time', '')}".strip()
                )
                detail_display = lambda item: item.get("detail", "")
            elif collection == "assignments":
                assignment_subject = text_field("科目", "例: 数学")
                assignment_content = ft.TextField(
                    label="提出内容",
                    hint_text="課題の内容や提出するものを入力（画像のみでも登録できます）",
                    multiline=True,
                    min_lines=2,
                    max_lines=4,
                    expand=True,
                )
                due = text_field("提出日", "YYYY-MM-DD")
                destination = text_field("提出先", "例: 教室で先生に提出")
                inputs = [assignment_subject, assignment_content, due, destination]
                assignment_classes = store.list_classes()
                target_scope = ft.Dropdown(
                    label="配信先",
                    options=[
                        ft.dropdown.Option("all", "全生徒"),
                        ft.dropdown.Option("grade", "学年"),
                        ft.dropdown.Option("class", "クラス"),
                    ],
                    value="all",
                    width=160,
                    data="assignment-target-scope",
                )
                target_value = ft.Dropdown(
                    label="学年・クラス",
                    options=[],
                    width=220,
                    visible=False,
                    data="assignment-target-value",
                )

                def update_assignment_target_options(e=None):
                    if target_scope.value == "grade":
                        grades = {
                            class_info["grade"] for class_info in assignment_classes
                            if class_info["grade"]
                        }
                        target_value.options = [
                            ft.dropdown.Option(grade)
                            for grade in TEST_GRADES if grade in grades
                        ]
                    elif target_scope.value == "class":
                        target_value.options = [
                            ft.dropdown.Option(str(class_info["id"]), class_info["name"])
                            for class_info in assignment_classes
                        ]
                    else:
                        target_value.options = []
                    target_value.value = (
                        target_value.options[0].key if target_value.options else None
                    )
                    target_value.visible = target_scope.value != "all"
                    page.update()

                target_scope.on_select = update_assignment_target_options
                selected_images = []
                image_previews = ft.Column(
                    spacing=6,
                    data="assignment-image-previews",
                )

                def render_image_previews():
                    image_previews.controls = [
                        ft.Row([
                            ft.Image(
                                src=image["contents"],
                                width=72,
                                height=56,
                                fit=ft.BoxFit.CONTAIN,
                                border_radius=6,
                                semantics_label=image["name"],
                            ),
                            ft.Text(image["name"], size=12, color=INK, expand=True),
                            ft.TextButton(
                                "削除",
                                on_click=lambda e, image_index=index: remove_image(image_index),
                            ),
                        ], spacing=8)
                        for index, image in enumerate(selected_images)
                    ]
                    page.update()

                def remove_image(index):
                    selected_images.pop(index)
                    render_image_previews()

                async def pick_assignment_images(e):
                    try:
                        files = await assignment_image_picker.pick_files(
                            dialog_title="課題に添付する画像を選択",
                            file_type=ft.FilePickerFileType.CUSTOM,
                            allowed_extensions=["png", "jpg", "jpeg", "gif", "webp"],
                            allow_multiple=True,
                            with_data=True,
                        )
                    except (OSError, ValueError) as error:
                        fail(f"画像を選択できませんでした: {error}")
                        return
                    if not files:
                        return
                    if len(selected_images) + len(files) > MAX_ASSIGNMENT_IMAGES:
                        fail(f"画像は課題ごとに{MAX_ASSIGNMENT_IMAGES}枚まで添付できます。")
                        return

                    new_images = []
                    for file in files:
                        contents = file.bytes
                        if contents is None:
                            fail(f"{file.name}の画像データを読み込めませんでした。")
                            return
                        if len(contents) > MAX_ASSIGNMENT_IMAGE_SIZE:
                            fail(f"{file.name}は1枚あたり5MB以下にしてください。")
                            return
                        media_type = image_media_type(contents)
                        if media_type is None:
                            fail(f"{file.name}は対応していない画像形式です。")
                            return
                        new_images.append({
                            "name": file.name,
                            "media_type": media_type,
                            "contents": contents,
                        })

                    total_size = sum(
                        len(image["contents"])
                        for image in [*selected_images, *new_images]
                    )
                    if total_size > MAX_ASSIGNMENT_IMAGES_SIZE:
                        fail("画像の合計サイズは10MB以下にしてください。")
                        return
                    selected_images.extend(new_images)
                    render_image_previews()
                    fail(f"{len(new_images)}枚の画像を添付しました。")

                image_picker_button = ft.TextButton(
                    "画像を添付",
                    icon=ft.Icons.ADD_PHOTO_ALTERNATE_OUTLINED,
                    data="assignment-image-picker",
                    on_click=pick_assignment_images,
                )

                def add(e):
                    subject_value = (assignment_subject.value or "").strip()
                    content_value = (assignment_content.value or "").strip()
                    due_value = (due.value or "").strip()
                    destination_value = (destination.value or "").strip()
                    if (
                        not subject_value or not due_value or not destination_value
                        or (not content_value and not selected_images)
                    ):
                        fail("科目・提出日・提出先と、提出内容または画像を入力してください。")
                        return
                    if target_scope.value != "all" and not target_value.value:
                        fail("配信する学年またはクラスを選択してください。")
                        return
                    try:
                        due_value = datetime.strptime(
                            due_value, "%Y-%m-%d"
                        ).strftime("%Y-%m-%d")
                    except ValueError:
                        fail("提出日は YYYY-MM-DD 形式で入力してください。")
                        return
                    add_item(collection, {
                        "subject": subject_value,
                        "content": content_value,
                        "due": due_value,
                        "destination": destination_value,
                        "target_type": target_scope.value,
                        "target_grade": (
                            target_value.value if target_scope.value == "grade" else None
                        ),
                        "target_class_id": (
                            target_value.value if target_scope.value == "class" else None
                        ),
                        "attachments": [
                            {
                                "name": image["name"],
                                "media_type": image["media_type"],
                                "data": base64.b64encode(
                                    image["contents"]
                                ).decode("ascii"),
                            }
                            for image in selected_images
                        ],
                    }, "課題を登録しました")
            else:
                date = text_field("日付", "YYYY-MM-DD")
                event_title = text_field("行事・予定", "例 体育祭、保護者会")
                detail = text_field("内容", "場所や持ち物など")
                inputs = [date, event_title, detail]

                def add(e):
                    if date.value and date.value.strip() and event_title.value and event_title.value.strip():
                        add_item(collection, {"date": date.value.strip(),
                                              "title": event_title.value.strip(),
                                              "detail": (detail.value or "").strip()},
                                 "予定を登録しました")

                title_display = lambda item: f"{item['date']}  {item['title']}"
                detail_display = lambda item: item.get("detail", "")

            can_edit = user["role"] == "teacher" or collection == "tests"
            if can_edit:
                if collection == "tests":
                    fields = []
                else:
                    button_text = (
                        "通知を更新" if collection == "reminders" and editing_reminder[0]
                        else "登録する"
                    )
                    if collection == "assignments":
                        fields = [
                            form(inputs, button_text, add),
                            ft.Container(
                                content=ft.Row([
                                    target_scope,
                                    target_value,
                                    ft.Text(
                                        "登録すると選択した生徒の画面に配信されます。",
                                        size=11,
                                        color=MUTED,
                                    ),
                                ], wrap=True, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                padding=10,
                                bgcolor="#F4F6F4",
                                border_radius=8,
                            ),
                            ft.Container(
                                content=ft.Column([
                                    ft.Row([
                                        image_picker_button,
                                        ft.Text(
                                            "PNG・JPEG・GIF・WebP（最大5枚、合計10MB）",
                                            size=11,
                                            color=MUTED,
                                        ),
                                    ], spacing=8, wrap=True),
                                    image_previews,
                                ], spacing=6),
                                padding=10,
                                bgcolor="#F4F6F4",
                                border_radius=8,
                            ),
                        ]
                    else:
                        fields = [form(inputs, button_text, add)]
                    if collection == "reminders" and editing_reminder[0]:
                        fields.append(ft.TextButton(
                            "編集をキャンセル",
                            on_click=lambda e: set_reminder_form(),
                        ))
            else:
                fields = []
            items = store.list_items(collection)
            assignment_classes = []
            if collection == "assignments":
                assignment_classes = store.list_classes()
                if user["role"] == "student":
                    items = [
                        item for item in items
                        if assignment_visible_to_user(item, user, assignment_classes)
                    ]
            if collection in ("calendar", "tests"):
                items.sort(key=lambda item: (
                    item.get("date", ""),
                    item.get("time", ""),
                ))
            if collection == "assignments":
                items.sort(key=lambda item: item.get("due", ""))
            if collection == "reminders":
                items.sort(key=lambda item: item.get("when", ""))
            if collection == "tests":
                if user["role"] == "student":
                    items = [item for item in items if item.get("published", False)]
                    items = [
                        item for item in items
                        if item.get("grade", "1年生") == selected_test_grade[0]
                    ]
                    test_cards = [
                        ft.Container(
                            content=ft.Column([
                                ft.Text(
                                    item.get("subject", ""),
                                    size=17,
                                    color=INK,
                                    weight=ft.FontWeight.W_600,
                                ),
                                ft.Text(
                                    f"試験日時: {item.get('date', '')} "
                                    f"{item.get('time', '')}".strip(),
                                    size=13,
                                    color=MUTED,
                                ),
                                ft.Divider(height=1, color="#DEDFD5"),
                                ft.Text("試験範囲", size=12, color=MUTED),
                                ft.Text(
                                    item.get("detail", "") or "範囲は未登録です。",
                                    size=14,
                                    color=INK,
                                ),
                            ], spacing=7),
                            padding=14,
                            bgcolor=WHITE,
                            border=ft.Border.all(1, "#E3E3D9"),
                            border_radius=6,
                        )
                        for item in items
                    ]
                    grade_dropdown = ft.Dropdown(
                        label="学年",
                        value=selected_test_grade[0],
                        options=[
                            ft.dropdown.Option(grade) for grade in TEST_GRADES
                        ],
                        width=150,
                    )

                    def select_student_test_grade(e):
                        selected_test_grade[0] = grade_dropdown.value
                        render_all()

                    grade_dropdown.on_select = select_student_test_grade
                    fields.append(grade_dropdown)
                    fields.append(ft.Button(
                        "最新のテスト予定を表示",
                        bgcolor=GREEN,
                        color="white",
                        on_click=lambda e: render_all("テスト予定を更新しました。"),
                    ))
                    fields.append(ft.Column(
                        test_cards or [
                            ft.Text("先生から配信されたテストはありません。", color=MUTED)
                        ],
                        spacing=10,
                    ))
                    return panel(title, description, fields)
                is_teacher = user["role"] == "teacher"
                if is_teacher:
                    grade_dropdown = ft.Dropdown(
                        label="学年",
                        value=selected_test_grade[0],
                        options=[
                            ft.dropdown.Option(grade) for grade in TEST_GRADES
                        ],
                        width=150,
                    )

                    def select_test_grade(e):
                        selected_test_grade[0] = grade_dropdown.value
                        render_all()

                    grade_dropdown.on_select = select_test_grade
                    subject_to_add = ft.TextField(
                        label="教科を追加",
                        hint_text="例: 化学",
                        width=180,
                    )

                    def add_test_subject(e):
                        try:
                            added = store.add_test_subject(
                                selected_test_grade[0],
                                subject_to_add.value or "",
                            )
                        except ValueError as error:
                            fail(str(error))
                            return
                        except (OSError, sqlite3.Error) as error:
                            fail(f"教科を追加できませんでした: {error}")
                            return
                        render_all(
                            "教科を追加しました。" if added else "この教科は登録済みです。"
                        )

                    fields.append(ft.Row([
                        grade_dropdown,
                        subject_to_add,
                        ft.Button(
                            "教科を追加",
                            bgcolor=GREEN,
                            color="white",
                            on_click=add_test_subject,
                        ),
                    ], wrap=True, spacing=8))
                    items = [
                        item for item in items
                        if item.get("grade", "1年生") == selected_test_grade[0]
                    ]
                    test_subjects = store.list_test_subjects(selected_test_grade[0])
                else:
                    test_subjects = []

                test_rows = []
                editable_test_rows = []

                def make_test_fields(item=None):
                    return (
                        ft.TextField(
                            label="科目",
                            hint_text="例 数学",
                            value=item.get("subject", "") if item else "",
                            border_radius=6,
                            border_color="#D4DED5",
                            focused_border_color=GREEN,
                            bgcolor=WHITE,
                            text_size=14,
                        ),
                        ft.TextField(
                            label="試験日",
                            hint_text="YYYY-MM-DD",
                            value=item.get("date", "") if item else "",
                            border_radius=6,
                            border_color="#D4DED5",
                            focused_border_color=GREEN,
                            bgcolor=WHITE,
                            text_size=14,
                        ),
                        ft.TextField(
                            label="時刻",
                            hint_text="HH:MM",
                            value=item.get("time", "") if item else "",
                            border_radius=6,
                            border_color="#D4DED5",
                            focused_border_color=GREEN,
                            bgcolor=WHITE,
                            text_size=14,
                        ),
                        ft.TextField(
                            label="範囲",
                            hint_text="教科書 p.10-30",
                            value=item.get("detail", "") if item else "",
                            multiline=True,
                            min_lines=1,
                            max_lines=3,
                        ),
                    )

                def test_editor_card(subject_field, date_field, time_field,
                                     detail_field, actions):
                    return ft.Container(
                        content=ft.Column([
                            subject_field,
                            date_field,
                            time_field,
                            detail_field,
                            ft.Row(actions, wrap=True, spacing=8),
                        ], spacing=8),
                        padding=14,
                        bgcolor=WHITE,
                        border=ft.Border.all(1, "#E3E3D9"),
                        border_radius=6,
                    )

                def save_test(e, item_id, subject_field, date_field,
                              time_field, detail_field, publish=False):
                    if not is_teacher:
                        fail("テスト予定の編集は先生のみ行えます。")
                        return
                    subject_value = (subject_field.value or "").strip()
                    date_value = (date_field.value or "").strip()
                    time_value = (time_field.value or "").strip()
                    if not subject_value or not date_value or not time_value:
                        fail("科目・試験日・開始時刻を入力してください。")
                        return
                    try:
                        date_value = datetime.strptime(date_value, "%Y-%m-%d").strftime("%Y-%m-%d")
                        time_value = datetime.strptime(time_value, "%H:%M").strftime("%H:%M")
                        is_new = item_id is None
                        payload = {
                            "subject": subject_value,
                            "grade": selected_test_grade[0],
                            "date": date_value,
                            "time": time_value,
                            "detail": (detail_field.value or "").strip(),
                        }
                        if item_id is None:
                            item_id = store.add_item("tests", payload)
                        else:
                            store.update_item("tests", item_id, payload)
                        if publish and not store.set_test_published(item_id, True):
                            fail("配信するテストが見つかりません。")
                            return
                        if publish:
                            render_all("テスト予定を保存して生徒へ配信しました。")
                        elif is_new:
                            render_all("テスト予定を登録しました")
                        else:
                            render_all("テスト予定を保存しました")
                    except ValueError:
                        fail("試験日は YYYY-MM-DD、開始時刻は HH:MM 形式で入力してください。")
                    except (OSError, sqlite3.Error) as error:
                        fail(f"テスト予定を保存できませんでした: {error}")

                def publish_all_tests(e):
                    if not is_teacher:
                        fail("テスト予定の配信は先生のみ行えます。")
                        return
                    try:
                        changes = []
                        for item_id, subject_field, date_field, time_field, detail_field in editable_test_rows:
                            subject_value = (subject_field.value or "").strip()
                            date_value = (date_field.value or "").strip()
                            time_value = (time_field.value or "").strip()
                            detail_value = (detail_field.value or "").strip()
                            if item_id is None and not any(
                                (date_value, time_value, detail_value)
                            ):
                                continue
                            if not subject_value or not date_value or not time_value:
                                fail("配信するテストは科目・試験日・開始時刻を入力してください。")
                                return
                            date_value = datetime.strptime(date_value, "%Y-%m-%d").strftime("%Y-%m-%d")
                            time_value = datetime.strptime(time_value, "%H:%M").strftime("%H:%M")
                            changes.append((item_id, {
                                "subject": subject_value,
                                "grade": selected_test_grade[0],
                                "date": date_value,
                                "time": time_value,
                                "detail": detail_value,
                            }))
                        for item_id, payload in changes:
                            if item_id is None:
                                store.add_item("tests", payload)
                            else:
                                store.update_item("tests", item_id, payload)
                        published_count = store.publish_all_tests()
                    except ValueError:
                        fail("試験日は YYYY-MM-DD、開始時刻は HH:MM 形式で入力してください。")
                        return
                    except (OSError, sqlite3.Error) as error:
                        fail(f"テスト予定を保存・配信できませんでした: {error}")
                        return
                    render_all(
                        f"入力内容を保存し、テストを{published_count}件生徒側へ配信しました。"
                        if published_count
                        else "入力内容を保存し、生徒側のテスト予定に反映しました。"
                    )

                if is_teacher:
                    fields.append(ft.Button(
                        "入力内容を保存して生徒へ配信",
                        bgcolor=GREEN,
                        color="white",
                        on_click=publish_all_tests,
                    ))

                for item in items:
                    if is_teacher:
                        subject_field, date_field, time_field, detail_field = make_test_fields(item)
                        editable_test_rows.append((
                            item["id"], subject_field, date_field, time_field, detail_field,
                        ))
                        action_controls = [
                            ft.Button(
                                "保存",
                                bgcolor=GREEN,
                                color="white",
                                on_click=lambda e, item_id=item["id"],
                                subject=subject_field, date=date_field,
                                time=time_field, detail=detail_field: save_test(
                                    e, item_id, subject, date, time, detail
                                ),
                            ),
                            ft.Button(
                                "保存して生徒へ配信",
                                bgcolor=GREEN,
                                color="white",
                                on_click=lambda e, item_id=item["id"],
                                subject=subject_field, date=date_field,
                                time=time_field, detail=detail_field: save_test(
                                    e, item_id, subject, date, time, detail, True
                                ),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_color=MUTED,
                                tooltip="削除",
                                on_click=lambda e, item_id=item["id"]: remove_item(
                                    "tests", item_id
                                ),
                            ),
                        ]
                        test_rows.append(test_editor_card(
                            subject_field, date_field, time_field, detail_field,
                            action_controls,
                        ))
                    else:
                        test_rows.append(ft.Container(
                            content=ft.Column([
                                ft.Text(
                                    item.get("subject", ""),
                                    size=17,
                                    color=INK,
                                    weight=ft.FontWeight.W_600,
                                ),
                                ft.Text(
                                    f"試験日: {item.get('date', '')}",
                                    size=13,
                                    color=MUTED,
                                ),
                                ft.Text(
                                    f"開始時刻: {item.get('time', '')}",
                                    size=13,
                                    color=MUTED,
                                ),
                                ft.Text("試験範囲", size=12, color=MUTED),
                                ft.Text(
                                    item.get("detail", "") or "範囲は未登録です。",
                                    size=14,
                                    color=INK,
                                ),
                            ], spacing=7),
                            padding=14,
                            bgcolor=WHITE,
                            border=ft.Border.all(1, "#E3E3D9"),
                            border_radius=6,
                        ))

                if is_teacher:
                    existing_subjects = {item.get("subject", "") for item in items}
                    for preset_subject in test_subjects:
                        if preset_subject in existing_subjects:
                            continue
                        new_subject, new_date, new_time, new_detail = make_test_fields()
                        new_subject.value = preset_subject
                        editable_test_rows.append((
                            None, new_subject, new_date, new_time, new_detail,
                        ))
                        test_rows.append(test_editor_card(
                            new_subject, new_date, new_time, new_detail,
                            [ft.Button(
                                "保存して生徒へ配信",
                                bgcolor=GREEN,
                                color="white",
                                on_click=lambda e, subject=new_subject,
                                date=new_date, time=new_time, detail=new_detail: save_test(
                                    e, None, subject, date, time, detail, True
                                ),
                            )],
                        ))
                    if not test_subjects and not items:
                        test_rows.append(
                            ft.Text("この学年の教科を上から追加してください。", color=MUTED)
                        )
                elif not items:
                    test_rows.append(ft.Text(
                        "先生から配信されたテストはありません。", color=MUTED
                    ))
                fields.append(ft.Column(test_rows, spacing=10))
            elif collection == "assignments":
                def update_assignment_submission(e, assignment_id, student_id):
                    if user["role"] != "teacher":
                        fail("提出状況を変更できるのは先生のみです。")
                        return
                    try:
                        store.set_assignment_submitted(
                            assignment_id,
                            student_id,
                            e.control.value == "submitted",
                        )
                    except (ValueError, OSError, sqlite3.Error) as error:
                        fail(f"提出状況を保存できませんでした: {error}")
                        return
                    render_all("提出状況を更新しました。")

                assignment_cards = []
                for item in items:
                    assignment_id = item["id"]
                    subject = item.get("subject") or item.get("title", "")
                    destination_value = item.get("destination") or item.get("detail", "")
                    card_controls = [
                        ft.Text(
                            f"{subject}　提出日: {item.get('due', '')}",
                            size=16,
                            color=INK,
                            weight=ft.FontWeight.W_600,
                        ),
                        ft.Text(
                            f"提出先: {destination_value}",
                            size=13,
                            color=MUTED,
                        ),
                    ]
                    content_text = item.get("content", "")
                    attachments = item.get("attachments", [])
                    if content_text:
                        card_controls.append(ft.Text(
                            f"提出内容: {content_text}",
                            size=13,
                            color=INK,
                        ))
                    elif not attachments:
                        card_controls.append(ft.Text(
                            "提出内容: 内容は未登録です。",
                            size=13,
                            color=INK,
                        ))
                    if attachments:
                        card_controls.append(ft.Text("添付画像", size=12, color=MUTED))
                        card_controls.append(ft.Row([
                            ft.Image(
                                src=(
                                    f"data:{attachment['media_type']};base64,"
                                    f"{attachment['data']}"
                                ),
                                width=220,
                                height=160,
                                fit=ft.BoxFit.CONTAIN,
                                border_radius=8,
                                semantics_label=attachment["name"],
                            )
                            for attachment in attachments
                        ], spacing=8, wrap=True))
                    if user["role"] == "student":
                        submitted = store.assignment_submitted(assignment_id, user["id"])
                        card_controls.append(ft.Text(
                            f"提出状況: {'提出済み' if submitted else '未提出'}",
                            size=13,
                            color=GREEN if submitted else MUTED,
                        ))
                    else:
                        target_type = item.get("target_type", "all")
                        if target_type == "grade":
                            audience = item.get("target_grade", "学年未設定")
                        elif target_type == "class":
                            audience = next(
                                (
                                    class_info["name"]
                                    for class_info in assignment_classes
                                    if str(class_info["id"])
                                    == str(item.get("target_class_id"))
                                ),
                                "クラス未設定",
                            )
                        else:
                            audience = "全生徒"
                        card_controls.append(ft.Text(
                            f"配信先: {audience}",
                            size=12,
                            color=MUTED,
                        ))
                        submission_rows = []
                        for submission in store.list_assignment_submission_statuses(assignment_id):
                            status_dropdown = ft.Dropdown(
                                value="submitted" if submission["submitted"] else "pending",
                                options=[
                                    ft.dropdown.Option("pending", "未提出"),
                                    ft.dropdown.Option("submitted", "提出済み"),
                                ],
                                width=140,
                                on_select=lambda e, aid=assignment_id,
                                sid=submission["student_id"]: update_assignment_submission(
                                    e, aid, sid
                                ),
                            )
                            submission_rows.append(ft.Row([
                                ft.Text(
                                    f"{submission['username']} "
                                    f"({submission.get('class_name') or 'クラス未設定'})",
                                    expand=True,
                                    size=13,
                                    color=INK,
                                ),
                                status_dropdown,
                            ]))
                        card_controls.append(ft.Text("生徒ごとの提出状況", size=12, color=MUTED))
                        card_controls.append(ft.Column(
                            submission_rows or [
                                ft.Text("生徒アカウントはまだありません。", size=13, color=MUTED)
                            ],
                            spacing=4,
                        ))
                    assignment_cards.append(ft.Container(
                        content=ft.Column(card_controls, spacing=7),
                        padding=14,
                        bgcolor=WHITE,
                        border=ft.Border.all(1, "#E3E3D9"),
                        border_radius=6,
                    ))
                fields.append(ft.Column(
                    assignment_cards or [
                        ft.Text("登録された課題はありません。", color=MUTED, size=13)
                    ],
                    spacing=10,
                ))
            else:
                rows = [
                    row(
                        collection, item, title_display(item), detail_display(item),
                        editable=can_edit,
                        on_edit=(lambda item=item: on_edit_item(item))
                        if collection == "reminders" and can_edit else None,
                    )
                    for item in items
                ]
                fields.append(ft.Column(
                    rows or [ft.Text("登録された情報はありません。", color=MUTED, size=13)],
                    spacing=0,
                ))
            role_description = "先生が登録・編集できます。" if not can_edit else description
            return panel(title, role_description, fields)

        def tasks_view():
            saved_notes = store.list_items("notes", user["id"])
            canvas_width = max(280, min(640, (page.width or 1200) - 360))
            canvas_height = 360

            def note_editor(note, index):
                note_key = note["id"] if note else "new"
                note_strokes = [
                    [
                        [float(point[0]), float(point[1])]
                        for point in stroke
                        if (
                            isinstance(point, (list, tuple))
                            and len(point) == 2
                            and isinstance(point[0], (int, float))
                            and isinstance(point[1], (int, float))
                        )
                    ]
                    for stroke in (note or {}).get("strokes", [])
                    if isinstance(stroke, list)
                ]
                note_strokes = [stroke for stroke in note_strokes if stroke]
                memo = ft.TextField(
                    label="文字でメモ",
                    value=(note or {}).get("text", ""),
                    multiline=True,
                    min_lines=5,
                    max_lines=10,
                    data=f"student-note-text:{note_key}",
                )

                def dot(point):
                    return ft.Container(
                        left=point[0] * canvas_width - 2.5,
                        top=point[1] * canvas_height - 2.5,
                        width=5,
                        height=5,
                        bgcolor=INK,
                        border_radius=5,
                    )

                drawing_stack = ft.Stack(
                    controls=[
                        ft.Container(
                            width=canvas_width,
                            height=canvas_height,
                            bgcolor=WHITE,
                        ),
                        *[
                            dot(point)
                            for stroke in note_strokes
                            for point in stroke
                        ],
                    ],
                )
                active_stroke = [None]

                def add_drawing_point(event, start=False):
                    x = min(1.0, max(0.0, event.local_position.x / canvas_width))
                    y = min(1.0, max(0.0, event.local_position.y / canvas_height))
                    point = [x, y]
                    if start:
                        active_stroke[0] = []
                        note_strokes.append(active_stroke[0])

                    current = active_stroke[0]
                    if current is None:
                        return
                    if current:
                        previous = current[-1]
                        distance = math.hypot(
                            (point[0] - previous[0]) * canvas_width,
                            (point[1] - previous[1]) * canvas_height,
                        )
                        steps = max(1, math.ceil(distance / 3))
                        new_points = [
                            [
                                previous[0] + (point[0] - previous[0]) * step / steps,
                                previous[1] + (point[1] - previous[1]) * step / steps,
                            ]
                            for step in range(1, steps + 1)
                        ]
                    else:
                        new_points = [point]
                    current.extend(new_points)
                    drawing_stack.controls.extend(dot(item) for item in new_points)
                    drawing_stack.update()

                def clear_drawing(e):
                    note_strokes.clear()
                    active_stroke[0] = None
                    del drawing_stack.controls[1:]
                    drawing_stack.update()

                def delete_note(e):
                    try:
                        if note:
                            store.delete_item("notes", note["id"], user["id"])
                        else:
                            new_note_pending[0] = False
                    except (OSError, sqlite3.Error) as error:
                        fail(f"メモを削除できませんでした: {error}")
                        return
                    render_all("メモを削除しました")

                def save_note(e):
                    payload = {"text": memo.value or "", "strokes": note_strokes}
                    try:
                        if note:
                            store.update_item(
                                "notes", note["id"], payload, user["id"]
                            )
                        else:
                            store.add_item("notes", payload, owner_id=user["id"])
                    except (OSError, sqlite3.Error, ValueError) as error:
                        fail(f"メモを保存できませんでした: {error}")
                        return
                    new_note_pending[0] = False
                    render_all("メモを保存しました")

                return ft.Container(
                    content=ft.Column([
                        ft.Text(f"メモ {index + 1}", size=14, color=INK),
                        memo,
                        ft.Text("ペンで書く・描く", size=14, color=INK),
                        ft.Container(
                            content=ft.GestureDetector(
                                content=drawing_stack,
                                width=canvas_width,
                                height=canvas_height,
                                on_pan_start=lambda e: add_drawing_point(e, start=True),
                                on_pan_update=add_drawing_point,
                                on_pan_end=lambda e: active_stroke.__setitem__(0, None),
                                data=f"student-note-canvas:{note_key}",
                            ),
                            width=canvas_width,
                            height=canvas_height,
                            border=ft.Border.all(1, "#D8DEDA"),
                            border_radius=6,
                            clip_behavior=ft.ClipBehavior.HARD_EDGE,
                        ),
                        ft.Row([
                            ft.OutlinedButton(
                                "手書きを消去",
                                icon=ft.Icons.DELETE_OUTLINE,
                                on_click=clear_drawing,
                                data=f"student-note-clear:{note_key}",
                            ),
                            ft.Button(
                                "メモを保存",
                                icon=ft.Icons.SAVE_OUTLINED,
                                bgcolor=GREEN,
                                color="white",
                                on_click=save_note,
                                data=f"student-note-save:{note_key}",
                            ),
                            ft.OutlinedButton(
                                "メモを削除",
                                icon=ft.Icons.DELETE_OUTLINE,
                                on_click=delete_note,
                                data=f"student-note-delete:{note_key}",
                            ),
                        ], spacing=8, wrap=True),
                    ], spacing=8),
                    padding=12,
                    bgcolor=GREEN_LIGHT,
                    border_radius=6,
                )

            notes_to_show = list(saved_notes)
            if new_note_pending[0]:
                notes_to_show.insert(0, None)
            note_controls = [
                note_editor(note, index)
                for index, note in enumerate(notes_to_show)
            ]

            def add_note(e):
                if not new_note_pending[0]:
                    new_note_pending[0] = True
                    render_all()

            note_panel = panel(
                "メモ",
                "文字入力と手書きに対応しています。",
                [
                    ft.Button(
                        "メモ欄を追加",
                        icon=ft.Icons.ADD,
                        bgcolor=GREEN,
                        color="white",
                        disabled=new_note_pending[0],
                        on_click=add_note,
                        data="student-note-add",
                    ),
                    *note_controls,
                    *(
                        []
                        if note_controls
                        else [
                            ft.Text(
                                "メモ欄を追加して、文字や手書きで記録できます。",
                                color=MUTED,
                                size=13,
                            )
                        ]
                    ),
                ],
            )
            return ft.Column([note_panel], spacing=14)

        def home_view():
            today = datetime.now().date()
            exception = next(
                (item for item in store.list_timetable_exceptions()
                 if item["date"] == today.isoformat()),
                None,
            )
            if exception:
                weekday = today.strftime("%Y-%m-%d")
                if exception["kind"] == "holiday":
                    class_rows = [ft.Text(exception["title"], color=MUTED, size=13)]
                else:
                    class_rows = [
                        row("timetable", item, f"{item['period']}時限  {item['time']}",
                            f"{item['subject']} ・ {item.get('teacher') or '担当未設定'}")
                        for item in exception["lessons"]
                    ] or [ft.Text("特別日課の授業は登録されていません。", color=MUTED, size=13)]
            else:
                weekday_index = today.weekday()
                weekday = WEEKDAY_OPTIONS[weekday_index] if weekday_index < len(WEEKDAY_OPTIONS) else None
                lessons = (
                    store.published_timetable_for_day(weekday)["lessons"]
                    if user["role"] == "student" and weekday
                    else store.list_items("timetable")
                )
                classes = [item for item in lessons
                           if weekday and item.get("day") == weekday
                           and (
                               item.get("class_id") is None
                               or user["role"] != "student"
                               or item.get("class_id") == user["class_id"]
                           )]
                if user["role"] == "student" and user["class_id"] is not None:
                    class_lessons = [
                        item for item in classes
                        if item.get("class_id") == user["class_id"]
                    ]
                    if class_lessons:
                        classes = class_lessons
                classes.sort(key=lambda item: (
                    not item.get("period", "").isdigit(),
                    int(item["period"]) if item.get("period", "").isdigit()
                    else item.get("period", ""),
                ))
                class_rows = [
                    row("timetable", item, f"{item.get('period', '')}時限  {item['time']}",
                        f"{item['subject']} ・ {item.get('teacher') or '担当未設定'}")
                    for item in classes
                ]
                weekday = f"{weekday}曜日" if weekday else "土・日曜日"
                if not class_rows:
                    class_rows = [ft.Text("今日の時間割は登録されていません。",
                                          color=MUTED, size=13)]
            tests = sorted(store.list_items("tests"), key=lambda item: item.get("date", ""))[:5]
            test_rows = [row("tests", item, f"{item['date']}  {item['subject']}",
                             item.get("detail", "")) for item in tests]
            schedule_subtitle = (
                f"{weekday}の特別日課" if exception and exception["kind"] == "schedule"
                else f"{weekday}の休校・授業なし" if exception
                else f"{weekday}の授業"
            )
            return ft.Column([
                panel("今日の時間割", schedule_subtitle, [
                    ft.Column(class_rows, spacing=0)]),
                panel("テスト予定", "試験日が近い順に表示しています", [
                    ft.Column(test_rows or [ft.Text("テスト予定は登録されていません。",
                                                    color=MUTED, size=13)], spacing=0)]),
            ], spacing=14)

        def timetable_view():
            can_edit = user["role"] == "teacher"
            controls = []

            def publish_timetable():
                try:
                    store.publish_timetable(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
                except (OSError, sqlite3.Error, ValueError) as error:
                    fail(f"時間割を配信できませんでした: {error}")
                    return
                render_all("時間割を生徒へ配信しました")

            if can_edit:
                weekly_lessons = store.list_items("timetable")
                periods = WEEKDAY_OPTIONS
                class_scopes = [{"id": None, "name": "全クラス共通"}] + store.list_classes()
                selected_key = selected_timetable_class[0]
                if selected_key != "common" and selected_key not in [
                    str(class_scope["id"]) for class_scope in class_scopes
                    if class_scope["id"] is not None
                ]:
                    selected_key = "common"
                    selected_timetable_class[0] = selected_key
                selected_scopes = [
                    class_scope for class_scope in class_scopes
                    if (selected_key == "common" and class_scope["id"] is None)
                    or (selected_key != "common"
                        and str(class_scope["id"]) == selected_key)
                ]
                class_buttons = []
                for class_scope in class_scopes:
                    scope_key = "common" if class_scope["id"] is None else str(class_scope["id"])
                    class_buttons.append(ft.Button(
                        class_scope["name"],
                        bgcolor=GREEN if selected_key == scope_key else WHITE,
                        color="white" if selected_key == scope_key else INK,
                        on_click=lambda e, key=scope_key: (
                            selected_timetable_class.__setitem__(0, key),
                            render_all(),
                        )[1],
                    ))
                controls.append(panel(
                    "クラスを選択",
                    "表示するクラスを選ぶと、そのクラスの時間割表が開きます。",
                    [ft.Row(class_buttons, wrap=True, spacing=8)],
                ))

                for class_scope in selected_scopes:
                    class_id = class_scope["id"]
                    existing_lessons = {
                        (str(item.get("day", "")), str(item.get("slot", "")),
                         str(item.get("period", ""))): item
                        for item in weekly_lessons
                        if item.get("class_id") == class_id
                    }
                    schedule_cells = {}
                    slot_rows = (
                        tuple(f"1-{number}" for number in range(1, 8))
                        + tuple(f"2-{number}" for number in range(1, 8))
                        + tuple(f"3-{number}" for number in range(1, 7))
                    )
                    header_controls = [ft.Container(
                        width=60, height=30, bgcolor=GREEN_LIGHT,
                        border=ft.Border.all(1, "#202020"),
                    )]
                    for period in range(1, 8):
                        header_controls.append(ft.Container(
                            content=ft.Text(f"{period}限目", size=13, weight=ft.FontWeight.BOLD),
                            width=150, height=30, alignment=ft.Alignment(0, 0),
                            bgcolor=GREEN_LIGHT, padding=5,
                            border=ft.Border.all(1, "#202020"),
                        ))
                    schedule_rows = [
                        ft.Row(header_controls, spacing=0,
                               vertical_alignment=ft.CrossAxisAlignment.START)
                    ]
                    for slot in slot_rows:
                        schedule_row = [ft.Container(
                            content=ft.Text(slot, size=12, weight=ft.FontWeight.BOLD),
                            width=60, height=68, alignment=ft.Alignment(0, 0),
                            padding=5, border=ft.Border.all(1, "#202020"),
                        )]
                        selected_weekday = selected_timetable_day[0]
                        for period in range(1, 8):
                            item = existing_lessons.get(
                                (selected_weekday, slot, str(period)), {}
                            )
                            subject = ft.TextField(
                                value=item.get("subject", ""), hint_text="科目",
                                border=ft.InputBorder.NONE, text_size=12,
                                text_align=ft.TextAlign.CENTER, multiline=True,
                                height=34, content_padding=ft.Padding.only(top=2, bottom=0, left=2, right=2),
                            )
                            teacher = ft.TextField(
                                value=item.get("teacher", ""), hint_text="担当名",
                                border=ft.InputBorder.NONE, text_size=10,
                                text_align=ft.TextAlign.CENTER, multiline=True,
                                height=28, content_padding=ft.Padding.only(top=0, bottom=2, left=2, right=2),
                            )
                            schedule_cells[(slot, period)] = (subject, teacher)
                            schedule_row.append(ft.Container(
                                content=ft.Column(
                                    [subject, ft.Divider(height=1, thickness=1, color="#C9C9C0"), teacher],
                                    spacing=0,
                                ),
                                width=150, height=68,
                                padding=2, border=ft.Border.all(1, "#202020"),
                            ))
                        schedule_rows.append(ft.Row(
                            schedule_row, spacing=0,
                            vertical_alignment=ft.CrossAxisAlignment.START))

                    def save_weekday_schedule(e, scope_id=class_id,
                                              cells=schedule_cells,
                                              existing=existing_lessons):
                        try:
                            selected_weekday = selected_timetable_day[0]
                            for (slot, period), (subject, teacher) in cells.items():
                                subject_name = (subject.value or "").strip()
                                teacher_name = (teacher.value or "").strip()
                                current = existing.get((selected_weekday, slot, str(period)))
                                if not subject_name:
                                    if current:
                                        store.delete_item("timetable", current["id"])
                                    continue
                                payload = {
                                    "day": selected_weekday, "period": str(period),
                                    "slot": slot,
                                    "time": "",
                                    "subject": subject_name, "teacher": teacher_name,
                                }
                                if scope_id is not None:
                                    payload["class_id"] = scope_id
                                if current:
                                    store.update_item("timetable", current["id"], payload)
                                else:
                                    store.add_item("timetable", payload)
                        except (OSError, sqlite3.Error, ValueError) as error:
                            fail(f"時間割を保存できませんでした: {error}")
                            return
                        render_all("通常時間割を登録・更新しました")

                    controls.append(panel(
                        f"{class_scope['name']}の時間割を配置",
                        "月・火・水・木・金の時間割は毎週同じ曜日に繰り返します。各マスに科目と担当教師を入力し、一括保存してください。",
                        [
                            ft.Row([
                                ft.Button(
                                    f"{weekday}曜",
                                    bgcolor=GREEN if selected_timetable_day[0] == weekday else WHITE,
                                    color="white" if selected_timetable_day[0] == weekday else INK,
                                    on_click=lambda e, value=weekday: (
                                        selected_timetable_day.__setitem__(0, value),
                                        render_all(),
                                    )[1],
                                )
                                for weekday in WEEKDAY_OPTIONS
                            ], wrap=True, spacing=8),
                            ft.Container(
                                content=ft.Column(schedule_rows, spacing=0, scroll=ft.ScrollMode.AUTO),
                                width=1110,
                                height=1450,
                            ),
                            ft.Button(
                                f"{class_scope['name']}を保存",
                                bgcolor=GREEN, color="white",
                                on_click=save_weekday_schedule,
                            ),
                            ft.Row([
                                ft.Text(
                                    f"最終配信: {store.timetable_published_at() or '未配信'}",
                                    size=12,
                                    color=MUTED,
                                ),
                                ft.Button(
                                    "時間割を生徒へ配信",
                                    bgcolor=GREEN,
                                    color="white",
                                    on_click=lambda e: publish_timetable(),
                                ),
                            ], wrap=True, spacing=8),
                        ],
                    ))

            weekly_lessons = store.list_items("timetable")
            weekly_lessons.sort(key=lambda item: (
                WEEKDAY_OPTIONS.index(item["day"]) if item.get("day") in WEEKDAY_OPTIONS else 99,
                not item.get("period", "").isdigit(),
                int(item["period"]) if item.get("period", "").isdigit()
                else item.get("period", ""),
            ))
            if can_edit:
                weekly_rows = [
                    row("timetable", item,
                        f"{item.get('day', '')}曜日  {item.get('period', '')}時限  {item['time']}",
                        f"{item['subject']} ・ {item.get('teacher') or '担当未設定'}",
                        editable=True,
                    )
                    for item in weekly_lessons
                ]
                controls.append(panel("曜日ごとの通常時間割", "登録済みの通常授業一覧です。", [
                    ft.Column(weekly_rows or [
                        ft.Text("通常時間割はまだ登録されていません。", color=MUTED, size=13)
                    ], spacing=0),
                ]))
            else:
                slot_rows = (
                    tuple(f"1-{number}" for number in range(1, 8))
                    + tuple(f"2-{number}" for number in range(1, 8))
                    + tuple(f"3-{number}" for number in range(1, 7))
                )
                header = [ft.Container(
                    width=60, height=30,
                    bgcolor=GREEN_LIGHT, border=ft.Border.all(1, "#202020"),
                )]
                for period in range(1, 8):
                    header.append(ft.Container(
                        content=ft.Text(f"{period}限目", size=13, weight=ft.FontWeight.BOLD),
                        width=150, height=30, alignment=ft.Alignment(0, 0),
                        bgcolor=GREEN_LIGHT, padding=5,
                        border=ft.Border.all(1, "#202020"),
                    ))
                selected_day = selected_timetable_day[0]
                day_publication = store.published_timetable_for_day(selected_day)
                class_lessons = [
                    item for item in day_publication["lessons"]
                    if item.get("class_id") is not None
                    and str(item.get("class_id")) == str(user.get("class_id"))
                ]
                common_lessons = [
                    item for item in day_publication["lessons"]
                    if item.get("class_id") is None
                ]
                table_rows = [ft.Row(header, spacing=0)]
                for slot in slot_rows:
                    cells = [ft.Container(
                        content=ft.Text(slot, size=12, weight=ft.FontWeight.BOLD),
                        width=60, height=68, alignment=ft.Alignment(0, 0),
                        padding=5, border=ft.Border.all(1, "#202020"),
                    )]
                    for period in range(1, 8):
                        lesson = next((
                            item for item in class_lessons
                            if str(item.get("day", "")) == str(selected_day)
                            and item.get("slot", "") == slot
                            and str(item.get("period", "")) == str(period)
                        ), None)
                        if lesson is None:
                            lesson = next((
                                item for item in common_lessons
                                if str(item.get("day", "")) == str(selected_day)
                                and item.get("slot", "") == slot
                                and str(item.get("period", "")) == str(period)
                            ), None)
                        subject = lesson.get("subject", "") if lesson else ""
                        teacher = lesson.get("teacher", "") if lesson else ""
                        cells.append(ft.Container(
                            content=ft.Column([
                                ft.Container(
                                    content=ft.Text(subject, size=12, text_align=ft.TextAlign.CENTER),
                                    width=146,
                                    height=33,
                                    alignment=ft.Alignment(0, 0),
                                ),
                                ft.Divider(height=1, thickness=1, color="#C9C9C0"),
                                ft.Container(
                                    content=ft.Text(teacher, size=10, text_align=ft.TextAlign.CENTER),
                                    width=146,
                                    height=27,
                                    alignment=ft.Alignment(0, 0),
                                ),
                            ], spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                            width=150, height=68, alignment=ft.Alignment(0, 0),
                            padding=2, border=ft.Border.all(1, "#202020"),
                        ))
                    table_rows.append(ft.Row(cells, spacing=0))
                day_buttons = [
                    ft.Button(
                        f"{weekday}曜",
                        bgcolor=GREEN if selected_day == weekday else WHITE,
                        color="white" if selected_day == weekday else INK,
                        on_click=lambda e, value=weekday: (
                            selected_timetable_day.__setitem__(0, value),
                            render_all(),
                        )[1],
                    )
                    for weekday in WEEKDAY_OPTIONS
                ]
                controls.append(panel("週間時間割", "曜日を選択して時間割を確認できます。", [
                    ft.Row(day_buttons, wrap=True, spacing=8),
                    ft.Text(
                        f"この曜日の配信: {day_publication['published_at'] or '未配信'}"
                        if day_publication["published_at"]
                        else "この曜日はまだ未配信です。月曜は金曜15時、火曜は水曜15時、"
                             "水曜・金曜は木曜15時に自動配信されます。",
                        size=12,
                        color=MUTED,
                    ),
                    ft.Row([
                        ft.Text(
                            f"最終配信: {store.timetable_published_at() or 'まだ配信されていません'}",
                            size=12,
                            color=MUTED,
                        ),
                        ft.Button("最新の時間割を更新", bgcolor=GREEN, color="white",
                                  on_click=lambda e: render_all("最新の時間割を表示しました")),
                    ], wrap=True, spacing=8),
                    ft.Container(
                        content=ft.Column(table_rows, spacing=0, scroll=ft.ScrollMode.AUTO),
                        width=1110, height=1450,
                    ),
                ]))

            exceptions = store.list_timetable_exceptions()
            if can_edit:
                exception_date = text_field("日付", "YYYY-MM-DD")
                kind = ft.Dropdown(
                    label="日課の種類",
                    options=[
                        ft.dropdown.Option("schedule", "特別日課"),
                        ft.dropdown.Option("holiday", "休校・授業なし"),
                    ],
                    value="schedule",
                    width=170,
                    data="timetable-exception-kind",
                )
                exception_title = text_field("日課の内容・理由", "例 短縮授業、文化祭")
                exception_date.data = "timetable-exception-date"
                exception_title.data = "timetable-exception-title"
                exception_period = text_field("時限", "例 1", expand=False, width=80)
                exception_time = text_field("時間", "例 09:00-09:40")
                exception_subject = text_field("授業内容・科目", "例 数学")
                exception_teacher = text_field("担当教師", "例 山田先生")
                exception_notice = ft.TextField(
                    label="生徒へのお知らせ",
                    hint_text="集合場所や持ち物などを入力",
                    multiline=True,
                    min_lines=3,
                    max_lines=6,
                    data="timetable-exception-notice",
                )
                selected_notice_images = []
                notice_image_previews = ft.Column(
                    spacing=6,
                    data="timetable-exception-image-previews",
                )

                def render_notice_image_previews():
                    notice_image_previews.controls = [
                        ft.Row([
                            ft.Image(
                                src=image["contents"],
                                width=72,
                                height=56,
                                fit=ft.BoxFit.CONTAIN,
                                border_radius=6,
                                semantics_label=image["name"],
                            ),
                            ft.Text(image["name"], size=12, color=INK, expand=True),
                            ft.TextButton(
                                "削除",
                                on_click=lambda e, image_index=index: (
                                    selected_notice_images.pop(image_index),
                                    render_notice_image_previews(),
                                ),
                            ),
                        ], spacing=8)
                        for index, image in enumerate(selected_notice_images)
                    ]
                    page.update()

                async def pick_exception_notice_images(e):
                    try:
                        files = await assignment_image_picker.pick_files(
                            dialog_title="特別日のお知らせに添付する写真を選択",
                            file_type=ft.FilePickerFileType.CUSTOM,
                            allowed_extensions=["png", "jpg", "jpeg", "gif", "webp"],
                            allow_multiple=True,
                            with_data=True,
                        )
                    except (OSError, ValueError) as error:
                        fail(f"写真を選択できませんでした: {error}")
                        return
                    if not files:
                        return
                    if len(selected_notice_images) + len(files) > MAX_ASSIGNMENT_IMAGES:
                        fail(f"写真は1件のお知らせにつき{MAX_ASSIGNMENT_IMAGES}枚までです。")
                        return

                    new_images = []
                    for file in files:
                        contents = file.bytes
                        if contents is None:
                            fail(f"{file.name}の写真データを読み込めませんでした。")
                            return
                        if len(contents) > MAX_ASSIGNMENT_IMAGE_SIZE:
                            fail(f"{file.name}は1枚あたり5MB以下にしてください。")
                            return
                        media_type = image_media_type(contents)
                        if media_type is None:
                            fail(f"{file.name}は対応していない画像形式です。")
                            return
                        new_images.append({
                            "name": file.name,
                            "media_type": media_type,
                            "contents": contents,
                        })
                    total_size = sum(
                        len(image["contents"])
                        for image in [*selected_notice_images, *new_images]
                    )
                    if total_size > MAX_ASSIGNMENT_IMAGES_SIZE:
                        fail("写真の合計サイズは10MB以下にしてください。")
                        return
                    selected_notice_images.extend(new_images)
                    render_notice_image_previews()

                exception_image_picker_button = ft.TextButton(
                    "写真をアップロード",
                    icon=ft.Icons.ADD_PHOTO_ALTERNATE_OUTLINED,
                    data="timetable-exception-image-picker",
                    on_click=pick_exception_notice_images,
                )

                def notice_attachments_for_date(selected_date):
                    if not selected_notice_images:
                        return None
                    existing = next(
                        (
                            item for item in exceptions
                            if item["date"] == selected_date
                        ),
                        {},
                    )
                    attachments = list(existing.get("attachments", []))
                    attachments.extend({
                        "name": image["name"],
                        "media_type": image["media_type"],
                        "data": base64.b64encode(image["contents"]).decode("ascii"),
                    } for image in selected_notice_images)
                    if len(attachments) > MAX_ASSIGNMENT_IMAGES:
                        raise ValueError(
                            f"写真は1件のお知らせにつき{MAX_ASSIGNMENT_IMAGES}枚までです。"
                        )
                    total_size = sum(
                        len(base64.b64decode(image["data"]))
                        for image in attachments
                    )
                    if total_size > MAX_ASSIGNMENT_IMAGES_SIZE:
                        raise ValueError("写真の合計サイズは10MB以下にしてください。")
                    return attachments

                def set_exception_fields(e):
                    is_holiday = kind.value == "holiday"
                    for control in (exception_period, exception_time,
                                    exception_subject, exception_teacher):
                        control.disabled = is_holiday
                    page.update()

                kind.on_select = set_exception_fields

                def save_exception_lesson(e):
                    selected_date = (exception_date.value or "").strip()
                    if not selected_date:
                        fail("日付を入力してください。")
                        return
                    if kind.value == "schedule" and (
                        not exception_period.value or not exception_period.value.strip()
                        or not exception_time.value or not exception_time.value.strip()
                        or not exception_subject.value or not exception_subject.value.strip()
                    ):
                        fail("特別日課は時限・時間・授業内容を入力してください。")
                        return
                    try:
                        lesson = None
                        if kind.value == "schedule":
                            lesson = {
                                "period": exception_period.value.strip(),
                                "time": exception_time.value.strip(),
                                "subject": exception_subject.value.strip(),
                                "teacher": (exception_teacher.value or "").strip(),
                            }
                        store.save_timetable_exception(
                            selected_date,
                            kind.value,
                            exception_title.value or "",
                            lesson=lesson,
                            notice=exception_notice.value or "",
                            attachments=notice_attachments_for_date(selected_date),
                        )
                    except ValueError as error:
                        fail(str(error))
                        return
                    except (OSError, sqlite3.Error) as error:
                        fail(f"特別日課を保存できませんでした: {error}")
                        return
                    render_all("特別日課を登録・更新しました")

                def save_exception_day(e):
                    try:
                        store.save_timetable_exception(
                            (exception_date.value or "").strip(),
                            kind.value,
                            exception_title.value or "",
                            notice=exception_notice.value or "",
                            attachments=notice_attachments_for_date(
                                (exception_date.value or "").strip()
                            ),
                        )
                    except ValueError as error:
                        fail(str(error))
                        return
                    except (OSError, sqlite3.Error) as error:
                        fail(f"日課を保存できませんでした: {error}")
                        return
                    render_all(
                        "休校・授業なしを登録しました"
                        if kind.value == "holiday" else "特別日を設定しました"
                    )

                exception_date_form = form(
                    [exception_date, kind, exception_title],
                    "日付・日課設定を保存",
                    save_exception_day,
                )
                exception_date_form.content.controls[-1].data = (
                    "timetable-exception-save"
                )
                flyer_paper = ft.Container(
                    content=ft.Column([
                        ft.Text(
                            "生徒向けお知らせちらし",
                            size=16,
                            color=INK,
                            weight=ft.FontWeight.W_600,
                        ),
                        ft.Text(
                            "お知らせ文を書き、写真や画像を添付できます。",
                            size=12,
                            color=MUTED,
                        ),
                        exception_notice,
                        ft.Row([
                            exception_image_picker_button,
                            ft.Text(
                                "画像は5枚まで、合計10MBまで",
                                size=12,
                                color=MUTED,
                            ),
                        ], wrap=True, spacing=8),
                        notice_image_previews,
                    ], spacing=10),
                    padding=18,
                    bgcolor=PAPER,
                    border=ft.Border.all(1, "#D8D1BF"),
                    border_radius=4,
                    data="timetable-exception-flyer-paper",
                )
                controls.append(panel(
                    "日付指定の特別日課・休校",
                    "特別日を登録すると通常時間割より優先されます。お知らせ文や写真も生徒に表示できます。",
                    [
                        exception_date_form,
                        form([exception_period, exception_time, exception_subject,
                              exception_teacher], "授業を登録・更新", save_exception_lesson),
                        flyer_paper,
                    ],
                ))

            exception_rows = []
            for exception in exceptions:
                if exception["kind"] == "holiday":
                    detail = exception["title"]
                    summary = "休校・授業なし"
                else:
                    summary = f"特別日課: {exception['title']}" if exception["title"] else "特別日課"
                    detail = " / ".join(
                        f"{lesson['period']}時限 {lesson['time']} {lesson['subject']} "
                        f"({lesson.get('teacher') or '担当未設定'})"
                        for lesson in exception["lessons"]
                    ) or "授業の登録なし"
                exception_rows.append(row(
                    "timetable_exceptions",
                    {"id": exception["date"]},
                    f"{exception['date']}  {summary}",
                    detail,
                    editable=can_edit,
                ))
                flyer_controls = []
                if exception.get("notice"):
                    flyer_controls.append(ft.Text(
                        exception["notice"],
                        size=13,
                        color=INK,
                    ))
                attachments = exception.get("attachments", [])
                if attachments:
                    flyer_controls.append(ft.Row([
                        ft.Image(
                            src=f"data:{image['media_type']};base64,{image['data']}",
                            width=240,
                            height=180,
                            fit=ft.BoxFit.CONTAIN,
                            border_radius=6,
                            semantics_label=image["name"],
                        )
                        for image in attachments
                    ], wrap=True, spacing=8))
                if flyer_controls:
                    exception_rows.append(ft.Container(
                        content=ft.Column([
                            ft.Text("お知らせ", size=12, color=MUTED),
                            *flyer_controls,
                        ], spacing=6),
                        padding=12,
                        bgcolor=GREEN_LIGHT,
                        border_radius=6,
                        data=f"timetable-exception-flyer:{exception['date']}",
                    ))
            controls.append(panel("登録済みの特別日課・休校", "登録した日付は通常時間割より優先されます。", [
                ft.Column(exception_rows or [
                    ft.Text("特別日課・休校はまだ登録されていません。", color=MUTED, size=13)
                ], spacing=0),
            ]))
            return ft.Column(controls, spacing=14)

        def reminders_view():
            return items_panel(
                "reminders", "時間指定通知",
                "好きな日付・時刻を指定できます。例: 前日の夜、当日7:00。登録した通知は生徒側に表示されます。",
            )

        def tests_view():
            return items_panel(
                "tests", "テスト管理",
                "学年を選び、教科ごとに試験日・開始時刻・範囲を入力できます。"
                "教科を追加して2・3年生の表も作成できます。配信したテストは生徒側に表示されます。"
                if user["role"] == "teacher"
                else "先生から配信されたテスト予定を確認できます。",
            )

        def assignments_view():
            return items_panel(
                "assignments", "課題・提出物管理", "提出期限を見える化します。",
            )

        def calendar_view():
            return items_panel(
                "calendar", "カレンダー・行事予定", "学校行事や予定を日付順に管理します。",
            )

        def class_management_view():
            class_name = text_field("クラス名", "例 1年A組")
            class_grade = ft.Dropdown(
                label="学年",
                options=[ft.dropdown.Option(grade) for grade in TEST_GRADES],
                width=150,
            )
            student_name = text_field("生徒ユーザー名", "ユーザー名")
            student_password = text_field("初期パスワード", "生徒に安全な方法で共有",
                                          password=True)
            class_dropdown = ft.Dropdown(
                label="所属クラス",
                options=[ft.dropdown.Option(str(row["id"]), row["name"])
                         for row in store.list_classes()],
                expand=True,
            )

            def add_class(e):
                if not class_grade.value:
                    fail("学年を選択してください。")
                    return
                try:
                    store.create_class(class_name.value or "", class_grade.value)
                except ValueError as error:
                    fail(str(error))
                except sqlite3.IntegrityError:
                    fail("同じ名前のクラスがすでにあります。")
                except (OSError, sqlite3.Error) as error:
                    fail(f"クラスを作成できませんでした: {error}")
                else:
                    render_all("クラスを作成しました")

            def add_student(e):
                if not class_dropdown.value:
                    fail("先にクラスを作成してください。")
                    return
                try:
                    store.create_student(student_name.value or "", student_password.value or "",
                                         int(class_dropdown.value))
                except ValueError as error:
                    fail(str(error))
                except sqlite3.IntegrityError:
                    fail("そのユーザー名はすでに使われています。")
                except (OSError, sqlite3.Error) as error:
                    fail(f"生徒アカウントを作成できませんでした: {error}")
                else:
                    render_all("生徒アカウントを作成しました")

            classes = store.list_classes()
            students = store.list_students()
            student_rows = [
                ft.Container(
                    content=ft.Row([
                        ft.Text(student["username"], expand=True, color=INK),
                        ft.Text(student["class_name"] or "クラス未設定", color=MUTED, size=12),
                    ]),
                    padding=ft.Padding.symmetric(vertical=9, horizontal=14),
                    border=ft.Border.only(bottom=ft.BorderSide(1, "#DEDFD5")),
                )
                for student in students
            ]
            return ft.Column([
                panel("クラス管理", "クラスごとに作成されるグループチャットに先生と所属生徒が参加します。", [
                    form([class_name, class_grade], "クラスを作成", add_class),
                    form([student_name, student_password, class_dropdown],
                         "生徒アカウントを作成", add_student),
                    ft.Column([
                        ft.Text(
                            f"クラス: {item['name']}（{item['grade'] or '学年未設定'}）",
                            color=INK,
                        )
                        for item in classes
                    ] or [ft.Text("クラスはまだありません。", color=MUTED, size=13)], spacing=4),
                ]),
                panel("生徒アカウント", "生徒はここで作成したアカウントでログインします。", [
                    ft.Column(student_rows or [ft.Text("生徒アカウントはまだありません。",
                                                      color=MUTED, size=13)], spacing=0)]),
            ], spacing=14)

        def chat_view():
            contacts = store.list_contacts(user)
            if not contacts:
                return panel("チャット", "個人チャットは先生と生徒の間で利用できます。", [
                    ft.Text("チャット相手またはクラスがまだありません。", color=MUTED, size=13)])
            for contact in contacts:
                if contact["conversation_id"] == selected_conversation[0]:
                    break
            else:
                selected_conversation[0] = contacts[0]["conversation_id"]
            selected_contact = next(
                contact for contact in contacts
                if contact["conversation_id"] == selected_conversation[0]
            )
            conversation_header = ft.Row([
                ft.Container(
                    content=ft.Icon(
                        ft.Icons.GROUP_OUTLINED
                        if selected_contact["conversation_id"].startswith("class:")
                        else ft.Icons.PERSON_OUTLINE,
                        color=GREEN,
                    ),
                    width=42,
                    height=42,
                    alignment=ft.Alignment(0.5, 0.5),
                    bgcolor=GREEN_LIGHT,
                    border_radius=21,
                ),
                ft.Column([
                    ft.Text(selected_contact["label"], size=17, color=INK,
                            weight=ft.FontWeight.W_600),
                    ft.Text("チャット", size=11, color=MUTED),
                ], spacing=2),
            ], spacing=10)
            message = ft.TextField(
                label="メッセージ",
                hint_text="メッセージを入力",
                expand=True,
                min_lines=1,
                max_lines=3,
                multiline=True,
                border_radius=18,
                border_color="#D4DED5",
                focused_border_color=GREEN,
                bgcolor=WHITE,
                content_padding=ft.Padding.only(left=16, right=16, top=12, bottom=12),
                text_size=14,
            )

            def send_button_label(conversation_id):
                contact = next(
                    contact for contact in contacts
                    if contact["conversation_id"] == conversation_id
                )
                recipient = contact["label"].split(": ", 1)[-1]
                return f"{recipient}へ送信"

            def messages_view():
                conversation_id = selected_conversation[0]
                if not store.can_access_conversation(user, conversation_id):
                    return [ft.Text("このチャットには参加できません。", color=MUTED, size=13)]
                entries = store.list_messages(conversation_id)
                if not entries:
                    return [ft.Text("メッセージはまだありません。", color=MUTED, size=13)]

                rows = []
                for entry in entries:
                    is_me = entry["sender"] == user["username"]
                    bubble = ft.Container(
                        content=ft.Column([
                            ft.Text(entry["body"], size=14, selectable=True,
                                    color="white" if is_me else INK,
                                    weight=ft.FontWeight.W_500,
                                    max_lines=10,
                                    overflow=ft.TextOverflow.VISIBLE),
                            ft.Text(
                                entry["created_at"],
                                size=10,
                                color=("#DBF5E5" if is_me else MUTED),
                                text_align=ft.TextAlign.RIGHT,
                            ),
                        ], tight=True, spacing=4),
                        padding=ft.Padding.only(left=14, top=10, right=14, bottom=8),
                        bgcolor=GREEN if is_me else WHITE,
                        border_radius=18,
                        shadow=ft.BoxShadow(
                            spread_radius=0,
                            blur_radius=6,
                            color="#DDE5DF",
                            offset=ft.Offset(0, 2),
                        ) if not is_me else None,
                        width=360,
                    )
                    row = ft.Row(
                        [
                            ft.Container(width=60 if not is_me else 0),
                            bubble,
                            ft.Container(width=60 if is_me else 0),
                        ],
                        alignment=ft.MainAxisAlignment.START if not is_me else ft.MainAxisAlignment.END,
                        spacing=0,
                    )
                    if is_me:
                        row.controls = [ft.Container(width=60), bubble]
                    else:
                        row.controls = [bubble, ft.Container(width=60)]
                    rows.append(row)
                return rows

            message_list = ft.Column(messages_view(), spacing=8, scroll=ft.ScrollMode.AUTO)
            send_button = ft.Button(
                send_button_label(selected_conversation[0]),
                bgcolor=GREEN,
                color="white",
                height=54,
                on_click=lambda e: None,
            )

            def send(e):
                try:
                    store.send_message(user, selected_conversation[0], message.value or "")
                except ValueError as error:
                    fail(str(error))
                    return
                except PermissionError as error:
                    fail(str(error))
                    return
                except (OSError, sqlite3.Error) as error:
                    fail(f"送信できませんでした: {error}")
                    return
                message.value = ""
                render_all("メッセージを送信しました")

            send_button.on_click = send
            message.on_submit = send

            return panel("チャット", "相手を選び、メッセージを入力して送信します。", [
                conversation_header,
                ft.Container(
                    content=message_list,
                    height=420,
                    padding=12,
                    bgcolor="#F3F4F0",
                    border_radius=12,
                    border=ft.Border.all(1, "#E2E7E0"),
                ),
                ft.Container(
                    content=ft.Row([
                        message,
                        ft.Container(
                            content=send_button,
                            alignment=ft.Alignment(0.5, 0.5),
                            width=150,
                        ),
                    ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.END),
                    padding=12,
                    bgcolor=GREEN_LIGHT,
                    border_radius=18,
                ),
            ])

        def render_all(message=None):
            teacher = user["role"] == "teacher"
            page._student_auto_refresh_active = not teacher
            page._teacher_auto_refresh_active = teacher
            if not auto_refresh_started[0]:
                auto_refresh_started[0] = True
                page._dashboard_auto_refresh_active = True

                def auto_refresh_dashboard():
                    while (
                        getattr(page, "_dashboard_auto_refresh_token", None)
                        is auto_refresh_token
                    ):
                        time.sleep(15)
                        if (
                            getattr(page, "_dashboard_auto_refresh_token", None)
                            is not auto_refresh_token
                        ):
                            break
                        if not page.controls:
                            continue
                        try:
                            page.run_thread(
                                lambda: render_all()
                                if getattr(page, "_dashboard_auto_refresh_token", None)
                                is auto_refresh_token else None
                            )
                        except Exception:
                            pass

                threading.Thread(target=auto_refresh_dashboard, daemon=True).start()

            teacher = user["role"] == "teacher"
            tab_labels = ["ホーム", "時間割", "通知", "テスト", "課題", "カレンダー", "チャット"]
            views = [home_view(), timetable_view(), reminders_view(), tests_view(),
                     assignments_view(), calendar_view(), chat_view()]
            if teacher:
                tab_labels.append("クラス管理")
                views.append(class_management_view())
            else:
                tab_labels.insert(1, "自分のタスク")
                views.insert(1, tasks_view())
            selected_index = min(selected_tab[0], len(tab_labels) - 1)

            def open_view(index):
                selected_tab[0] = index
                render_all()

            icon_by_label = {
                "ホーム": ft.Icons.HOME_OUTLINED,
                "時間割": ft.Icons.SCHEDULE_OUTLINED,
                "通知": ft.Icons.NOTIFICATIONS_OUTLINED,
                "テスト": ft.Icons.ASSIGNMENT_OUTLINED,
                "課題": ft.Icons.TASK_ALT,
                "カレンダー": ft.Icons.EVENT_OUTLINED,
                "チャット": ft.Icons.CHAT_OUTLINED,
                "クラス管理": ft.Icons.GROUP_OUTLINED,
                "自分のタスク": ft.Icons.TASK_ALT,
            }
            nav_texts = []
            nav_items = []
            for index, label in enumerate(tab_labels):
                nav_text = ft.Text(
                    label, size=13,
                    color=GREEN if index == selected_index else INK,
                    weight=ft.FontWeight.W_600 if index == selected_index else None,
                    no_wrap=True,
                )
                nav_texts.append(nav_text)
                nav_items.append(ft.Container(
                    content=ft.Row([
                        ft.Icon(
                            icon_by_label[label],
                            size=19,
                            color=GREEN if index == selected_index else MUTED,
                        ),
                        nav_text,
                    ], spacing=12),
                    padding=ft.Padding.symmetric(horizontal=12, vertical=10),
                    bgcolor="#E1EAE4" if index == selected_index else None,
                    border_radius=8,
                    ink=True,
                    tooltip=label,
                    data=f"dashboard-nav:{label}",
                    on_click=lambda e, view_index=index: open_view(view_index),
                ))

            contacts = store.list_contacts(user)
            chat_index = tab_labels.index("チャット")
            contact_items = []
            for contact in contacts:
                is_selected_contact = (
                    contact["conversation_id"] == selected_conversation[0]
                )
                is_group = contact["conversation_id"].startswith("class:")
                contact_items.append(ft.Container(
                    content=ft.Row([
                        ft.Icon(
                            ft.Icons.GROUP_OUTLINED if is_group else ft.Icons.PERSON_OUTLINE,
                            size=17,
                            color=GREEN if is_selected_contact else MUTED,
                        ),
                        ft.Text(
                            contact["label"],
                            size=12,
                            color=GREEN if is_selected_contact else INK,
                            weight=ft.FontWeight.W_600 if is_selected_contact else None,
                            no_wrap=True,
                            overflow=ft.TextOverflow.ELLIPSIS,
                        ),
                    ], spacing=9),
                    padding=ft.Padding.symmetric(horizontal=12, vertical=9),
                    bgcolor="#E1EAE4" if is_selected_contact else None,
                    border_radius=8,
                    ink=True,
                    tooltip=contact["label"],
                    data=f"dashboard-contact:{contact['conversation_id']}",
                    on_click=lambda e, conversation_id=contact["conversation_id"]: (
                        selected_conversation.__setitem__(0, conversation_id),
                        open_view(chat_index),
                    ),
                ))
            chat_heading = ft.Text(
                "チャット", size=11, color=MUTED, weight=ft.FontWeight.W_600
            )
            nav_heading = ft.Text(
                "ナビゲーション", size=11, color=MUTED,
                weight=ft.FontWeight.W_600,
            )
            chat_empty = ft.Text("会話はありません", size=11, color=MUTED)
            sidebar = ft.Container(
                content=ft.Column([
                    nav_heading,
                    *nav_items,
                    ft.Divider(height=12, color="#D8DEDA"),
                    chat_heading,
                    *(contact_items or [chat_empty]),
                ], spacing=4, scroll=ft.ScrollMode.AUTO, expand=True),
                width=240,
                padding=ft.Padding.only(left=12, right=12, top=18, bottom=12),
                bgcolor="#F4F6F4",
                border=ft.Border.only(right=ft.BorderSide(1, "#DDE2DE")),
                data="dashboard-sidebar",
            )
            sidebar_detail_controls = [
                nav_heading, chat_heading, *contact_items, chat_empty,
            ]

            header = ft.Container(
                content=ft.Row([
                    ft.Row([
                        ft.Container(
                            content=ft.Icon(ft.Icons.SCHOOL_OUTLINED, color="white", size=19),
                            width=34,
                            height=34,
                            alignment=ft.Alignment(0.5, 0.5),
                            bgcolor=GREEN,
                            border_radius=8,
                        ),
                        ft.Text(
                            "今日の段取り", size=16, color=INK,
                            weight=ft.FontWeight.W_600,
                        ),
                    ], spacing=10),
                    ft.Row([
                        ft.Text(
                            f"{user['username']}（{'先生' if teacher else '生徒'}）",
                            size=12, color=MUTED,
                        ),
                        ft.TextButton(
                            "ログアウト",
                            data="dashboard-logout",
                            on_click=lambda e: (
                                show_login() if require_login else show_role_picker()
                            ),
                        ),
                    ], spacing=8),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                padding=ft.Padding.symmetric(horizontal=20, vertical=10),
                bgcolor=WHITE,
                border=ft.Border.only(bottom=ft.BorderSide(1, "#DDE2DE")),
            )
            heading_controls = [
                ft.Text(
                    tab_labels[selected_index], size=26, color=INK,
                    weight=ft.FontWeight.W_600,
                ),
                ft.Text("予定・締切・共有を、ひとつの場所に。", size=13, color=MUTED),
            ]
            if user["role"] == "student":
                tomorrow = (datetime.now().date() + timedelta(days=1)).isoformat()
                due_notices = []
                student_classes = store.list_classes()
                for assignment in store.list_items("assignments"):
                    if (
                        assignment_visible_to_user(assignment, user, student_classes)
                        and
                        assignment.get("due") == tomorrow
                        and not store.assignment_submitted(assignment["id"], user["id"])
                    ):
                        due_notices.append(ft.Text(
                            f"{assignment.get('subject') or assignment.get('title', '')}: "
                            f"明日が提出日です（提出先: "
                            f"{assignment.get('destination') or assignment.get('detail', '')}）",
                            size=13,
                            color="#8F3B2E",
                        ))
                if due_notices:
                    heading_controls.append(ft.Container(
                        content=ft.Column([
                            ft.Text(
                                "未提出の課題があります",
                                size=14,
                                color="#8F3B2E",
                                weight=ft.FontWeight.W_600,
                            ),
                            *due_notices,
                        ], spacing=5),
                        padding=12,
                        bgcolor="#FFF1E8",
                        border=ft.Border.all(1, "#F1C7B8"),
                        border_radius=6,
                        data="dashboard-due-notices",
                    ))
            heading = ft.Column(heading_controls, spacing=4)
            active_view = ft.Container(
                content=ft.Column(
                    [views[selected_index]],
                    scroll=ft.ScrollMode.AUTO,
                    expand=True,
                ),
                data="dashboard-active-view",
                expand=True,
            )
            workspace = ft.Column([
                heading,
                active_view,
                status,
            ], spacing=16, expand=True)
            body = ft.Row([
                sidebar,
                ft.Container(
                    content=workspace,
                    padding=24,
                    expand=True,
                    bgcolor="#ECEFEC",
                ),
            ], spacing=0, expand=True)
            content = ft.Column([header, body], spacing=0, expand=True)
            page.controls.clear()
            page.add(ft.Container(
                content=content,
                expand=True,
                bgcolor="#ECEFEC",
            ))
            if message:
                status.value = message
            dashboard_layout[0] = (sidebar, nav_texts, sidebar_detail_controls)
            resize_page()
            page.update()

        render_all()

    def resize_page():
        page.padding = 0
        if page.controls:
            container = page.controls[0]
            if isinstance(container, ft.Container) and isinstance(container.content, ft.Column):
                container.width = max(320, page.width or 1200)
                container.alignment = ft.Alignment(0, -1)
                container.content.width = container.width
        if dashboard_layout[0]:
            sidebar, nav_texts, detail_controls = dashboard_layout[0]
            sidebar.width = max(160, round((page.width or 1200) / 3))
            for label in nav_texts:
                label.visible = True
            for control in detail_controls:
                control.visible = True

    if require_login:
        show_login()
    else:
        show_role_picker()
