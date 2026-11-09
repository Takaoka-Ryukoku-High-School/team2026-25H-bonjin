import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


DATABASE_FILE = Path.home() / ".daily_note.sqlite3"
LEGACY_FILE = Path.home() / ".daily_note_tasks.json"
PUBLIC_COLLECTIONS = ("timetable", "reminders", "tests", "assignments", "calendar")
WEEKDAYS = ("月", "火", "水", "木", "金")
TIMETABLE_DELIVERY_DAYS = {
    2: ("火",),
    3: ("水", "金"),
    4: ("月",),
}


class Store:
    def __init__(self, path=DATABASE_FILE):
        self.path = Path(path)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash BLOB NOT NULL,
                    password_salt BLOB NOT NULL,
                    role TEXT NOT NULL CHECK (role IN ('teacher', 'student')),
                    class_id INTEGER REFERENCES classes(id)
                );
                CREATE TABLE IF NOT EXISTS classes (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE
                );
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY,
                    collection TEXT NOT NULL,
                    owner_id INTEGER REFERENCES users(id),
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS items_owner_collection
                    ON items(owner_id, collection);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    sender_id INTEGER NOT NULL REFERENCES users(id),
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS messages_conversation
                    ON messages(conversation_id, id);
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS timetable_exceptions (
                    date TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );
                """
            )
        os.chmod(self.path, 0o600)
        self._migrate_legacy_data()
        self._migrate_test_publication_state()

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _password_digest(password, salt):
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)

    def _migrate_test_publication_state(self):
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, payload FROM items WHERE collection = 'tests'"
            ).fetchall()
            for row in rows:
                payload = json.loads(row["payload"])
                if "published" not in payload:
                    payload["published"] = True
                    connection.execute(
                        "UPDATE items SET payload = ? WHERE id = ?",
                        (json.dumps(payload, ensure_ascii=False), row["id"]),
                    )

    def create_user(self, username, password, role, class_id=None):
        username = username.strip()
        if not username or not password:
            raise ValueError("ユーザー名とパスワードを入力してください。")
        if len(password) < 8:
            raise ValueError("パスワードは8文字以上で入力してください。")
        if role not in ("teacher", "student"):
            raise ValueError("無効なアカウント種別です。")
        if role == "teacher" and class_id is not None:
            raise ValueError("先生アカウントにクラスは設定できません。")
        salt = secrets.token_bytes(16)
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO users (username, password_hash, password_salt, role, class_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (username, self._password_digest(password, salt), salt, role, class_id),
            )
            return cursor.lastrowid

    def authenticate(self, username, password):
        with self._connect() as connection:
            user = connection.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
                (username.strip(),),
            ).fetchone()
        if user is None:
            return None
        digest = self._password_digest(password, user["password_salt"])
        if not hmac.compare_digest(digest, user["password_hash"]):
            return None
        return {"id": user["id"], "username": user["username"], "role": user["role"],
                "class_id": user["class_id"]}

    def has_teacher(self):
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM users WHERE role = 'teacher' LIMIT 1"
            ).fetchone() is not None

    def get_development_user(self, role):
        if role not in ("teacher", "student"):
            raise ValueError("無効なアカウント種別です。")
        key = f"development_user_{role}"
        with self._connect() as connection:
            row = connection.execute(
                """SELECT users.id, users.username, users.role, users.class_id
                   FROM metadata JOIN users ON users.id = CAST(metadata.value AS INTEGER)
                   WHERE metadata.key = ?""",
                (key,),
            ).fetchone()
            if row is not None:
                return dict(row)

            class_id = None
            if role == "student":
                connection.execute(
                    "INSERT OR IGNORE INTO classes (name) VALUES ('開発用クラス')"
                )
                class_id = connection.execute(
                    "SELECT id FROM classes WHERE name = '開発用クラス' COLLATE NOCASE"
                ).fetchone()["id"]

            username = f"_daily_note_development_{role}"
            salt = secrets.token_bytes(16)
            cursor = connection.execute(
                """INSERT INTO users (username, password_hash, password_salt, role, class_id)
                   VALUES (?, ?, ?, ?, ?)""",
                (username, self._password_digest(secrets.token_urlsafe(32), salt),
                 salt, role, class_id),
            )
            user_id = cursor.lastrowid
            connection.execute(
                "INSERT INTO metadata (key, value) VALUES (?, ?)",
                (key, str(user_id)),
            )
            return {"id": user_id, "username": username, "role": role, "class_id": class_id}

    def create_class(self, name):
        name = name.strip()
        if not name:
            raise ValueError("クラス名を入力してください。")
        with self._connect() as connection:
            cursor = connection.execute("INSERT INTO classes (name) VALUES (?)", (name,))
            return cursor.lastrowid

    def list_classes(self):
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(
                "SELECT id, name FROM classes ORDER BY name"
            )]

    def create_student(self, username, password, class_id):
        with self._connect() as connection:
            if connection.execute(
                "SELECT 1 FROM classes WHERE id = ?", (class_id,)
            ).fetchone() is None:
                raise ValueError("選択したクラスが見つかりません。")
        return self.create_user(username, password, "student", class_id)

    def list_students(self):
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(
                """SELECT users.id, users.username, classes.name AS class_name
                   FROM users LEFT JOIN classes ON classes.id = users.class_id
                   WHERE users.role = 'student' ORDER BY users.username"""
            )]

    def list_items(self, collection, owner_id=None):
        if collection not in PUBLIC_COLLECTIONS and collection != "tasks":
            raise ValueError("無効なデータ種別です。")
        with self._connect() as connection:
            if collection == "tasks":
                rows = connection.execute(
                    "SELECT id, payload FROM items WHERE collection = ? AND owner_id = ? ORDER BY id DESC",
                    (collection, owner_id),
                )
            else:
                rows = connection.execute(
                    "SELECT id, payload FROM items WHERE collection = ? ORDER BY id",
                    (collection,),
                )
            result = []
            for row in rows:
                item = json.loads(row["payload"])
                item["id"] = str(row["id"])
                result.append(item)
            return result

    def add_item(self, collection, payload, owner_id=None):
        if collection not in PUBLIC_COLLECTIONS and collection != "tasks":
            raise ValueError("無効なデータ種別です。")
        if collection == "tasks" and owner_id is None:
            raise ValueError("タスクには所有者が必要です。")
        if collection != "tasks" and owner_id is not None:
            raise ValueError("共有情報に所有者は設定できません。")
        payload = dict(payload)
        if collection == "tests":
            payload.setdefault("published", False)
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO items (collection, owner_id, payload) VALUES (?, ?, ?)",
                (collection, owner_id, json.dumps(payload, ensure_ascii=False)),
            )
            return str(cursor.lastrowid)

    def publish_timetable(self, published_at, day=None, delivery_date=None):
        if day is not None and day not in WEEKDAYS:
            raise ValueError("無効な曜日です。")
        if (day is None) != (delivery_date is None):
            raise ValueError("自動配信には曜日と配信日が必要です。")

        with self._connect() as connection:
            delivery_key = None
            if delivery_date is not None:
                try:
                    datetime.strptime(delivery_date, "%Y-%m-%d")
                except ValueError as error:
                    raise ValueError("配信日は YYYY-MM-DD 形式で入力してください。") from error
                delivery_key = f"timetable_auto_delivery:{delivery_date}:{day}"
                if connection.execute(
                    "SELECT 1 FROM metadata WHERE key = ?", (delivery_key,)
                ).fetchone():
                    return False

            payloads = [
                json.loads(row["payload"])
                for row in connection.execute(
                    "SELECT payload FROM items WHERE collection = 'timetable' ORDER BY id"
                )
            ]
            if not payloads:
                raise ValueError("配信する時間割がありません。科目を入力して保存してください。")

            published_by_day_row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'published_timetable_by_day'"
            ).fetchone()
            if published_by_day_row:
                published_by_day = json.loads(published_by_day_row["value"])
            else:
                published_by_day = {}
                previous_snapshot = connection.execute(
                    "SELECT value FROM metadata WHERE key = 'published_timetable'"
                ).fetchone()
                previous_published_at = connection.execute(
                    "SELECT value FROM metadata WHERE key = 'timetable_published_at'"
                ).fetchone()
                if previous_snapshot:
                    previous_lessons = json.loads(previous_snapshot["value"])
                    previous_time = previous_published_at["value"] if previous_published_at else ""
                    for weekday in WEEKDAYS:
                        published_by_day[weekday] = {
                            "published_at": previous_time,
                            "lessons": [
                                item for item in previous_lessons
                                if item.get("day") == weekday
                            ],
                        }

            days_to_publish = (day,) if day is not None else WEEKDAYS
            for weekday in days_to_publish:
                published_by_day[weekday] = {
                    "published_at": published_at,
                    "lessons": [
                        item for item in payloads if item.get("day") == weekday
                    ],
                }

            connection.execute(
                """INSERT INTO metadata (key, value) VALUES ('timetable_published_at', ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (published_at,),
            )
            connection.execute(
                """INSERT INTO metadata (key, value) VALUES ('published_timetable', ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (json.dumps(payloads, ensure_ascii=False),),
            )
            connection.execute(
                """INSERT INTO metadata (key, value)
                   VALUES ('published_timetable_by_day', ?)
                   ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
                (json.dumps(published_by_day, ensure_ascii=False),),
            )
            if delivery_key is not None:
                connection.execute(
                    "INSERT INTO metadata (key, value) VALUES (?, ?)",
                    (delivery_key, published_at),
                )
            return True

    def publish_due_timetables(self, now=None):
        now = now or datetime.now()
        if (now.hour, now.minute) < (15, 0):
            return []

        days = TIMETABLE_DELIVERY_DAYS.get(now.weekday(), ())
        published = []
        for day in days:
            was_published = self.publish_timetable(
                now.strftime("%Y-%m-%d %H:%M:%S"),
                day=day,
                delivery_date=now.date().isoformat(),
            )
            if was_published:
                published.append(day)
        return published

    def timetable_published_at(self):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'timetable_published_at'"
            ).fetchone()
            return row["value"] if row else ""

    def published_timetable(self):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'published_timetable'"
            ).fetchone()
            return json.loads(row["value"]) if row else []

    def published_timetable_for_day(self, day):
        if day not in WEEKDAYS:
            raise ValueError("無効な曜日です。")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'published_timetable_by_day'"
            ).fetchone()
            if row:
                publication = json.loads(row["value"]).get(day, {})
                return {
                    "published_at": publication.get("published_at", ""),
                    "lessons": publication.get("lessons", []),
                }

            snapshot = connection.execute(
                "SELECT value FROM metadata WHERE key = 'published_timetable'"
            ).fetchone()
            published_at = connection.execute(
                "SELECT value FROM metadata WHERE key = 'timetable_published_at'"
            ).fetchone()
            lessons = json.loads(snapshot["value"]) if snapshot else []
            return {
                "published_at": published_at["value"] if published_at else "",
                "lessons": [item for item in lessons if item.get("day") == day],
            }

    def delete_item(self, collection, item_id, owner_id=None):
        if collection == "tasks":
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM items WHERE id = ? AND collection = ? AND owner_id = ?",
                    (item_id, collection, owner_id),
                )
        elif collection in PUBLIC_COLLECTIONS:
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM items WHERE id = ? AND collection = ?",
                    (item_id, collection),
                )

    def update_item(self, collection, item_id, payload, owner_id=None):
        if collection == "tasks":
            with self._connect() as connection:
                connection.execute(
                    "UPDATE items SET payload = ? WHERE id = ? AND collection = ? AND owner_id = ?",
                    (json.dumps(payload, ensure_ascii=False), item_id, collection, owner_id),
                )
            return
        if collection not in PUBLIC_COLLECTIONS:
            raise ValueError("このデータは更新できません。")
        with self._connect() as connection:
            if collection == "tests":
                existing = connection.execute(
                    "SELECT payload FROM items WHERE id = ? AND collection = ?",
                    (item_id, collection),
                ).fetchone()
                if existing is not None:
                    old_payload = json.loads(existing["payload"])
                    payload = dict(payload)
                    payload.setdefault("published", old_payload.get("published", False))
            connection.execute(
                "UPDATE items SET payload = ? WHERE id = ? AND collection = ?",
                (json.dumps(payload, ensure_ascii=False), item_id, collection),
            )

    def set_test_published(self, item_id, published):
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM items WHERE id = ? AND collection = 'tests'",
                (item_id,),
            ).fetchone()
            if row is None:
                return False
            payload = json.loads(row["payload"])
            payload["published"] = bool(published)
            connection.execute(
                "UPDATE items SET payload = ? WHERE id = ? AND collection = 'tests'",
                (json.dumps(payload, ensure_ascii=False), item_id),
            )
            return True

    def publish_all_tests(self):
        published_count = 0
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, payload FROM items WHERE collection = 'tests'"
            ).fetchall()
            for row in rows:
                payload = json.loads(row["payload"])
                if payload.get("published", False):
                    continue
                payload["published"] = True
                connection.execute(
                    "UPDATE items SET payload = ? WHERE id = ? AND collection = 'tests'",
                    (json.dumps(payload, ensure_ascii=False), row["id"]),
                )
                published_count += 1
        return published_count

    def list_timetable_exceptions(self):
        with self._connect() as connection:
            return [
                {"date": row["date"], **json.loads(row["payload"])}
                for row in connection.execute(
                    "SELECT date, payload FROM timetable_exceptions ORDER BY date"
                )
            ]

    def save_timetable_exception(self, exception_date, kind, title, lesson=None):
        try:
            datetime.strptime(exception_date, "%Y-%m-%d")
        except ValueError as error:
            raise ValueError("日付は YYYY-MM-DD 形式で入力してください。") from error
        if kind not in ("schedule", "holiday"):
            raise ValueError("無効な日課種別です。")
        title = title.strip()
        if kind == "holiday" and not title:
            raise ValueError("休校・授業なしの内容を入力してください。")

        with self._connect() as connection:
            existing = connection.execute(
                "SELECT payload FROM timetable_exceptions WHERE date = ?",
                (exception_date,),
            ).fetchone()
            payload = json.loads(existing["payload"]) if existing else {}
            lessons = payload.get("lessons", []) if payload.get("kind") == kind else []
            if kind == "holiday":
                lessons = []
            elif lesson is not None:
                period = lesson["period"].strip()
                if not period:
                    raise ValueError("時限を入力してください。")
                updated_lesson = {
                    "period": period,
                    "time": lesson["time"].strip(),
                    "subject": lesson["subject"].strip(),
                    "teacher": lesson["teacher"].strip(),
                }
                for index, existing_lesson in enumerate(lessons):
                    if existing_lesson.get("period") == period:
                        lessons[index] = updated_lesson
                        break
                else:
                    lessons.append(updated_lesson)
                lessons.sort(key=lambda item: (
                    not item["period"].isdigit(),
                    int(item["period"]) if item["period"].isdigit() else item["period"],
                ))
            payload = {"kind": kind, "title": title, "lessons": lessons}
            connection.execute(
                """INSERT INTO timetable_exceptions (date, payload) VALUES (?, ?)
                   ON CONFLICT(date) DO UPDATE SET payload = excluded.payload""",
                (exception_date, json.dumps(payload, ensure_ascii=False)),
            )

    def delete_timetable_exception(self, exception_date):
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM timetable_exceptions WHERE date = ?", (exception_date,)
            )

    @staticmethod
    def direct_conversation_id(first_user_id, second_user_id):
        return f"dm:{min(first_user_id, second_user_id)}:{max(first_user_id, second_user_id)}"

    def list_contacts(self, user):
        with self._connect() as connection:
            if user["role"] == "teacher":
                students = connection.execute(
                    "SELECT id, username FROM users WHERE role = 'student' ORDER BY username"
                )
                contacts = [{"id": row["id"], "label": f"個人: {row['username']}",
                             "conversation_id": self.direct_conversation_id(user["id"], row["id"])}
                            for row in students]
                groups = connection.execute("SELECT id, name FROM classes ORDER BY name")
                contacts.extend({"id": f"class:{row['id']}", "label": f"グループ: {row['name']}",
                                 "conversation_id": f"class:{row['id']}"}
                                for row in groups)
                return contacts

            teachers = connection.execute(
                "SELECT id, username FROM users WHERE role = 'teacher' ORDER BY username"
            )
            contacts = [{"id": row["id"], "label": f"個人: {row['username']}",
                         "conversation_id": self.direct_conversation_id(user["id"], row["id"])}
                        for row in teachers]
            if user["class_id"] is not None:
                class_row = connection.execute(
                    "SELECT id, name FROM classes WHERE id = ?", (user["class_id"],)
                ).fetchone()
                if class_row is not None:
                    contacts.append({"id": f"class:{class_row['id']}",
                                     "label": f"グループ: {class_row['name']}",
                                     "conversation_id": f"class:{class_row['id']}"})
            return contacts

    def can_access_conversation(self, user, conversation_id):
        if conversation_id.startswith("dm:"):
            try:
                participants = {int(part) for part in conversation_id.split(":")[1:]}
            except ValueError:
                return False
            if user["id"] not in participants or len(participants) != 2:
                return False
            with self._connect() as connection:
                roles = {row["role"] for row in connection.execute(
                    "SELECT role FROM users WHERE id IN (?, ?)", tuple(sorted(participants))
                )}
            return roles == {"teacher", "student"}
        if conversation_id.startswith("class:"):
            try:
                class_id = int(conversation_id.split(":", 1)[1])
            except ValueError:
                return False
            if user["role"] == "teacher":
                with self._connect() as connection:
                    return connection.execute(
                        "SELECT 1 FROM classes WHERE id = ?", (class_id,)
                    ).fetchone() is not None
            return user["class_id"] == class_id
        return False

    def list_messages(self, conversation_id):
        with self._connect() as connection:
            return [dict(row) for row in connection.execute(
                """SELECT messages.id, messages.sender_id, users.username AS sender,
                          messages.body, messages.created_at
                   FROM messages JOIN users ON users.id = messages.sender_id
                   WHERE conversation_id = ? ORDER BY messages.id""",
                (conversation_id,),
            )]

    def send_message(self, user, conversation_id, body):
        body = body.strip()
        if not body:
            raise ValueError("メッセージを入力してください。")
        if not self.can_access_conversation(user, conversation_id):
            raise PermissionError("このチャットには参加できません。")
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO messages (conversation_id, sender_id, body, created_at)
                   VALUES (?, ?, ?, ?)""",
                (conversation_id, user["id"], body, datetime.now().isoformat(timespec="minutes")),
            )

    def _migrate_legacy_data(self):
        with self._connect() as connection:
            marker = connection.execute(
                "INSERT OR IGNORE INTO metadata (key, value) VALUES ('legacy_imported', '1')"
            )
            if marker.rowcount == 0:
                return
            if LEGACY_FILE.exists():
                try:
                    legacy = json.loads(LEGACY_FILE.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    legacy = {}
                if isinstance(legacy, dict):
                    for collection in PUBLIC_COLLECTIONS:
                        values = legacy.get(collection, [])
                        if isinstance(values, list):
                            connection.executemany(
                                "INSERT INTO items (collection, owner_id, payload) VALUES (?, NULL, ?)",
                                [(collection, json.dumps(value, ensure_ascii=False))
                                 for value in values if isinstance(value, dict)],
                            )
