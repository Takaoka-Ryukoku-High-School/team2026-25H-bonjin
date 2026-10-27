import getpass
import sqlite3
import sys

import flet as ft

from dashboard import main
from store import Store


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
    ft.run(lambda page: main(page, require_login=args == ["--login"]),
           view=ft.AppView.WEB_BROWSER)
