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
    print("ログイン完了")


def go_to_workflow_index(page):
    page.goto(CYBOZU_URL)
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    wf_link = page.query_selector('a:has-text("ワークフロー")')
    if wf_link:
        wf_link.click()
        page.wait_for_load_state("networkidle")
        time.sleep(2)


def approve_item(page):
    for selector in ['input[name="Approve"]', 'input[value="この申請を決裁する"]']:
        btn = page.query_selector(selector)
        if btn:
            btn.click()
            page.wait_for_load_state("networkidle")
            time.sleep(2)
            return True
    return False


def process_workflow_items(page):
    go_to_workflow_index(page)
    processed = 0

    while True:
        items = page.query_selector_all('a[href*="WorkFlowHandle"]')

        target = None
        is_report = False
        for item in items:
            text = item.inner_text().strip()
            if "日報" in text or "週報" in text:
                target = item
                is_report = True
                print(f"日報・週報を処理: {text}")
                break
            elif "設備使用許可" in text or "練習台帳" in text:
                target = item
                is_report = False
                print(f"設備使用許可申請を処理: {text}")
                break

        if target is None:
            print(f"処理完了。合計 {processed} 件を承認しました。")
            break

        try:
            target.click()
            page.wait_for_load_state("networkidle")
            time.sleep(2)

            if is_report:
                report_text = page.inner_text("body")[:2000]
                print("AIコメントを生成中...")
                comment = generate_comment(report_text)
                print(f"生成コメント: {comment}")

                comment_box = page.query_selector("textarea")
                if comment_box:
                    comment_box.click()
                    comment_box.fill(comment)
                    time.sleep(1)

            if approve_item(page):
                processed += 1
                print(f"承認完了 ({processed}件目)")
            else:
                print("承認ボタンが見つかりませんでした。スキップします。")

        except Exception as e:
            print(f"エラー: {e}")

        go_to_workflow_index(page)

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
