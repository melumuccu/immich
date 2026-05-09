## v1 実装着手の最小分解

- [x] ストレージ初期化
    - [x] SQLite migration で `ranker_profile`, `person_group`, `person_group_member`, `category`, `routing_rule`, `training_signal_rule`, `category_score_policy`, `action_destination`, `action_policy`, `action_policy_step`, `execution_schedule`, `collector_cursor`, `feedback_event`, `inference_trace`, `action_execution_log` を作る。
    - [x] モデル保存ディレクトリ、設定スナップショット出力先、ジョブログ出力先を volume 上に確保する。
- [x] Immich 接続層の実装
    - [x] `immich_client` に asset metadata、metadata search、People、`search/smart`、書き込み系 API を実装する。
    - [x] `immich_db_reader` に Immich DB read-only 接続と `smart_search` の取得処理を実装する。
- [x] 差分収集ジョブの実装
    - [x] `collector_cursor` を読み、`updatedAfter` と `trashedAfter` を使った差分取得を実装する。
    - [x] 削除候補アルバム差分、または GUI 手動除外入力から `delete_candidate_rescued` の `feedback_event` を追記する。
    - [x] run 成功時のみ `collector_cursor` を更新する。
- [x] ラベル解決と特徴量組み立ての実装
    - [x] 人物系は People メタデータで決定し、書類、スクリーンショットは OCR、ファイル名、パス、タグの機械的ルールで判定する。
    - [x] 風景、ペットは `search/smart` の結果を弱ラベルとして取り込み、asset ごとの候補ラベル集合を作る。
    - [x] CLIP embedding と通常メタデータを学習、推論用マトリクスへ変換する。
- [x] 学習ジョブの実装
    - [x] `trash > archive > favorite > weak positive > unlabeled` の優先順位で教師ラベルを再構成する。
    - [x] 汎用モデル 1 本と、人物系 1 本、非人物系複数本の Logistic Regression を学習し、`.pkl` と設定スナップショットを保存する。
- [x] 推論、反映ジョブの実装
    - [x] `isTrashed: false` かつ `visibility: timeline` の asset を対象にスコア算出し、`inference_trace` へ保存する。
    - [x] dry-run 付きで `action_execution_log` を残し、Review アルバム追加や description 更新を `Action Executor` から実行する。
- [x] API と最小 GUI の実装
    - [x] 手動実行 API は `jobRunId` を返す形で `collect`, `train`, `score`, `apply` を先に用意する。
    - [x] GUI は Person Group、Categories & Routing、Policies、Jobs & Models、Event Ledger の最小画面から着手する。
- [x] 初回完走条件
    - [x] Favorite、trash、People、CLIP embedding を取得できる。
    - [x] 差分収集が `collector_cursor` で再開できる。
    - [x] 1 回の学習で汎用モデルと少なくとも 1 本の専用モデルが保存される。
    - [x] 1 回の推論で `inference_trace` と `action_execution_log` が残る。

## 次タスク

- [ ] ジョブ実行の非同期化
    - [ ] `/api/jobs/{job_type}` を同期実行から切り離し、手動実行も共通ランナー経由に寄せる。
    - [ ] `jobRunId` の状態確認と履歴参照を API と GUI の両方から辿れるようにする。
- [ ] scheduler 常駐化
    - [ ] APScheduler を組み込み、`execution_schedule` を読んで定期実行を登録する。
    - [ ] `sync_people_catalog` と `cleanup_runtime_state` を追加し、重複実行ガードを入れる。
- [ ] GUI の本実装
    - [ ] frontend パッケージを分離し、Svelte + TypeScript + Vite 構成へ移す。
    - [ ] Dashboard と Jobs & Models から最新ジョブ結果、モデル件数、再実行を確認できるようにする。
- [ ] 実運用前の確認強化
    - [ ] `/healthz` と `/readyz` を追加し、起動確認と依存確認を分ける。
    - [ ] Compose 上での collect、train、score、apply の E2E 確認を自動化する。
