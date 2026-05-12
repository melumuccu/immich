## 現在地

- [x] SQLite を中心とした基礎ストレージと migration の導入
- [x] Immich API / DB read-only への接続基盤
- [x] ラベル解決、モデル学習、推論、GUI の最小構成
- [x] 手動 job 実行と job 履歴の基本導線

## v2 再設計タスク

- [ ] `collect` と `train` の統合
- [ ] `learn` job 名、CLI 名、API 名、内部 `job_type` の命名を確定する。
- [ ] current favorite と current trash の同期を 1 job にまとめる。
- [ ] `learn` 完了時にモデル保存と設定 snapshot 保存まで終える。

- [ ] 手動学習 signal の永続化
- [ ] `favorite_signal` と `trash_signal` を別テーブルで保持する。
- [ ] favorite 解除時の `cleared_at`、restore 時の `restored_at` を保持する。
- [ ] 直近 manual signal を教師ラベルへ再構成するロジックを決める。

- [ ] Review Album 送付台帳の導入
- [ ] `apply_exclusion_asset` を追加する。
- [ ] `apply` によって Review Album へ送った asset の重複 apply を抑止する。
- [ ] 除外解除の運用フローを GUI か運用 runbook のどちらで持つか決める。

- [ ] `score` の全件化
- [ ] asset 全件を対象とした `score_run` / `score_result` 保存へ切り替える。
- [ ] GUI に score 順一覧を追加し、状態フィルタと件数表示を出す。
- [ ] 最新 completed run を GUI の既定表示対象にする。

- [ ] 閾値 GUI と `apply` の接続
- [ ] GUI で削除閾値を編集できるようにする。
- [ ] `apply` が最新 threshold と最新 score snapshot を読むようにする。
- [ ] 閾値以下、未保護、未 trash の asset を一括で Review Album へ送る。

- [ ] API と job 実行経路の整理
- [ ] `/api/jobs/{job_type}` を `learn`, `score`, `apply` の 3 系統へ寄せる。
- [ ] `jobRunId` の状態確認と履歴参照を API と GUI の両方から辿れるようにする。
- [ ] `apply` 実行時に使用した threshold と `score_run` を履歴へ固定する。

- [ ] テスト更新
- [ ] `learn` の signal 同期とラベル再構成の unit test を追加する。
- [ ] `score` 全件化に合わせて GUI/API の一覧 test を更新する。
- [ ] `apply` 後に Review Album 候補を手動 trash した asset が `learn` に入ることを E2E で確認する。

## 実運用前の確認

- [ ] `/healthz` と `/readyz` を追加し、起動確認と依存確認を分ける。
- [ ] Compose 上での `learn`、`score`、`apply` の E2E 確認を自動化する。
- [ ] 大量 asset 環境で `score_all_assets` の実行時間と GUI 応答時間を測る。
