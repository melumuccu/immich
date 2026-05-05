# 外付け HDD 交換メモ

Immich の `library` を置いている外付け HDD が故障したときの復旧メモ。

## 新たなHDDにデータを復元する際のＰＯＩＮＴ　-> 隠しファイルも復元すること

- Time Machine などから復元するときは、`.immich` も必ず戻す
    - これは Immich の保存先整合性チェック用マーカーファイル

## 手順

基本的には `.env` の `LIBRARY_PATH` を新しい HDD のパスに更新するだけでOK

   例:

   ```dotenv
   LIBRARY_PATH=/Volumes/<新しいボリューム名>/immich-data/library
   ```

## よくある落とし穴

- ボリューム名が変わったのに `.env` の `LIBRARY_PATH` を更新していない
- Docker Desktop 側で `/Volumes` の file sharing が不整合になっている
- `library` の中身だけ復元して、ルート直下の `.immich` を落としている

Docker Desktop 側の mount source path エラーが出る場合は、[docker-desktop-mount-error.md](docker-desktop-mount-error.md) を参照する。
