# -*- coding: utf-8 -*-
"""サイボウズの契約人数（ライセンスの上限）と利用人数が揃っているか、利用者が今いるスタッフと揃っているかを確かめる（毎月末）。

- 契約人数: 共通管理（/admin/）の「契約状況」の表「ユーザー数」の上限と利用中（2026-10-26 院長「ここの数字と、
  利用しているメンバーの数の突合。ときどきメンバー数以上に契約人数が多い場合がある」）。APIが無いので画面から読む

- サイボウズ側: cybozu.com のユーザーAPIで「使用中（valid）」のユーザーを数える
- スタッフ側 : スタッフ名簿スプシ（今いる人だけが載る・卒業したら行を消す運用）の
               「正社員名簿」「パート」タブの氏名
- 名簿の外でサイボウズを使う人（院長・育休中の先生・社労士など）と、名簿にいてもサイボウズを
  使わない人（土曜アルバイト・清掃など）は、Secret CYBOZU_MEMBER_RULES（JSON）で持つ（2026-10-26 院長回答）。
  {"extra_users": [名簿の外の利用者], "no_account": [アカウントを作らない名簿の人]}
  変わる事実なのでコードに書かない。公開リポジトリなので氏名をファイルにも置かない
- 人数と顔ぶれを突き合わせ、結果を院長DMへ1通（揃っていても1行・ずれていれば誰がずれているか）

このリポジトリは公開＝実行ログを誰でも読めるので、氏名はログに出さない（人数だけ）。
氏名入りの結果は apotool（非公開）の lw_notify.yml 経由で院長DMへ送る。
試運転では ENC_PUBKEY を渡すと、結果を暗号化してログに出し、院長DMは送らない。

読み取りのみ。サイボウズ・名簿のどちらも書き換えない。
"""
import base64
import json
import os
import re
import sys
import urllib.request

import requests
from playwright.sync_api import sync_playwright
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

CYBOZU_URL = os.environ["CYBOZU_URL"]
LOGIN_ID = os.environ["CYBOZU_LOGIN_ID"]
PASSWORD = os.environ["CYBOZU_PASSWORD"]
SHEET_ID = os.environ["STAFF_MEIBO_SHEET_ID"]
DRIVE_TOKEN_JSON = os.environ["DRIVE_TOKEN_JSON"]
DISPATCH_PAT = os.environ.get("DISPATCH_PAT", "")
NO_NOTIFY = os.getenv("NO_NOTIFY", "").strip() in ("1", "true", "True")
ENC_PUBKEY = os.getenv("ENC_PUBKEY", "").strip()
RULES = json.loads(os.getenv("CYBOZU_MEMBER_RULES", "").strip() or "{}")

STAFF_TABS = ["正社員名簿", "パート"]
LW_BOT_ID = "12266491"


def log(msg):
    print(f"[サイボウズ人数チェック] {msg}", flush=True)


def norm(name):
    """表記ゆれを吸収した比較用の名前（空白・括弧書きの旧姓などを除く）"""
    name = re.sub(r"[（(].*?[）)]", "", name or "")
    return re.sub(r"\s|　", "", name)


def cybozu_users():
    host = re.sub(r"https?://([^/]+).*", r"\1", CYBOZU_URL)
    auth = base64.b64encode(f"{LOGIN_ID}:{PASSWORD}".encode()).decode()
    users, offset = [], 0
    while True:
        r = requests.get(f"https://{host}/v1/users.json",
                         headers={"X-Cybozu-Authorization": auth},
                         params={"size": 100, "offset": offset}, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"サイボウズのユーザー一覧を取れません（HTTP {r.status_code}）")
        page = r.json().get("users", [])
        users += page
        if len(page) < 100:
            return users
        offset += 100


def contract_counts():
    """共通管理の契約状況から（上限, 利用中）を読む。ログインは main.py の login を使う"""
    from main import login
    host = re.sub(r"https?://([^/]+).*", r"\1", CYBOZU_URL)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            login(page)
            page.goto(f"https://{host}/admin/")
            page.wait_for_load_state("networkidle")
            text = re.sub(r"\s+", " ", page.inner_text("body"))
        finally:
            browser.close()
    m = re.search(r"ユーザー数 (\d+) (\d+)", text)
    if not m:
        raise RuntimeError("契約状況の表（ユーザー数）が見つかりません")
    return int(m.group(2)), int(m.group(1))


def meibo_names():
    creds = Credentials.from_authorized_user_info(json.loads(DRIVE_TOKEN_JSON.lstrip("﻿")))
    creds.refresh(Request())
    names = []
    for tab in STAFF_TABS:
        r = requests.get(
            f"https://sheets.googleapis.com/v4/spreadsheets/{SHEET_ID}/values/{tab}!B2:B",
            headers={"Authorization": f"Bearer {creds.token}"}, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"スタッフ名簿（{tab}）を読めません（HTTP {r.status_code}）")
        names += [row[0].strip() for row in r.json().get("values", []) if row and row[0].strip()]
    return names


