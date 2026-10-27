import sqlite3
from datetime import datetime

import flet as ft

from store import PUBLIC_COLLECTIONS, Store


GREEN = "#2E6654"
GREEN_LIGHT = "#E2EDE5"
PAPER = "#F6F5EF"
INK = "#202C2A"
MUTED = "#77807B"
WHITE = "#FFFEFA"
WEEKDAY_OPTIONS = ("月", "火", "水", "木", "金")


def text_field(label, hint, expand=True, width=None, password=False):
    return ft.TextField(
        label=label,
        hint_text=hint,
        expand=expand,
        width=width,
        password=password,
        can_reveal_password=password,
        border_radius=6,
        border_color="#D4DED5",
        focused_border_color=GREEN,
        bgcolor=WHITE,
        text_size=14,
    )


def main(page: ft.Page, require_login=False):
    store = Store()
    page.title = "今日の段取り | 学生ダッシュボード"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = PAPER
    page.padding = 24
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.scroll = ft.ScrollMode.AUTO
    page.on_resize = lambda e: resize_page()

    def show_role_picker():
        def enter_role(role):
            try:
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
        status = ft.Text(color=MUTED, size=12)
        selected_conversation = [None]
        selected_tab = [0]

        def refresh(message=None):
            if message:
                status.value = message
            page.update()

        def fail(message):
            status.value = message
            page.update()

        def row(collection, item, title, detail="", editable=False):
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
                reminder_title = text_field("通知内容", "例 レポート提出を確認")
                when = text_field("通知時刻", "YYYY-MM-DD HH:MM")
                inputs = [reminder_title, when]

                def add(e):
                    if reminder_title.value and reminder_title.value.strip() and when.value and when.value.strip():
                        add_item(collection, {"title": reminder_title.value.strip(),
                                              "when": when.value.strip()}, "通知を登録しました")

                title_display = lambda item: item["title"]
                detail_display = lambda item: f"通知時刻: {item['when']}"
            elif collection == "tests":
                subject = text_field("科目", "数学")
                date = text_field("試験日", "YYYY-MM-DD")
                detail = text_field("範囲・メモ", "教科書 p.10-30")
                inputs = [subject, date, detail]

                def add(e):
                    if subject.value and subject.value.strip() and date.value and date.value.strip():
                        add_item(collection, {"subject": subject.value.strip(),
                                              "date": date.value.strip(),
                                              "detail": (detail.value or "").strip()},
                                 "テストを登録しました")

                title_display = lambda item: f"{item['subject']}  {item['date']}"
                detail_display = lambda item: item.get("detail", "")
            elif collection == "assignments":
                assignment_title = text_field("課題名", "レポート・宿題")
                due = text_field("提出期限", "YYYY-MM-DD")
                detail = text_field("提出先・メモ", "提出方法など")
                inputs = [assignment_title, due, detail]

                def add(e):
                    if assignment_title.value and assignment_title.value.strip() and due.value and due.value.strip():
                        add_item(collection, {"title": assignment_title.value.strip(),
                                              "due": due.value.strip(),
                                              "detail": (detail.value or "").strip()},
                                 "課題を登録しました")

                title_display = lambda item: f"{item['title']}  {item['due']}"
                detail_display = lambda item: item.get("detail", "")
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

            can_edit = user["role"] == "teacher"
            if can_edit:
                fields = [form(inputs, "登録する", add)]
            else:
                fields = []
            items = store.list_items(collection)
            if collection == "calendar":
                items.sort(key=lambda item: item.get("date", ""))
            if collection == "tests":
                items.sort(key=lambda item: item.get("date", ""))
            rows = [
                row(collection, item, title_display(item), detail_display(item), editable=can_edit)
                for item in items
            ]
            fields.append(ft.Column(
                rows or [ft.Text("登録された情報はありません。", color=MUTED, size=13)],
                spacing=0,
            ))
            role_description = "先生が登録・編集できます。" if not can_edit else description
            return panel(title, role_description, fields)

        def tasks_view():
            task = text_field("やること", "次にやることは？")

            def add(e):
                if task.value and task.value.strip():
                    try:
                        store.add_item("tasks", {"text": task.value.strip(), "done": False},
                                       owner_id=user["id"])
                    except (OSError, sqlite3.Error) as error:
                        fail(f"保存できませんでした: {error}")
                        return
                    render_all("タスクを追加しました")

            rows = [row("tasks", item, item["text"], editable=True)
                    for item in store.list_items("tasks", user["id"])]
            return panel(
                "自分のタスク",
                "このタスクは自分のアカウントだけに保存されます。",
                [form([task], "追加する", add),
                 ft.Column(rows or [ft.Text("まずは、やることをひとつ書いてみましょう。",
                                             color=MUTED, size=13)], spacing=0)],
            )

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
                classes = [item for item in store.list_items("timetable")
                           if weekday and item.get("day") == weekday]
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
            if can_edit:
                day = ft.Dropdown(
                    label="曜日",
                    options=[ft.dropdown.Option(value) for value in WEEKDAY_OPTIONS],
                    width=110,
                )
                period = text_field("時限", "例 1", expand=False, width=80)
                time = text_field("時間", "例 09:00-10:30")
                subject = text_field("授業内容・科目", "例 数学")
                teacher = text_field("担当教師", "例 山田先生")

                def save_weekday_lesson(e):
                    if not day.value or not period.value or not period.value.strip() \
                            or not time.value or not time.value.strip() \
                            or not subject.value or not subject.value.strip():
                        fail("曜日・時限・時間・授業内容を入力してください。")
                        return
                    payload = {
                        "day": day.value,
                        "period": period.value.strip(),
                        "time": time.value.strip(),
                        "subject": subject.value.strip(),
                        "teacher": (teacher.value or "").strip(),
                    }
                    try:
                        existing = next(
                            (item for item in store.list_items("timetable")
                             if item.get("day") == payload["day"]
                             and item.get("period") == payload["period"]),
                            None,
                        )
                        if existing:
                            store.update_item("timetable", existing["id"], payload)
                        else:
                            store.add_item("timetable", payload)
                    except (OSError, sqlite3.Error, ValueError) as error:
                        fail(f"時間割を保存できませんでした: {error}")
                        return
                    render_all("通常時間割を登録・更新しました")

                controls.append(panel("通常時間割", "同じ曜日・時限を再登録すると、その授業内容・担当教師に更新します。", [
                    form([day, period, time, subject, teacher], "登録・更新", save_weekday_lesson),
                ]))

            weekly_lessons = store.list_items("timetable")
            weekly_lessons.sort(key=lambda item: (
                WEEKDAY_OPTIONS.index(item["day"]) if item.get("day") in WEEKDAY_OPTIONS else 99,
                not item.get("period", "").isdigit(),
                int(item["period"]) if item.get("period", "").isdigit()
                else item.get("period", ""),
            ))
            weekly_rows = [
                row("timetable", item,
                    f"{item.get('day', '')}曜日  {item.get('period', '')}時限  {item['time']}",
                    f"{item['subject']} ・ {item.get('teacher') or '担当未設定'}",
                    editable=can_edit,
                )
                for item in weekly_lessons
            ]
            controls.append(panel("曜日ごとの通常時間割", "全クラス共通の通常授業です。", [
                ft.Column(weekly_rows or [
                    ft.Text("通常時間割はまだ登録されていません。", color=MUTED, size=13)
                ], spacing=0),
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
                )
                exception_title = text_field("日課の内容・理由", "例 短縮授業、文化祭")
                exception_period = text_field("時限", "例 1", expand=False, width=80)
                exception_time = text_field("時間", "例 09:00-09:40")
                exception_subject = text_field("授業内容・科目", "例 数学")
                exception_teacher = text_field("担当教師", "例 山田先生")

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

                controls.append(panel(
                    "日付指定の特別日課・休校",
                    "特別日を登録すると、その日は通常時間割の代わりにこの日課を表示します。同じ日付・時限を再登録すると授業を更新し、別の時限を登録すると授業を追加します。",
                    [
                        form([exception_date, kind, exception_title],
                             "日付・日課設定を保存", save_exception_day),
                        form([exception_period, exception_time, exception_subject,
                              exception_teacher], "授業を登録・更新", save_exception_lesson),
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
            controls.append(panel("登録済みの特別日課・休校", "登録した日付は通常時間割より優先されます。", [
                ft.Column(exception_rows or [
                    ft.Text("特別日課・休校はまだ登録されていません。", color=MUTED, size=13)
                ], spacing=0),
            ]))
            return ft.Column(controls, spacing=14)

        def reminders_view():
            return items_panel(
                "reminders", "時間指定通知", "通知内容と時刻を登録します。",
            )

        def tests_view():
            return items_panel(
                "tests", "テスト管理", "試験日と範囲を登録して対策状況を管理します。",
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
                try:
                    store.create_class(class_name.value or "")
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
                    form([class_name], "クラスを作成", add_class),
                    form([student_name, student_password, class_dropdown],
                         "生徒アカウントを作成", add_student),
                    ft.Column([
                        ft.Text(f"クラス: {item['name']}", color=INK) for item in classes
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
            conversation = ft.Dropdown(
                label="チャット",
                options=[ft.dropdown.Option(contact["conversation_id"], contact["label"])
                         for contact in contacts],
                value=selected_conversation[0],
                on_select=lambda e: select_conversation(e.control.value),
            )
            message = text_field("メッセージ", "メッセージを入力")

            def messages_view():
                conversation_id = selected_conversation[0]
                if not store.can_access_conversation(user, conversation_id):
                    return [ft.Text("このチャットには参加できません。", color=MUTED, size=13)]
                entries = store.list_messages(conversation_id)
                return [
                    ft.Container(
                        content=ft.Column([
                            ft.Text(f"{entry['sender']}  ({entry['created_at']})",
                                    size=12, color=MUTED),
                            ft.Text(entry["body"], size=14, color=INK),
                        ], spacing=3),
                        padding=10,
                        border=ft.Border.only(bottom=ft.BorderSide(1, "#DEDFD5")),
                    )
                    for entry in entries
                ] or [ft.Text("メッセージはまだありません。", color=MUTED, size=13)]

            message_list = ft.Column(messages_view(), spacing=0)

            def select_conversation(value):
                if value and store.can_access_conversation(user, value):
                    selected_conversation[0] = value
                    message_list.controls = messages_view()
                    page.update()

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

            return panel("チャット", "先生と生徒の個人チャット、クラス別グループチャットです。", [
                conversation,
                form([message], "送信", send),
                message_list,
            ])

        def render_all(message=None):
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
            tab_views = ft.TabBarView(
                [ft.Column([view], scroll=ft.ScrollMode.AUTO) for view in views],
                expand=True,
            )
            tabs = ft.Tabs(
                content=ft.Column([
                    ft.TabBar(tabs=[ft.Tab(label=label) for label in tab_labels]),
                    tab_views,
                ], expand=True),
                length=len(tab_labels),
                selected_index=min(selected_tab[0], len(tab_labels) - 1),
                animation_duration=200,
                on_change=lambda e: selected_tab.__setitem__(0, e.control.selected_index),
                expand=True,
            )
            header = ft.Row([
                ft.Text("DAILY NOTE", size=12, color=GREEN, weight=ft.FontWeight.BOLD),
                ft.Row([
                    ft.Text(f"{user['username']}（{'先生' if teacher else '生徒'}）",
                            size=12, color=MUTED),
                    ft.TextButton("ログアウト", on_click=lambda e: (
                        show_login() if require_login else show_role_picker()
                    )),
                ], spacing=4),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
            heading = ft.Column([
                ft.Text("学生ダッシュボード", size=34, color=INK, weight=ft.FontWeight.W_600),
                ft.Text("予定・締切・共有を、ひとつの場所で。", size=13, color=MUTED),
            ], spacing=4)
            content = ft.Column([header, heading, tabs, status], width=700, spacing=22)
            page.controls.clear()
            page.add(ft.Container(
                content=content,
                width=700,
                padding=ft.Padding.only(top=18, bottom=32),
            ))
            if message:
                status.value = message
            resize_page()
            page.update()

        render_all()

    def resize_page():
        page.padding = 12 if (page.width or 748) < 520 else 24
        if page.controls:
            container = page.controls[0]
            if isinstance(container, ft.Container) and isinstance(container.content, ft.Column):
                container.width = min(700, max(272, (page.width or 748) - page.padding * 2))
                container.content.width = container.width

    if require_login:
        show_login()
    else:
        show_role_picker()
