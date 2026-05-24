import os
import re
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
    is_shinomiya = "篠宮" in report_text
    if is_shinomiya:
        name_rule_header = """★★★ 最重要指示 ★★★
この日報の提出者は「篠宮」です。
呼びかけは必ず「シノ」（呼び捨て）にしてください。
「篠宮さん」「シノさん」は絶対に使用禁止です。
★★★★★★★★★★★★

"""
    else:
        name_rule_header = ""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""{name_rule_header}あなたはスタッフの可能性を信じ、最大限支援する世界一の理解者として、日報・週報へのコメントを書く。

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
- スタッフへの呼びかけは必ず「名字＋さん」とする（例：「石川さん」「小西さん」「若澤さん」）
- 名前（下の名前）で呼ぶことは絶対にしない
- ただし提出者の名前が「篠宮」の場合のみ例外で、呼びかけは必ず「シノ」とする（「篠宮さん」「シノさん」と書いてはいけない）
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
    comment = message.content[0].text
    if is_shinomiya:
        comment = comment.replace("篠宮さん", "シノ").replace("シノさん", "シノ")
    return comment


def get_submitter_name(page) -> str:
    """ワークフロー詳細ページから申請者（提出者）の名前だけを取得する"""
    # 方法1: 申請者セルの隣のセルを取得
    try:
        申請者_el = page.query_selector('td:has-text("申請者")')
        if 申請者_el:
            name_text = 申請者_el.evaluate(
                'el => { const next = el.nextElementSibling; return next ? next.innerText : ""; }'
            )
            if name_text and name_text.strip():
                return name_text.strip()
    except Exception:
        pass

    # 方法2: ページ先頭のテキストから「申請者」ラベル周辺を正規表現で抽出
    try:
        header = page.inner_text("body")[:600]
        match = re.search(r'申請者[\s：:]+(\S{2,10})', header)
        if match:
            return match.group(1)
    except Exception:
        pass

    return ""


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
    skipped = set()

    while True:
        items = page.query_selector_all('a[href*="WorkFlowHandle"]')

        target = None
        target_href = None
        is_report = False
        for item in items:
            href = item.get_attribute("href")
            if href in skipped:
                continue
            text = item.inner_text().strip()
            if "日報" in text or "週報" in text:
                target = item
                target_href = href
                is_report = True
                print(f"日報・週報を処理: {text}")
                break
            elif "設備使用許可" in text or "練習台帳" in text:
                target = item
                target_href = href
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
                # 申請者本人が篠宮かどうかを確認（ページ内に篠宮の文字があるだけでは判断しない）
                submitter = get_submitter_name(page)
                print(f"申請者: {submitter}")
                if "篠宮" in submitter:
                    report_text = "篠宮 " + report_text
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
                skipped.add(target_href)

        except Exception as e:
            print(f"エラー: {e}")
            skipped.add(target_href)

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
