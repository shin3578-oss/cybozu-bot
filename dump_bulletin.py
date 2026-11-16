# -*- coding: utf-8 -*-
"""サイボウズの掲示板を読み、キーワードに当たる投稿の本文を取り出す（調査用・読み取りのみ）。

2026-11-16 院長指示：医局（ビュープラザ505）をめぐる住民とのやり取りを掲示板から遡って読む。
サイボウズの認証情報はこのリポジトリのSecretsにしかないため、ここで実行する。

【大事】このリポジトリは公開＝Actionsのログは誰でも読める。
本文は院長PCだけが持つ秘密鍵でしか開けない形に暗号化して出す（公開鍵で包んだ AES キー＋AES-GCM）。
サイボウズ側は一切変更しない（ログインして開くだけ）。
"""
import os
import re
import time
from playwright.sync_api import sync_playwright

import dump_top_notices as base  # login と暗号化を借りる（鍵だけ今回用に差し替え）

base.PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEAylQj0BglyzJ8DHl2sb7B
JIl76zUThBmhrYQdgQX2fHOLYfp0Hs6wEXZxshq/Jjnv0cLb/hm3w3qs4ed8VDtQ
Np9QhoH5Ln/iqAuhtMAwbgqzhMLGDBiJCsx3Ugr9M/tU6Gd2a6Tgna2SI1g3A7+c
iGtMN4EyAR1EXpCkdkyyt1t3xUoRfaJ2TpajYmltVYYyji89DfWEirUFZjgFJj9l
twhX93Dx9/vnqqOGYLHAx31Ce8WB9gTevHQqzx+/BgXqg7LqKOrLOl+lFGGoaeLI
nFaBJcEmFJmA+fxkqMLQVSlJ2q/mgu771M5uYXqg7P9Vlncfe08ycLrMu2anrOqA
I4zNzMIQgsbI/EWrSwb3e6JyBcVLNqjHZnSt2W8h/nWlJcjDFcy6IlR3YZ2p+gXv
ocswu+OqsR+RrW629/TB3B1fvESFdR68qjB1jCWsfzQQHcBMJPzOVZbHil37XPcX
6M5Z5ADeW4hgrd8V8WBDT5gAMfvQE/yI8mN/+lWq9OalAgMBAAE=
-----END PUBLIC KEY-----
"""

KEYWORDS = os.environ.get(
    "BULLETIN_KEYWORDS",
    "住民,管理組合,管理会社,理事,苦情,クレーム,医局,505,ビュープラザ,事務所,出入り,警察,騒音,近隣,マンション,エレベーター,オートロック,住人,似顔絵,指摘,スクラブ,通報,引越",
).split(",")
MAX_VIEWS = int(os.environ.get("BULLETIN_MAX_VIEWS", "900"))
START = int(os.environ.get("BULLETIN_START", "0"))  # 2回目以降は続きから読む
TIME_BUDGET = int(os.environ.get("BULLETIN_MINUTES", "35")) * 60
MAX_CHARS = 8000


def goto(page, url):
    page.goto(url)
    page.wait_for_load_state("domcontentloaded")
    time.sleep(0.6)


def links_of(page):
    return page.evaluate("""() => [...document.querySelectorAll('a')].map(a => ({t: (a.innerText||'').trim(), h: a.href}))""")


def main():
    t0 = time.time()
    out_titles, out_hits = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        base.login(page)
        # ログイン後は cybozu.com の共通ポータル → サイボウズ Office（/o/ag.cgi）を直接開く
        m = re.match(r"(https://[^/]+)", page.url)
        ag = f"{m[1]}/o/ag.cgi"
        index = f"{ag}?page=BulletinIndex"
        goto(page, index)
        print("掲示板トップ:", page.title())

        # カテゴリ（cid）を幅優先で集める
        cats, seen_cat, queue = [], set(), [index]
        views, seen_view = [], set()
        while queue and len(seen_cat) < 120:
            url = queue.pop(0)
            if url in seen_cat:
                continue
            seen_cat.add(url)
            try:
                goto(page, url)
            except Exception as e:
                print("開けない一覧:", type(e).__name__)
                continue
            for l in links_of(page):
                h = l["h"]
                if "page=BulletinView" in h:
                    key = re.sub(r"&(sp|Sp)=\d+", "", h)
                    if key not in seen_view:
                        seen_view.add(key)
                        views.append((l["t"], h))
                elif "page=BulletinIndex" in h and h not in seen_cat:
                    queue.append(h)
            cats.append(url)
        print(f"一覧ページ {len(cats)}件・投稿 {len(views)}件")
        if not views:  # 画面の作りが想定と違う → 一覧ページの本文とリンクを出して作りを確かめる
            goto(page, index)
            dbg = [page.url, page.title(), page.inner_text("body")[:6000], "\n----- リンク -----"]
            dbg += [f"{l['t'][:50]} | {l['h']}" for l in links_of(page)[:300]]
            base.encrypt_and_print("bulletin_debug", "\n".join(dbg))
            browser.close()
            return

        for i, (title, h) in enumerate(views[START:START + MAX_VIEWS], 1):
            out_titles.append(f"{title[:80]} | {h}")
            if time.time() - t0 > TIME_BUDGET:
                out_titles.append("（時間切れ：ここから先の本文は未確認）")
                break
            try:
                goto(page, h)
                body = page.inner_text("body")
            except Exception as e:
                out_titles.append(f"  開けませんでした（{type(e).__name__}）")
                continue
            hit = [k for k in KEYWORDS if k and k in body]
            if hit:
                out_hits.append(f"\n===== 当たり{len(out_hits)+1}：{title[:80]}（語：{'・'.join(hit)}）=====\n{h}\n{body[:MAX_CHARS]}")
        browser.close()

    text = "===== 投稿の見出し一覧 =====\n" + "\n".join(out_titles) + "\n\n===== キーワードに当たった投稿 =====" + "".join(out_hits)
    print(f"見出し {len(out_titles)}件・当たり {len(out_hits)}件・文字数 {len(text)}")
    base.encrypt_and_print("bulletin", text)


if __name__ == "__main__":
    main()
