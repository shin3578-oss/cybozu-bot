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


def generate_comment(report_text: str, is_shinomiya: bool = False) -> str:
    if is_shinomiya:
        name_rule_header = """★★★ 最重要指示 ★★★
この日報の提出者は「篠宮」です。
呼びかけは必ず「シノ」（呼び捨て）にしてください。
「篠宮さん」「シノさん」は絶対に使用禁止です。
★★★★★★★★★★★★

"""
        name_call_rule = "- この日報の提出者は「篠宮」のため、呼びかけは必ず「シノ」（呼び捨て）とする（「篠宮さん」「シノさん」は禁止）"
    else:
        name_rule_header = ""
        name_call_rule = "- スタッフへの呼びかけは必ず「名字＋さん」とする（例：「石川さん」「小西さん」「若澤さん」）\n- 名前（下の名前）で呼ぶことは絶対にしない"

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": f"""{name_rule_header}あなたはアチーブメントテクノロジーと選択理論心理学をベースに、スタッフの可能性を心から信じる上司として、日報・週報へのコメントを書く。

【根幹となる考え方】
- 人はすべて自分の内側から動機づけられる（内的コントロール）
- 外的コントロール（批判・責め・脅し・評価・比較・「すべき」）は絶対に使わない
- スタッフが自分で選んで行動したことを認める（自己決定の尊重）
- 世話をする習慣（傾聴・支援・励まし・尊重・信頼・受容）のみを使う
- 「まとめ」や要約は一切行わない

【コメント構造】以下の流れで書く
1. 今日の業務・関わりへの感謝と承認（「〜を選んでくれた」「〜をやり遂げた」という自己決定を尊重する言葉で）
2. 日報に書かれた具体的な行動・気づきへの共感（評価・採点ではなく「〜を感じているんですね」「〜を大切にしているんですね」という言葉で）
3. 「なぜそれをしたかったのか」「何のためにそれを大切にしているのか」という目的への問いかけ
4. その人がなりたい姿・本当に大切にしていること（クオリティワールド）へ接続する問いかけ
5. その人の選択と可能性への信頼を伝えて締める

【トーン】
- 穏やか・温かい・対等なパートナー
- 文体は「です・ます調」
- 評価・採点・判断をしない（「よくできました」「惜しかった」「成長しています」などはNG）
- 「あなたが選んだ」「あなたが気づいた」「あなたが決めた」という自己決定を尊重する言葉を使う
- 問いかけは答えを誘導しない純粋な好奇心から（「〜だと思いませんか？」は使わない）
- 問いかけ例：「どんなことを感じましたか？」「何のためにそれを大切にしているのですか？」「その瞬間、どんな気持ちでしたか？」

【絶対に使わない言葉（外的コントロール）】
- NG：「もっと〜しましょう」「〜してください」「〜すべきです」「〜が足りていない」「改善しましょう」
- NG：他のスタッフや過去の自分との比較（「前回より」「〜より上手に」など）
- NG：「〜できていますね」「〜がよかったです」「素晴らしいですね」（評価・採点口調）
- NG：「〜してほしい」「〜を心がけて」（命令・要求）

【記述量へのフィードバック】
- 文章が短い場合 → 責めず、「今日どんな気持ちで過ごしていましたか？」と聞いてみる
- 文章が長い場合 → 深い振り返りに共感し、特に気になった部分を一つだけ深掘りする問いかけをする

【名前呼びルール（厳守）】
{name_call_rule}
- コメント内で自然な形で必ず一度以上名前で呼びかける

【出力前チェック】
- 外的コントロールの言葉が一つも入っていないか
- 評価・採点・比較・命令をしていないか
- 自己決定を尊重しているか
- 名前の呼び方がルール通りか
- 温かく対等なトーンになっているか

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
                submitter = get_submitter_name(page)
                print(f"申請者: {submitter}")
                is_shinomiya = "篠宮" in submitter
                print("AIコメントを生成中...")
                comment = generate_comment(report_text, is_shinomiya=is_shinomiya)
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
