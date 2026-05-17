import os
import time
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import anthropic

load_dotenv()

CYBOZU_URL = os.getenv("CYBOZU_URL")
LOGIN_ID = os.getenv("CYBOZU_LOGIN_ID")
PASSWORD = os.getenv("CYBOZU_PASSWORD")
API_KEY = os.getenv("ANTHROPIC_API_KEY")

client = anthropic.Anthropic(api_key=API_KEY)


def generate_comment(report_text: str) -> str:
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""あなたはスタッフの可能性を信じ、最大限支援する世界一の理解者として、日報・週報へのコメントを書く。

【基本方針】
- スタッフが自主的に考え行動できる力を育てることを目的とする
- 答えを与えすぎず、問いかけを通じて思考を促す
- 小さな主体的行動を必ず承認する
- 「まとめ」や要約は一切行わない

【コメント構造】以下の流れで書く
1. 日々の診療・業務への感謝
2. 良かった行動や気づきへの具体的承認
3. 前回より成長している点の言語化（「前回より一歩進んでいる」「安定してできている」「変化が見えてきている」などの表現を使う）
4. 考えさせる問いかけ（例：「この取り組みを、次はどの場面で活かせそうでしょうか？」）
5. 未来への期待

【トーン】
- 穏やか・励まし・フラット・客観的
- 文体は「です・ます調」
- ジョジョ風の熱量を感じる静かで力強い表現を自然に織り交ぜる（「確実に前進しています」「この積み重ねが大きな力になります」「一歩ずつ形になっています」など）
- 過剰にならず、あくまで静かな力強さとして

【記述量へのフィードバック】
- 文章が短い場合 → なぜ短くなったのかを問いかけ、振り返りを促す
- 文章が長い場合 → 深い振り返りを評価しつつ、次に集中する行動を考えさせる

【名前呼びルール（厳守）】
- 週報提出者の名前が「シノ」の場合、呼びかけは必ず「シノ」とする（「シノさん」と書いてはいけない）
- コメント内で自然な形で必ず一度以上名前で呼びかける

【出力前チェック】
- 誤字脱字がないか
- 冗長な表現がないか
- 名前の呼び方がルール通りか
- 穏やかで前向きな文章になっているか

--- 日報・週報の内容 ---
{report_text}
---

