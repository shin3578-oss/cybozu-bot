# -*- coding: utf-8 -*-
"""サイボウズのメンバー一覧から、氏名とメールアドレスを取り出す。

雇用契約アプリ（Googleログインで本人確認する）に登録するアドレスを集めるための調査。
サイボウズの認証情報はこのリポジトリのSecretsにしかないため、ここで実行する。

読み取りのみ。サイボウズ側は一切変更しない。
出力は氏名とメールアドレスだけに絞る（他の個人情報はログに出さない）。
"""
import os
import re
import time

from playwright.sync_api import sync_playwright

CYBOZU_URL = os.environ["CYBOZU_URL"]
LOGIN_ID = os.environ["CYBOZU_LOGIN_ID"]
PASSWORD = os.environ["CYBOZU_PASSWORD"]

MAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def login(page):
    page.goto(CYBOZU_URL)
    page.wait_for_load_state("networkidle")
    page.locator('input[name="username"], input[name="userid"], input[type="text"]').first.fill(LOGIN_ID)
    page.locator('input[name="password"], input[type="password"]').first.fill(PASSWORD)
    page.locator('button:has-text("ログイン"), input[value="ログイン"]').first.click()
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    print("ログイン完了")
    print("トップのURL:", page.url)


def try_paths(page):
    """メンバー名簿がありそうな画面を順に開いて、メールアドレスを拾う。

    サイボウズは製品（Office / Garoon / kintone）で画面構成が違うため、
    候補を順に当たって、取れたところで止める。
    """
    base = CYBOZU_URL.rstrip("/")
    base = re.sub(r"/(index\.html?|\?.*)$", "", base)

    candidates = [
        # サイボウズ Office のユーザー名簿
        f"{base}/?page=UserList",
        f"{base}/?page=AddressBook",
        # cybozu.com 共通管理（クラウド版）
        f"{base}/v1/admin/users",
        "https://" + re.sub(r"https?://([^/]+).*", r"\1", CYBOZU_URL) + "/v1/admin/users",
        # Garoon
        f"{base}/grn.exe/address/index",
    ]

    found = {}
    for url in candidates:
        try:
            page.goto(url, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=30000)
            time.sleep(2)
        except Exception as e:
            print(f"  {url} → 開けず（{type(e).__name__}）")
            continue

        text = page.content()
        mails = set(MAIL_RE.findall(text))
        # 画面の飾りで出てくるサイボウズ自身のアドレスは除く
        mails = {m for m in mails if "cybozu" not in m.lower()}
        print(f"  {url} → メールらしき文字列 {len(mails)} 件")
        if mails:
            found[url] = sorted(mails)
    return found


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        login(page)

        print("\n=== メンバー名簿を探します ===")
        found = try_paths(page)

        print("\n=== 結果 ===")
        if not found:
            print("メールアドレスは見つかりませんでした。")
            print("いま開ける画面の一覧を出します（次の手がかり用）:")
            page.goto(CYBOZU_URL)
            page.wait_for_load_state("networkidle")
            for a in page.query_selector_all("a")[:60]:
                t = (a.inner_text() or "").strip().replace("\n", " ")
                h = a.get_attribute("href") or ""
                if t:
                    print(f"  {t[:24]:<26} {h[:80]}")
        else:
            for url, mails in found.items():
                print(f"\n--- {url} ---")
                for m in mails:
                    print("  ", m)

        browser.close()


if __name__ == "__main__":
    main()
