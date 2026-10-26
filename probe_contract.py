# -*- coding: utf-8 -*-
"""調査用（一時）：cybozu.com 共通管理「契約状況」画面のURLと、数字の出どころ（通信）を調べる。
ログに出すのはURLと契約表の文字（人数・容量）だけ。氏名は出さない。読むだけ。"""
import os, re, time
from playwright.sync_api import sync_playwright
from main import login, CYBOZU_URL

host = re.sub(r"https?://([^/]+).*", r"\1", CYBOZU_URL)
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    reqs = []
    page.on("request", lambda r: reqs.append(f"{r.method} {r.url}") if r.resource_type in ("xhr", "fetch") else None)
    login(page)
    page.goto(f"https://{host}/admin/")
    page.wait_for_load_state("networkidle"); time.sleep(2)
    print("admin URL:", page.url)
    link = page.query_selector('a:has-text("契約状況")')
    print("契約状況リンク:", link.get_attribute("href") if link else None)
    reqs.clear()
    if link:
        link.click(); page.wait_for_load_state("networkidle"); time.sleep(3)
    print("契約状況 URL:", page.url)
    for t in page.query_selector_all("table"):
        txt = re.sub(r"\s+", " ", t.inner_text())
        if "ユーザー数" in txt:
            print("表:", txt[:400])
    print("通信:")
    for r in reqs:
        print("  ", r.split("?")[0])
    b.close()
