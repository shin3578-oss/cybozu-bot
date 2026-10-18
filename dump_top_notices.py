# -*- coding: utf-8 -*-
"""サイボウズのトップページ「お知らせ」を読み取る（調査用・読み取りのみ）。

院長のKPIがトップページのお知らせに載っているため、その本文を取り出す。
サイボウズの認証情報はこのリポジトリのSecretsにしかないため、ここで実行する。

【大事】このリポジトリは公開＝Actionsのログは誰でも読める。
読み取った本文は、そのままログに出さず、院長のPCだけが持つ秘密鍵でしか開けない形に暗号化して出す
（公開鍵で包んだ AES キー＋AES-GCM）。ログに出るのは暗号文だけ。
サイボウズ側は一切変更しない（ログインして開くだけ）。
"""
import base64
import json
import os
import re
import time

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from playwright.sync_api import sync_playwright

CYBOZU_URL = os.environ["CYBOZU_URL"]
LOGIN_ID = os.environ["CYBOZU_LOGIN_ID"]
PASSWORD = os.environ["CYBOZU_PASSWORD"]

PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEAlT0bNLpw/EAZrzrJaAi0
yU/lGOur6UZOKAbYV/ROovaw9Ck8lrgAnKD1reqHTg4xlrj74ttln+9DAuHf+eq9
Pu4vqGAccTpVlX+A3SqaFBwAAnqgeaqvAek1oaP2S6IxlCutzgv09gsC80PP9cr0
YUZ0wOCbsLmCLTufMgYmbLqHKih5NGKDIW4U/B5CXwS0PgEESqZ/pqgL5bd9pxFI
xsN7fq3XcVFeBflwnMZit9AMiAjfT/GQZ5hHQBDBedH4z8HJ3SioIrfOQKUtJIe+
SX2b/cLMn3gomDYjD00gJXp5uBdoKNk97EzbNaaUDgt9kjuUZNiFR1Z3Q7IdjXNF
3VJEoBpK8g4BFr/9luI5XY2dD2BjiMHKtlxLj/NX9qd1AWxstGZUuIsdetyqnfAE
0PFpGZzCPplLqtPBiXYsdPnixEh7z8yzmCTz/aBeX0i/YiukHxWWaZXqnzWUYNy5
8cU0WR8lnEMR3NEWjk8XoOppcI9g95s8im4FbGYbKRDNAgMBAAE=
-----END PUBLIC KEY-----
"""

MAX_NOTICES = 15          # 詳細を開くお知らせの上限
MAX_CHARS = 6000          # 1件ごとの本文の上限


def encrypt_and_print(label, text):
    """text を暗号化して、ログに出す。復号できるのは秘密鍵を持つ人だけ。"""
    key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    body = AESGCM(key).encrypt(nonce, text.encode("utf-8"), None)
    pub = load_pem_public_key(PUBLIC_KEY_PEM)
    wrapped = pub.encrypt(key, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                                            algorithm=hashes.SHA256(), label=None))
    blob = json.dumps({"k": base64.b64encode(wrapped).decode(), "n": base64.b64encode(nonce).decode(),
                       "c": base64.b64encode(body).decode()})
    enc = base64.b64encode(blob.encode()).decode()
    print(f"ENC-BEGIN {label} {len(enc)}")
    for i in range(0, len(enc), 120):
        print("ENC " + enc[i:i + 120])
    print(f"ENC-END {label}")


def login(page):
    page.goto(CYBOZU_URL)
    page.wait_for_load_state("networkidle")
    page.locator('input[name="username"], input[name="userid"], input[type="text"]').first.fill(LOGIN_ID)
    page.locator('input[name="password"], input[type="password"]').first.fill(PASSWORD)
    page.locator('button:has-text("ログイン"), input[value="ログイン"]').first.click()
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    print("ログイン完了")


def main():
    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        login(page)
        page.goto(CYBOZU_URL)
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        print("トップページ:", page.title())

        out.append("===== トップページの本文 =====")
        out.append(page.inner_text("body")[:12000])

        # お知らせの詳細らしいリンクを集める（Cybozu Office: page=InformationView など）
        links = page.evaluate("""() => [...document.querySelectorAll('a')].map(a => ({t: (a.innerText||'').trim(), h: a.href}))""")
        notice_links, seen = [], set()
        for l in links:
            if re.search(r"page=(Information|Notice|News|Bulletin)", l["h"], re.I) and l["h"] not in seen:
                seen.add(l["h"])
                notice_links.append(l)
        print(f"お知らせらしいリンク: {len(notice_links)}件（全リンク {len(links)}件）")
        out.append("\n===== リンク一覧（見出し | URL）=====")
        for l in links[:150]:
            out.append(f"{l['t'][:60]} | {l['h']}")

        for i, l in enumerate(notice_links[:MAX_NOTICES], 1):
            try:
                page.goto(l["h"])
                page.wait_for_load_state("networkidle")
                time.sleep(1)
                out.append(f"\n===== お知らせ{i}：{l['t'][:80]} =====\n{l['h']}\n")
                out.append(page.inner_text("body")[:MAX_CHARS])
            except Exception as e:
                out.append(f"\n===== お知らせ{i}：開けませんでした（{type(e).__name__}）=====")
        browser.close()

    text = "\n".join(out)
    print(f"取得文字数: {len(text)}")
    encrypt_and_print("top_notices", text)


if __name__ == "__main__":
    main()
