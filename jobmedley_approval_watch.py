# ==========================================================
# 【何をする】ジョブメドレー応募者ラリーの承認スプレッドシートを見て、
#   院長が承認列に「OK」を入れた行があれば、apotool の送信ワークフローを起動する。
#   ここでは応募者に何も送らない。送るのは apotool 側の jobmedley_send.yml。
#
# 【なぜここに居るか】このリポジトリは30分ごとに動いていて、しかも公開リポジトリ＝
#   GitHub Actions の無料枠を消費しない。承認から送信までの待ち時間を最短にするため、
#   「承認された行があるかどうか」だけをここで見て、あるときだけ有料側を起こす。
#   （Cron-job.org の無料枠は12件で満杯なので新しいcronは作れない）
#
# 【環境変数】
#   DRIVE_TOKEN_JSON            スプレッドシートを読むための院長のOAuthトークン
#                               （サービスアカウント鍵 GOOGLE_CREDENTIALS_JSON があればそちらを優先）
#   JOBMEDLEY_REPLY_SHEET_ID    承認スプレッドシートのID
#   DISPATCH_PAT                apotool のワークフローを起動するトークン
# ==========================================================
import os
import sys
import json

import requests
from google.auth.transport.requests import Request

SHEET_NAME = "応募者ラリー"
STATUS_COL = 1          # A列 状態
APPROVAL_COL = 2        # B列 承認
NAME_COL = 7            # G列 氏名
TARGET_WF = "jobmedley_send.yml"
REPO = "shin3578-oss/apotool-automation"


def log(msg):
    print(f"[jobmedley承認見張り] {msg}", flush=True)


def main():
    sheet_id = os.environ.get("JOBMEDLEY_REPLY_SHEET_ID", "")
    sa = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    user = os.environ.get("DRIVE_TOKEN_JSON", "")
    if not sheet_id or not (sa or user):
        log("設定が無いので何もしません")
        return

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    if sa:
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_info(json.loads(sa.lstrip("﻿")), scopes=scopes)
    else:
        from google.oauth2.credentials import Credentials as UserCreds
        creds = UserCreds.from_authorized_user_info(json.loads(user.lstrip("﻿")))
    creds.refresh(Request())

    r = requests.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{SHEET_NAME}!A2:G",
        headers={"Authorization": f"Bearer {creds.token}"}, timeout=30)
    if r.status_code != 200:
        log(f"スプレッドシートを読めませんでした ({r.status_code}) — 今回は見送ります")
        return

    rows = r.json().get("values", [])
    waiting = []
    for row in rows:
        row = row + [""] * 8
        if row[STATUS_COL - 1].strip() != "下書き":
            continue
        if row[APPROVAL_COL - 1].strip() != "OK":
            continue
        waiting.append(row[NAME_COL - 1] or "（氏名不明）")

    if not waiting:
        log("承認済みの下書きはありません")
        return

    log(f"承認済み {len(waiting)}件: {' / '.join(waiting)} → 送信ワークフローを起動します")
    pat = os.environ.get("DISPATCH_PAT", "")
    if not pat:
        log("DISPATCH_PAT が無いため起動できません")
        sys.exit(1)
    d = requests.post(
        f"https://api.github.com/repos/{REPO}/actions/workflows/{TARGET_WF}/dispatches",
        headers={"Authorization": f"token {pat}", "Accept": "application/vnd.github+json"},
        json={"ref": "main"}, timeout=30)
    if d.status_code != 204:
        log(f"起動に失敗しました ({d.status_code}) {d.text[:200]}")
        sys.exit(1)
    log("起動しました")


if __name__ == "__main__":
    main()
