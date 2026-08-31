#!/usr/bin/env python3
"""
GitHub Actions 無料枠の見張り（公開リポジトリ側の安全網）

【なぜ公開リポジトリに置くのか】
  2026-08-30 14:30、無料枠（月2,000分）を使い切って apotool-automation（非公開）の
  自動化が丸1日まるごと止まった。しかも**誰にも知らせが行かなかった**。
  理由は単純で、失敗通知Bot（if: failure()）も消費レポートも、止まったのと同じ
  非公開リポジトリの中にあったから。枠切れではジョブ自体が起動しないので、
  「失敗の通知」も一緒に起動しない＝完全な無音になる。

  見張りは、見張る対象と別の場所に置かないと一緒に黙る。
  このリポジトリは公開＝Actionsが無料・無制限なので、枠が尽きても動き続ける。

【いつ動く】bot.yml（30分ごと）の中の、毎日 9:00 JST の回だけ
【何をする】非公開リポジトリ全部の当月消費を実測し、
  ・2,000分を超えている → 🚨 全停止中として院長DM（失敗通知Bot）
  ・1,600分（80%）を超えている → ⚠️ 警告として院長DM（レポートBot）
  ・それ未満 → 何もしない（毎日の平常報告は出さない）
【通知経路】deadline-alert（公開）の quota_alert.yml を dispatch する。
  このリポジトリはLINEワークスの秘密鍵を持たないため、鍵を持つ公開リポジトリに送信を頼む。
  渡すのは**数値と警戒レベルだけ**で、文面は向こうで組み立てる。
  ワークフローの入力は実行ログにそのまま印字され、公開リポジトリでは誰でも読めるため、
  「好きな文面を送れる汎用の入口」を公開側に作ってはいけない
  （2026-08-10に院長判断で却下・2026-08-31に実測で再確認）。
【対象】ユーザーの非公開リポジトリを毎回APIで引き直す（一覧を手で持たない＝新設の取りこぼしを防ぐ）
"""

import json
import math
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
FREE_LIMIT_MIN = 2000
WARN_MIN = 1600            # 80%
NOTIFY_REPO = "shin3578-oss/deadline-alert"   # LINEワークス送信を頼む公開リポジトリ
NOTIFY_WORKFLOW = "quota_alert.yml"
MAX_CALLS = 900            # APIの叩きすぎ防止（1回の見張りで使う上限）

TOKEN = os.environ.get("DISPATCH_PAT") or os.environ.get("GITHUB_PAT") or ""
_calls = 0


def api(url):
    global _calls
    if _calls >= MAX_CALLS:
        raise RuntimeError("API呼び出しが上限に達しました")
    _calls += 1
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code < 500 or attempt == 2:
                raise
        except Exception:
            if attempt == 2:
                raise
    return None


def t(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ") if s else None


def private_repos():
    """このアカウントの非公開リポジトリ（＝課金対象）を引き直す"""
    out, page = [], 1
    while True:
        rs = api(f"https://api.github.com/user/repos?visibility=private&affiliation=owner&per_page=100&page={page}")
        out += [r["full_name"] for r in rs]
        if len(rs) < 100:
            return out
        page += 1


def used_minutes(period):
    """当月の課金分。ジョブ単位で実時間を分に切り上げて合計する。

    /timing の billable は total_ms=0 を返すので使えない（2026-08-01実測）。
    """
    total = 0
    detail = {}
    for repo in private_repos():
        sub, page = 0, 1
        while True:
            runs = api(f"https://api.github.com/repos/{repo}/actions/runs"
                       f"?created={period}&per_page=100&page={page}").get("workflow_runs", [])
            for run in runs:
                for j in api(f"https://api.github.com/repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100").get("jobs", []):
                    st, ce = t(j.get("started_at")), t(j.get("completed_at"))
                    if not st or not ce:
                        continue
                    sec = (ce - st).total_seconds()
                    if sec > 0:
                        sub += math.ceil(sec / 60)
            if len(runs) < 100:
                break
            page += 1
        if sub:
            detail[repo.split("/")[1]] = sub
        total += sub
    return total, detail


def notify(inputs):
    """deadline-alert の quota_alert.yml を起こして院長DMを送ってもらう。

    渡すのは数値と警戒レベルだけ。文面は向こうで組み立てる（公開リポジトリの
    実行ログに任意の文章が残らないようにするため）。
    """
    # NO_NOTIFY=1 で送らずに内容だけ出す（動作確認用）
    if os.environ.get("NO_NOTIFY", "").strip() in ("1", "true", "True"):
        print("--- NO_NOTIFY のため送信しない。渡すはずだった値 ---")
        print(json.dumps(inputs, ensure_ascii=False, indent=2))
        print("--- ここまで ---")
        return

    body = json.dumps({"ref": "main", "inputs": inputs}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{NOTIFY_REPO}/actions/workflows/{NOTIFY_WORKFLOW}/dispatches",
        data=body,
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as res:
        if res.status not in (200, 204):
            raise RuntimeError(f"アラートのdispatchに失敗: HTTP {res.status}")
    print("院長DMへのアラートを起こした")


def main():
    if not TOKEN:
        print("[ERROR] DISPATCH_PAT がありません")
        return 1

    now = datetime.now(JST)
    period = f"{now.replace(day=1).date()}..{now.date()}"
    used, detail = used_minutes(period)
    remain = FREE_LIMIT_MIN - used
    days_in_month = ((now.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)).day
    forecast = round(used / now.day * days_in_month)

    top = "／".join(f"{k} {v}分" for k, v in sorted(detail.items(), key=lambda x: -x[1])[:3])
    print(f"当月 {used}分 / {FREE_LIMIT_MIN}分（残り{remain}／着地見込み {forecast}分）: {top}")

    reset = (now.replace(day=1) + timedelta(days=days_in_month)).replace(day=1)

    if used >= FREE_LIMIT_MIN:
        notify({"level": "blocked", "used": str(used), "forecast": str(forecast),
                "detail": top, "reset_month": str(reset.month)})
        return 0

    if used >= WARN_MIN or forecast > FREE_LIMIT_MIN:
        notify({"level": "warn", "used": str(used), "forecast": str(forecast),
                "detail": top, "reset_month": str(reset.month)})
        return 0

    print("枠に余裕あり。通知しない。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