コメントのみを出力してください。"""
            }
        ]
    )
    return message.content[0].text


def login(page):
    page.goto(CYBOZU_URL)
    page.wait_for_load_state("networkidle")

    # ログインフォームを探して入力
    page.locator('input[name="username"], input[name="userid"], input[type="text"]').first.fill(LOGIN_ID)
    page.locator('input[name="password"], input[type="password"]').first.fill(PASSWORD)
    page.locator('button:has-text("ログイン"), input[value="ログイン"]').first.click()
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    page.screenshot(path="login_result.png")
    print(f"ログイン後URL: {page.url}")
    print("ログイン完了")


def process_workflow_items(page):
    # トップページのスクリーンショットを撮って確認
    page.goto(CYBOZU_URL)
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    page.screenshot(path="workflow_page.png")
    print(f"現在のURL: {page.url}")

    # ワークフローリンクを探す
    wf_link = page.query_selector('a[href*="workflow"], a[href*="Workflow"], a:has-text("ワークフロー")')
    if wf_link:
        wf_href = wf_link.get_attribute("href")
        print(f"ワークフローリンク発見: {wf_href}")
        wf_link.click()
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        page.screenshot(path="workflow_page.png")
        print(f"ワークフローURL: {page.url}")
    else:
        print("ワークフローリンクが見つかりません")

    # ページ内の全リンクをデバッグ出力
    all_links = page.query_selector_all('a[href]')
    print(f"ページ内リンク総数: {len(all_links)}")
    for a in all_links:
        href = a.get_attribute("href")
        text = a.inner_text().strip()[:30]
        if href:
            print(f"  [{text}] -> {href}")

    # ワークフローアイテムを種類別に収集
    items = page.query_selector_all('a[href*="WorkFlowHandle"]')
    report_links = []    # 日報・週報（AIコメントあり）
    facility_links = []  # 設備使用許可申請（コメントなし即承認）

    for item in items:
        href = item.get_attribute("href")
        text = item.inner_text().strip()
        if not href or not text:
            continue
        if "日報" in text or "週報" in text:
            print(f"日報・週報: {text}")
            report_links.append(href)
        elif "設備使用許可" in text or "練習台帳" in text:
            print(f"設備使用許可申請: {text}")
            facility_links.append(href)

    print(f"日報・週報: {len(report_links)}件 / 設備使用許可申請: {len(facility_links)}件")

    processed = 0

    # 日報・週報：AIコメントをつけて承認
    for link in report_links:
        try:
            page.goto(link if link.startswith("http") else CYBOZU_URL + link.lstrip("/"))
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            # レポート本文を取得
            report_text = ""
            content_selectors = [
                ".comment-body",
                ".workflow-detail",
                ".grn-workflow-detail",
                "table.infolist-gf",
                ".ocean-ui-comments-commentbody",
            ]
            for selector in content_selectors:
                el = page.query_selector(selector)
                if el:
                    report_text = el.inner_text().strip()
                    break

            if not report_text:
                report_text = page.inner_text("body")[:1000]

            if len(report_text) < 10:
                print("内容を取得できませんでした。スキップします。")
                continue

            # AIでコメント生成
            print("AIコメントを生成中...")
            comment = generate_comment(report_text)
            print(f"生成コメント: {comment}")

            # コメント入力欄を探して入力
            comment_box_selectors = [
                'textarea[name*="comment"]',
                'textarea[name*="Comment"]',
                ".grn-comment-textarea textarea",
                "textarea",
            ]
            comment_box = None
            for selector in comment_box_selectors:
                comment_box = page.query_selector(selector)
                if comment_box:
                    break

            if comment_box:
                comment_box.click()
                comment_box.fill(comment)
                time.sleep(1)

            # 承認ボタンをクリック
            approved = False
            for selector in ['input[name="Approve"]', 'input[value="この申請を決裁する"]']:
                btn = page.query_selector(selector)
                if btn:
                    btn.click()
                    page.wait_for_load_state("networkidle")
                    approved = True
                    processed += 1
                    print(f"承認完了 ({processed}件目)")
                    time.sleep(2)
                    break

            if not approved:
                print("承認ボタンが見つかりませんでした。スキップします。")

        except Exception as e:
            print(f"エラーが発生しました: {e}")
            continue

    # 設備使用許可申請：コメントなしで即承認
    for link in facility_links:
        try:
            page.goto(link if link.startswith("http") else CYBOZU_URL + link.lstrip("/"))
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            approved = False
            for selector in ['input[name="Approve"]', 'input[value="この申請を決裁する"]']:
                btn = page.query_selector(selector)
                if btn:
                    btn.click()
                    page.wait_for_load_state("networkidle")
                    approved = True
                    processed += 1
                    print(f"設備使用許可申請 承認完了 ({processed}件目)")
                    time.sleep(2)
                    break

            if not approved:
                print("承認ボタンが見つかりませんでした。スキップします。")

        except Exception as e:
            print(f"エラーが発生しました: {e}")
            continue

    return processed


def main():
    print("=== サイボウズ 日報・週報 自動承認ツール ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            login(page)
            total = process_workflow_items(page)
            print(f"\n完了！合計 {total} 件を承認しました。")
        except Exception as e:
            print(f"エラー: {e}")
            page.screenshot(path="error_screenshot.png")
            print("エラー時のスクリーンショットを保存しました: error_screenshot.png")
        finally:
            time.sleep(3)
            browser.close()


if __name__ == "__main__":
    main()
