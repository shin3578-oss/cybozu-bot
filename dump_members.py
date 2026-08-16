# -*- coding: utf-8 -*-
"""サイボウズのメンバー一覧から、氏名とメールアドレスを取り出す。

雇用契約アプリ（Googleログインで本人確認する）に登録するアドレスを集めるための調査。
サイボウズの認証情報はこのリポジトリのSecretsにしかないため、ここで実行する。

cybozu.com のユーザーAPIを直接叩く（画面操作より速く確実）。
  GET https://{サブドメイン}.cybozu.com/v1/users.json
  ヘッダ X-Cybozu-Authorization: base64(ログインID:パスワード)

読み取りのみ。サイボウズ側は一切変更しない。
氏名とメールアドレス以外の個人情報はログに出さない。
"""
import base64
import os
import re
import sys

import requests

CYBOZU_URL = os.environ["CYBOZU_URL"]
LOGIN_ID = os.environ["CYBOZU_LOGIN_ID"]
PASSWORD = os.environ["CYBOZU_PASSWORD"]

HOST = re.sub(r"https?://([^/]+).*", r"\1", CYBOZU_URL)
AUTH = base64.b64encode(f"{LOGIN_ID}:{PASSWORD}".encode()).decode()


def get(path, params=None):
    r = requests.get(f"https://{HOST}{path}",
                     headers={"X-Cybozu-Authorization": AUTH},
                     params=params or {}, timeout=60)
    return r


def main():
    print(f"接続先: {HOST}")

    r = get("/v1/users.json", {"size": 100})
    print("users.json:", r.status_code)
    if r.status_code != 200:
        print("本文（先頭200字）:", r.text[:200])
        print("\n→ ユーザーAPIが使えません。共通管理の権限が要る可能性があります。")
        sys.exit(0)

    users = r.json().get("users", [])
    print(f"\n=== メンバー {len(users)} 名 ===")
    print(f"{'氏名':<14} {'ログイン名':<22} メールアドレス")
    print("-" * 76)

    gmail, other, none = [], [], []
    for u in users:
        name = (u.get("name") or "").strip()
        code = (u.get("code") or "").strip()
        mail = (u.get("email") or "").strip()
        valid = "有効" if u.get("valid") else "停止中"
        print(f"{name:<14} {code:<22} {mail or '(未登録)'}  [{valid}]")
        if not u.get("valid"):
            continue
        if not mail:
            none.append(name)
        elif mail.lower().endswith(("@gmail.com", "@googlemail.com")):
            gmail.append((name, mail))
        else:
            other.append((name, mail))

    print(f"\n=== 仕分け（有効なメンバーのみ）===")
    print(f"Gmail（そのまま使える）      : {len(gmail)} 名")
    for n, m in gmail:
        print(f"    {n}\t{m}")
    print(f"Gmail以外（Googleログイン不可の可能性）: {len(other)} 名")
    for n, m in other:
        print(f"    {n}\t{m}")
    print(f"未登録                      : {len(none)} 名")
    for n in none:
        print(f"    {n}")


if __name__ == "__main__":
    main()