def build_message(users, staff, contract):
    active = [u for u in users if u.get("valid")]
    stopped = [u for u in users if not u.get("valid")]
    cy = {norm(u.get("name")): (u.get("name") or "").strip() for u in active}
    no_account = {norm(n) for n in RULES.get("no_account", [])}
    extra = {norm(n): n for n in RULES.get("extra_users", [])}

    # あるべき利用者 = 名簿（アカウントを作らない人は除く。作られていれば数える）＋ 名簿の外の利用者
    expected = {norm(n): n for n in staff if norm(n) not in no_account or norm(n) in cy}
    skipped = [n for n in staff if norm(n) in no_account and norm(n) not in cy]
    expected.update(extra)
    only_cy = [cy[k] for k in cy if k not in expected]
    only_ex = [expected[k] for k in expected if k not in cy]

    staff_ok = len(active) == len(expected) and not only_cy and not only_ex
    if isinstance(contract, Exception):
        contract_ok, c_txt = False, f"契約人数を読めませんでした（{contract}）"
    else:
        limit, in_use = contract
        contract_ok = limit == in_use == len(active)
        c_txt = f"契約 {limit}名分／利用中 {in_use}名"
    ok = staff_ok and contract_ok
    head = "✅" if ok else "🔴"
    lines = [f"{head}【サイボウズ利用人数チェック】{c_txt}／あるべき人数 {len(expected)}名",
             f"（あるべき人数＝スタッフ名簿 {len(staff)}名 − サイボウズを使わない {len(skipped)}名 ＋ 名簿の外の利用者 {len(extra)}名）"]
    if ok:
        lines.append("契約人数・利用人数・顔ぶれとも揃っています")
    if not isinstance(contract, Exception) and not contract_ok:
        if limit > in_use:
            lines.append(f"・契約が {limit - in_use}名分 余っています（使っていないライセンスの解約を検討）")
        if in_use != len(active):
            lines.append(f"・契約状況の利用中 {in_use}名と、ユーザー一覧の使用中 {len(active)}名が食い違っています")
    if not staff_ok:
        lines.append("・利用者がスタッフと揃っていません")
        if only_cy:
            lines.append("　サイボウズにいるが、名簿にいない（卒業後もアカウントが残っている可能性）:")
            lines += [f"　　{n}" for n in only_cy]
        if only_ex:
            lines.append("　名簿にいるが、サイボウズにいない（アカウント未作成・改姓など名前の表記違いの可能性）:")
            lines += [f"　　{n}" for n in only_ex]
    if stopped:
        lines.append(f"（参考）サイボウズで「停止中」のユーザー {len(stopped)}名は数えていません")
    return ok, len(active), len(expected), "\n".join(lines)


def encrypt_and_print(text):
    """試運転用: 結果を暗号化してログに出す（公開ログに氏名を出さないため）"""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    body = AESGCM(key).encrypt(nonce, text.encode("utf-8"), None)
    pub = load_pem_public_key(base64.b64decode(ENC_PUBKEY))
    wrapped = pub.encrypt(key, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                                            algorithm=hashes.SHA256(), label=None))
    blob = json.dumps({"k": base64.b64encode(wrapped).decode(), "n": base64.b64encode(nonce).decode(),
                       "c": base64.b64encode(body).decode()})
    print("ENC " + base64.b64encode(blob.encode()).decode())


def notify(message):
    body = json.dumps({"ref": "main", "inputs": {"message": message, "bot_id": LW_BOT_ID}}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/repos/shin3578-oss/apotool-automation/actions/workflows/lw_notify.yml/dispatches",
        data=body,
        headers={"Authorization": f"Bearer {DISPATCH_PAT}",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as res:
        if res.status not in (200, 204):
            raise RuntimeError(f"院長DMの起動に失敗: HTTP {res.status}")


def main():
    try:
        try:
            contract = contract_counts()
        except Exception as e:
            contract = e
        ok, n_cy, n_st, message = build_message(cybozu_users(), meibo_names(), contract)
    except Exception as e:
        # 取れなかったときも黙らない（無音で止まる事故の再発防止）
        ok, message = False, f"🔴【サイボウズ利用人数チェック】確認できませんでした: {e}"
        log(message)
    else:
        log(f"使用中 {n_cy}名／あるべき人数 {n_st}名／契約 {contract if isinstance(contract, Exception) else contract[0]} → {'一致' if ok else '不一致'}")

    if ENC_PUBKEY:
        encrypt_and_print(message)
    elif NO_NOTIFY:
        log("NO_NOTIFY のため院長DMは送らない")
    else:
        notify(message)
        log("院長DMへ送った")
    if "確認できませんでした" in message or "読めませんでした" in message:
        sys.exit(1)


if __name__ == "__main__":
    main()
