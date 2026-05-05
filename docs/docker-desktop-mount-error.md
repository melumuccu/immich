# Docker Desktop mount source path エラーメモ

外付け HDD を交換し、新たなHDDで `docker compose up` した際に macOS 上で外付け HDD の `LIBRARY_PATH` を bind mount している状態で発生した起動エラーの覚書。

## 発生したエラー

```text
Error response from daemon: error while creating mount source path '/host_mnt/Volumes/1TB_Immich/immich-data/library': mkdir /host_mnt/Volumes/1TB_Immich: file exists
```

## 状況

- 外付け HDD A が故障
- 別の HDD B にバックアップデータを復元
- `.env` の `LIBRARY_PATH` を HDD B 側の `/Volumes/.../immich-data/library` に更新
- `docker compose up` 実行時に上記エラーで `immich_server` が起動できない

## 原因

- Immich の設定ミスというより、Docker Desktop for macOS の file sharing 側の不整合
- `/Volumes/...` の bind mount を Docker Desktop が `/host_mnt/Volumes/...` に取り込む段階で失敗していた
- ホスト側のディレクトリが存在していても、この状態だと `mkdir ...: file exists` で落ちることがある

## 対処

1. Docker Desktop を完全終了して再起動する
1. Docker Desktop の Settings → Resources → File Sharing で `/Volumes` を外して Apply & Restart し、再度 `/Volumes` を追加して Apply & Restart する
1. file sharing implementation を切り替える

   - `VirtioFS`
   - `gRPC FUSE`

   今回はこの 3 つ目の対応で解消した。(VirtioFS → gRPC FUSE → VirtioFS)

## 補足

- `docker compose down` だけでは Docker Desktop 側の共有状態は直らない
- ホスト上の `LIBRARY_PATH` 実体が存在するかは先に確認する
- mount エラー解消後に `.immich` 欠落で別エラーになることがあるため、外付け HDD 交換時は [replace-external-hdd.md](replace-external-hdd.md) もあわせて確認する
