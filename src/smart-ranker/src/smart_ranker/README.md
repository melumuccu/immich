# Smart Ranker の動かし方

## 現在できる確認

- SQLite の初期化
- FastAPI と最小 GUI の起動
- 手動 job API の疎通確認
- unit test 一式の実行

## 現在まだ未接続の範囲

- `/api/jobs/{job_type}` の `collect`, `train`, `score`, `apply` は現状 stub
- job API は `jobRunId` を返し、`GET /api/jobs/{jobRunId}` で状態を返すところまで
- 実ジョブの collect / train / score / apply を API から end-to-end で起動するところまでは未接続

## 前提

- Python 3.10 以上
- 作業ディレクトリは `src/smart-ranker`
- 依存は `.venv` へ入れる前提

## セットアップ

1. 作業ディレクトリへ移動する。

```bash
cd /Users/fujisawakoki/projects/immich/src/smart-ranker
```

1. 仮想環境を作る。

```bash
python3 -m venv .venv
```

1. 依存を入れる。

```bash
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
```

## 最短の動作確認

1. <span id="step-bootstrap-storage"></span>ストレージを初期化する。

```bash
env PYTHONPATH=src .venv/bin/python -m smart_ranker bootstrap-storage --state-dir ./var/local
```

期待値:

- `state_dir=.../src/smart-ranker/var/local`
- `db_path=.../src/smart-ranker/var/local/db/smart-ranker.sqlite3`
- `applied_migrations=0001_initial_storage.sql`

1. Web アプリを起動する。

```bash
env SMART_RANKER_STATE_DIR=$PWD/var/local PYTHONPATH=src \
  .venv/bin/python -m uvicorn smart_ranker.web.app:create_app \
  --factory --host 127.0.0.1 --port 8010
```

期待値:

- `Uvicorn running on http://127.0.0.1:8010`
- 起動時に `SMART_RANKER_STATE_DIR` 配下へ DB と runtime directory が自動作成される

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

1. <span id="step-smoke-api"></span>manual job API を叩く。

```bash
curl -s -X POST http://127.0.0.1:8010/api/jobs/train \
  -H 'content-type: application/json' \
  -d '{"trigger":"manual-readme-check"}'
```

期待値:

- HTTP status `202`
- JSON に `jobRunId`, `jobType`, `status`, `submittedAt` が入る

1. [manual job API の確認](#step-smoke-api)で返った `jobRunId` を確認する。

```bash
curl -s http://127.0.0.1:8010/api/jobs/<jobRunId>
```

期待値:

- `jobType` が `train`
- `status` が `completed`
- `result.accepted` が `true`

## テストでの確認

1. 単体テスト一式を実行する。

```bash
env PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

期待値:

- 現時点では `Ran 15 tests` と `OK`

1. Web まわりだけ確認したい場合は Web test に絞る。

```bash
env PYTHONPATH=src .venv/bin/python -m unittest tests.test_web_app
```

1. ストレージだけ確認したい場合は [ストレージの初期化](#step-bootstrap-storage)に加えて storage test を回す。

```bash
env PYTHONPATH=src .venv/bin/python -m unittest tests.test_storage_bootstrap
```

## 生成されるもの

- `var/local/db/smart-ranker.sqlite3`
- `var/local/models/`
- `var/local/snapshots/`
- `var/local/logs/`

`SMART_RANKER_STATE_DIR` を指定しない場合は、既定で `src/smart-ranker/var` を使う。

## 現時点の確認観点

- CLI から storage bootstrap が通ること
- app factory から FastAPI が起動すること
- `/` が HTML を返すこと
- `/api/jobs/train` が `jobRunId` を返すこと
- test suite が green であること

## 注意

- `collect`, `train`, `score`, `apply` の API は UI と contract の骨組みを確認する段階
- 学習済みモデルを API から起動して collect から apply までを通す運用確認は、まだ別実装が必要
- `unittest discover` は現状 green だが、環境によっては SQLite connection の `ResourceWarning` が出る場合がある
