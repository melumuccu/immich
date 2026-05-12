# Smart Ranker の動かし方

## 現在できる確認

- SQLite の初期化
- 設計書準拠の初期 master data 投入
- Compose network 内での起動
- 最小 GUI の起動
- GUI からの Person Group / Categories & Routing / Policies / Jobs 設定更新
- `learn`, `score`, `apply` の手動実行
- score review を独立 GUI でスコア順に確認
- unittest 一式の実行

## 各 job が行うこと

- `learn`: Immich の favorite asset と trash asset だけを収集し、`favorite_signal` と `trash_signal` を更新したうえで学習済みモデルと設定スナップショットを保存する。favorite 解除や restore 後も signal は保持する。
- `score`: すべての asset を学習済みモデルで採点し、`score_run` と `score_result` を保存する。GUI の score review page はこの結果をスコア順で 100 件ずつ表示する。
- `apply`: 現在の threshold 以下の asset を Review Album へ追加し、`action_execution_log` と `apply_exclusion_asset` を残す。`apply_exclusion_asset` は重複 apply の抑止に使い、ユーザーがあとで手動 trash した asset は次回の `learn` で通常どおり再収集する。

## 日常での使い方と対象

日常運用の基本順は `learn -> score -> apply`。

- `learn`
    - 日常での使い方: favorite / trash を教師信号として取り込みたいときに回す。favorite 解除や restore 後も学習用 signal を残したいので、まずこれを回す。
    - 対象: 現在 favorite の asset と、現在 trash にある asset。Review Album からユーザーが手動 trash した asset もここへ入る。
- `score`
    - 日常での使い方: 学習済みモデルで全件採点し、GUI の score review を更新したいときに回す。threshold 調整前の確認手順。
    - 対象: Immich 上のすべての asset。
- `apply`
    - 日常での使い方: score review で threshold を確認した後、threshold 以下の asset を Review Album へ送り、人手で最終確認したいときに回す。
    - 対象: 直近の `score` で保存された `score_result`。すでに trash 済みの asset や、すでに Review Album へ送付済みの asset は再適用しない。

## 現在の制約

- 日常コマンドは `mise run` 前提
- task は workspace root の `.env` を読む
- `/api/jobs/{job_type}` は同期実行
- `score` は採点のみで書き込みなし、`apply` は実書き込みあり

## 前提

- Python 3.10 以上
- `mise` が使えること
- workspace root に `.env` があること
- 作業ディレクトリは `smart-ranker`

## `.env` に入れる値

- 必須: `SMART_RANKER_IMMICH_API_KEY`
- 必須: `SMART_RANKER_IMMICH_USER_ID`
- 必須: `SMART_RANKER_REVIEW_ALBUM_ID` (`apply` の送付先 Album ID)
- 任意: `SMART_RANKER_PORT`
- 任意: `SMART_RANKER_REVIEW_THRESHOLD`

Compose service 側で `SMART_RANKER_IMMICH_BASE_URL` と `SMART_RANKER_IMMICH_DB_DSN` を組み立てるため、root の `.env` に追加しなくてよい。

## セットアップ

1. <span id="step-enter-project"></span>作業ディレクトリへ移動する。

```bash
cd /Users/fujisawakoki/projects/immich/smart-ranker
```

1. 初回だけ `mise` 設定を trust する。

```bash
mise trust
```

1. 依存と `.venv` を用意する。

```bash
mise run install
```

1. <span id="step-bootstrap-storage"></span>ローカル保存先と SQLite を初期化する。

```bash
mise run bootstrap
```

期待値:

- `state_dir=.../smart-ranker/var/local`
- `db_path=.../smart-ranker/var/local/db/smart-ranker.sqlite3`
- `applied_migrations=0001_initial_storage.sql, 0002_collect_batch_cursor.sql, 0003_learning_runtime.sql`

1. 初期 master data を投入する。

```bash
mise run seed-master-data
```

期待値:

- `person_groups=2`
- `categories=8`
- `routing_rules=9`
- `policies=1`
- `destinations=2`
- `schedules=3`

## 最短の動作確認

1. <span id="step-start-service"></span>Smart Ranker を Compose network 内で起動する。

```bash
mise run up
```

期待値:

- `smart-ranker` コンテナが起動する
- `http://127.0.0.1:8010/` が開ける

補足:

- 起動後のログ確認は `mise run logs`
- foreground で起動したい場合は `mise run dev`
- `mise run restart` は `smart-ranker` サービスだけを再作成する。依存サービスは既に起動済み前提
- Compose 起動中は `src/web` 配下の Python と HTML/CSS/JS が live reload 対象。保存後にブラウザが自動で再読み込みされる

1. ブラウザで最小 GUI を開く。

```text
http://127.0.0.1:8010/
```

期待値:

- `Smart Ranker Console` が表示される
- `Person Group` に seed 済み JSON が入る
- `Categories & Routing` に categories と routingRules の JSON が入る
- `Policies` に review threshold policy が出る
- `Jobs & Models` に `learn`, `score`, `apply` の schedules と model snapshot 一覧が出る
- `Event Ledger` に `Signals`, `Score Review`, `Apply Log` が出る
- `score review` nav から独立一覧ページへ移動できる

補足:

- 画面右上の `seed defaults` からも既定 master data を再投入できる
- JSON を編集して `save` を押すと backend 側の job 設定を再読込する
- score review 一覧は `http://127.0.0.1:8010/score-review` でも直接開ける

1. <span id="step-run-learn"></span>learn ジョブを実行する。

```bash
mise run learn
```

期待値:

- JSON に `jobRunId`, `jobType`, `status`, `submittedAt` が入る

1. [learn ジョブの実行](#step-run-learn)で返った `jobRunId` を使って状態を確認する。

```bash
JOB_RUN_ID=<jobRunId> mise run job-status
```

期待値:

- `jobType` が `learn`
- `status` が `completed`
- `result.runId` が入る
- `result.modelCount` と `result.modelKeys` が入る

## よく使う task

- `mise run seed-master-data`: 設計書準拠の初期 master data を投入する
- `mise run learn`: signal 同期と学習をまとめて実行する

## 引数つき task

- `JOB_RUN_ID` 必須: `mise run job-status` で指定する。`jobRunId` の状態を取得する。
- `SMART_RANKER_PORT` 任意: `learn`, `score`, `apply`, `job-status` で使う。既定は `8010`。

例:

```bash
JOB_RUN_ID=<jobRunId> mise run job-status
```

`learn`, `score`, `apply` は引数なし。workspace root の `.env` を読む。

## テストでの確認

1. 起動経路まわりの簡易検証を実行する。

```bash
mise run check
```

期待値:

- `OK`

1. unittest 一式を実行する。

```bash
mise run test
```

期待値:

- 現時点では `Ran 31 tests` と `OK`

## 生成されるもの

- `var/local/db/smart-ranker.sqlite3`
- `var/local/models/`
- `var/local/snapshots/`
- `var/local/logs/`

`SMART_RANKER_STATE_DIR` を指定しない場合は、既定で `smart-ranker/var` を使う。

## 注意

- env が不足している場合、job API は `status=failed` と設定エラーを返す
- `score` は model が未作成なら内部で `learn` を補完実行する
- `apply` は直近の `score_run` を使う。明示 `scoreRunId` が無ければ最新 completed run を参照する
- app 起動時には Immich DB へ接続しない。DB 接続確認は job 実行時に行う
- `unittest discover` は環境によって SQLite connection の `ResourceWarning` が出る場合がある
