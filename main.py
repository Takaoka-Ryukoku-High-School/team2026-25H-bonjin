import getpass
import logging
import sqlite3
import sys
import threading
import time
from datetime import datetime

import flet as ft

from dashboard import main
from store import Store


def run_timetable_scheduler():
    store = None
    while True:
        try:
            if store is None:
                store = Store()
            store.publish_due_timetables(datetime.now())
        except (OSError, sqlite3.Error, ValueError):
            logging.exception("時間割の自動配信に失敗しました。")
            store = None
        time.sleep(30)


def create_teacher():
    store = Store()
    username = input("先生ユーザー名: ").strip()
    password = getpass.getpass("パスワード: ")
    confirmation = getpass.getpass("パスワード（確認）: ")
    if password != confirmation:
        print("パスワードが一致しません。")
        return 1
    try:
        store.create_user(username, password, "teacher")
    except ValueError as error:
        print(error)
        return 1
    except (OSError, sqlite3.Error) as error:
        print(f"先生アカウントを作成できませんでした: {error}")
        return 1
    print("先生アカウントを作成しました。")
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["create-teacher"]:
        raise SystemExit(create_teacher())
    if args not in ([], ["--login"]):
        print("使い方: python main.py [--login | create-teacher]")
        raise SystemExit(2)
    threading.Thread(target=run_timetable_scheduler, daemon=True).start()
    ft.run(lambda page: main(page, require_login=args == ["--login"]),
           view=ft.AppView.WEB_BROWSER)
