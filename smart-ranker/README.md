# Smart Ranker の動かし方

## 現在できる確認

- SQLite の初期化
- 設計書準拠の初期 master data 投入
- Compose network 内での起動
- 最小 GUI の起動
- GUI からの Person Group / Categories & Routing / Policies / Jobs 設定更新
- `collect`, `train`, `score`, `apply` の手動実行
- unittest 一式の実行

## 各 job が行うこと

- `collect`: Immich から差分 asset を集め、feedback を取り込み、学習と推論に使う feature input を作る。
- `train`: 収集済みデータから教師ラベルを再構成し、学習済みモデルと設定スナップショットを保存する。
- `score`: 学習済みモデルで推論し、`inference_trace` と dry-run の `action_execution_log` を残す。
- `apply`: 推論結果を使って Review アルバム追加や description 更新を実行し、`action_execution_log` を残す。

## 日常での使い方と対象

日常運用の基本順は `collect -> train -> score -> apply`。

- `collect`
    - 日常での使い方: まず最初に回す。新規追加、更新、trash、restore の差分を取り込みたいときに使う。
    - 対象: 初回は取得できる asset 全体。2 回目以降は `collector_cursor` 以後に更新された asset と、trash 状態が変わった asset が中心。手動で救済した asset の feedback もここで取り込む。
- `train`
    - 日常での使い方: Favorite、trash、救済 feedback が増えた後や、ルール変更後に回す。毎回必須ではなく、学習に使う判断材料が増えたタイミングで回す。
    - 対象: 直前の `collect` で feature input 化された asset 群と、`feedback_event` に入った weak positive。教師ラベルは trash、archive、favorite、weak positive から再構成する。
- `score`
    - 日常での使い方: 反映前の確認に使う。まず dry-run で推論結果と planned action を見て、閾値やルールが妥当かを確認する。
    - 対象: 直前の `collect` で入力化された asset のうち、`isTrashed = false` かつ `visibility = timeline` のもの。初回は実質的に全件、以降は通常は差分中心。
- `apply`
    - 日常での使い方: `score` の結果を見て問題なければ最後に回す。Review アルバム追加や description 更新を本当に反映したいときだけ使う。
    - 対象: `score` と同じ asset 群。最新または指定した `model` を使って再度推論し、action policy に従って実書き込みする。

## 現在の制約

- 日常コマンドは `mise run` 前提
- task は workspace root の `.env` を読む
- `/api/jobs/{job_type}` は同期実行
- `score` は dry-run、`apply` は実書き込みあり

## 前提

- Python 3.10 以上
- `mise` が使えること
- workspace root に `.env` があること
- 作業ディレクトリは `smart-ranker`

## `.env` に入れる値

- 必須: `SMART_RANKER_IMMICH_API_KEY`
- 必須: `SMART_RANKER_IMMICH_USER_ID`
- 任意: `SMART_RANKER_PORT`
- 任意: `SMART_RANKER_REVIEW_ALBUM_ID`
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

1. <span id="step-review-album-id"></span>Review Album の ID が必要なら取得する。

```bash
mise run review-album-id
```

別名のアルバムを引く場合:

```bash
ALBUM_NAME="Some Album" mise run review-album-id
```

1. [Review Album の ID 取得](#step-review-album-id)で得た値を必要に応じて workspace root の `.env` へ入れる。

```dotenv
SMART_RANKER_REVIEW_ALBUM_ID=replace-me
```

1. <span id="step-bootstrap-storage"></span>ローカル保存先と SQLite を初期化する。

```bash
mise run bootstrap
```

期待値:

- `state_dir=.../smart-ranker/var/local`
- `db_path=.../smart-ranker/var/local/db/smart-ranker.sqlite3`
- `applied_migrations=0001_initial_storage.sql`

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
- `schedules=4`

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
- `Policies` に review policy と destinations の JSON が入る
- `Jobs & Models` に schedules JSON と model snapshot 一覧が出る
- `Event Ledger`

補足:

- 画面右上の `seed defaults` からも既定 master data を再投入できる
- JSON を編集して `save` を押すと backend 側の job 設定を再読込する

1. <span id="step-run-train"></span>train ジョブを実行する。

```bash
mise run train
```

期待値:

- JSON に `jobRunId`, `jobType`, `status`, `submittedAt` が入る

1. [train ジョブの実行](#step-run-train)で返った `jobRunId` を使って状態を確認する。

```bash
JOB_RUN_ID=<jobRunId> mise run job-status
```

期待値:

- `jobType` が `train`
- `status` が `completed`
- `result.runId` が入る
- `result.modelCount` と `result.modelKeys` が入る

## よく使う task

- `mise run review-album-id`: アルバム名から ID を検索する
- `mise run seed-master-data`: 設計書準拠の初期 master data を投入する

## 引数つき task

- `JOB_RUN_ID` 必須: `mise run job-status` で指定する。`jobRunId` の状態を取得する。
- `ALBUM_NAME` 任意: `mise run review-album-id` で指定する。既定は `Review Album`。
- `SMART_RANKER_PORT` 任意: `collect`, `train`, `score`, `apply`, `job-status` で使う。既定は `8010`。

例:

```bash
JOB_RUN_ID=<jobRunId> mise run job-status
ALBUM_NAME="Some Album" mise run review-album-id
```

`collect`, `train`, `score`, `apply` は引数なし。workspace root の `.env` を読む。

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

- 現時点では `Ran 19 tests` と `OK`

## 生成されるもの

- `var/local/db/smart-ranker.sqlite3`
- `var/local/models/`
- `var/local/snapshots/`
- `var/local/logs/`

`SMART_RANKER_STATE_DIR` を指定しない場合は、既定で `smart-ranker/var` を使う。

## 注意

- env が不足している場合、job API は `status=failed` と設定エラーを返す
- `train` と `score` は必要な前段結果が無ければ内部で `collect` や `train` を補完実行する
- app 起動時には Immich DB へ接続しない。DB 接続確認は job 実行時に行う
- `unittest discover` は環境によって SQLite connection の `ResourceWarning` が出る場合がある
