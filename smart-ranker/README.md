# Smart Ranker の動かし方

## 現在できる確認

- SQLite の初期化
- Compose network 内での起動
- 最小 GUI の起動
- `collect`, `train`, `score`, `apply` の手動実行
- unittest 一式の実行

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

1. ブラウザで最小 GUI を開く。

```text
http://127.0.0.1:8010/
```

期待値:

- `Smart Ranker Console` が表示される
- `Person Group`
- `Categories & Routing`
- `Policies`
- `Jobs & Models`
- `Event Ledger`

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
