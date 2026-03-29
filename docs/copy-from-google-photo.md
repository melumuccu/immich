# Google Photos から Immich へ全量移行する手順

## 0. 前提

- Immich は <http://localhost:2283> で起動済み
- Google Takeout の ZIP は、取り込み完了を確認するまで消さない
- 分割された ZIP は全パートを同じフォルダに置く
- 公式の takeout-\*.zip はあくまで例
- 今回のように Photos-3-001.zip という名前なら、実行時は Photos-\*.zip を使う

## 1. Google Takeout を作る

1. <https://takeout.google.com/> を開く
1. いったん全解除する
1. Google Photos だけを選ぶ
1. 全量移行したいなら、アルバム個別選択はせずそのまま進める
1. 次へ進む
1. Delivery method は任意
1. Export type は One-time archive
1. File type は ZIP
1. Archive size は 50GB
1. エクスポート作成後、すべての ZIP を同じフォルダにダウンロードする

## 2. Immich の API キーを作る

### 通常の API キー

Account Settings → API Keys → New API Key で作る
(めんどくさいから全権限許可した。 immich 公式がおすすめしてる CLI だしええか...と)

必要権限:

- asset.read
- asset.statistics
- asset.update
- asset.upload
- asset.copy
- asset.replace
- asset.delete
- asset.download
- album.create
- album.read
- albumAsset.create
- server.about
- stack.create
- tag.asset
- tag.create
- user.read

### 管理者 API キー

大きい移行では pause-immich-jobs を使うので、管理者アカウントに紐づく API キーも作る

必要権限:

- 通常キーの全権限
- job.create
- job.read

補足:

- あなたが管理者ユーザーで作業しているなら、同じキーを通常キー兼管理者キーとして使ってもよい

## 3. immich-go を入れる

- repo から落としてくる (<https://github.com/simulot/immich-go/releases>)
    - mac なら `immich-go_Darwin_arm64.tar.gz`
- `*.tar.gz` をダブルクリックで展開。中に immich-go があるのでパスを取る

```sh
chmod +x <immich-go パス>
sudo mv <immich-go パス> /usr/local/bin/
immich-go --version
```

## 4. 変数を設定する

- APIキーは同じもので良い (管理者ユーザとして実行するなら)

```sh
export IMMICH_URL=http://localhost:2283
export IMMICH_API_KEY='ここに通常APIキー'
export IMMICH_ADMIN_API_KEY='ここに管理者APIキー'
export TAKEOUT_DIR="$HOME/Downloads"
export LOG_FILE="$HOME/Downloads/immich-google-import-$(date +%Y%m%d-%H%M%S).log"
```

## 5. まず dry run する

### もしファイル名が takeout-001.zip 系なら

```sh
immich-go upload from-google-photos \
  --dry-run \
  --server="$IMMICH_URL" \
  --api-key="$IMMICH_API_KEY" \
  --admin-api-key="$IMMICH_ADMIN_API_KEY" \
  --client-timeout=60m \
  --concurrent-tasks=4 \
  --pause-immich-jobs=true \
  --on-errors=continue \
  --session-tag \
  --log-file="$LOG_FILE" \
  "$TAKEOUT_DIR"/takeout-*.zip
```

## 6. 本番実行する

- 上記の `--dry-run` を外す

## 7. 取り込み後の確認

1. Web UI を開く
   <http://localhost:2283>

1. Administration の Jobs を見る
   - サムネイル生成やメタデータ処理が流れていれば正常

1. 写真一覧やアルバム一覧を確認する
   - Google Photos 側のアルバムが作られているか
   - 代表的な年や月の写真が入っているか
   - 動画も見えているか

1. ログを見る

   ```sh
   tail -n 100 "$LOG_FILE"
   ```

## 8. 中断した場合

- 同じコマンドをそのまま再実行してよい
- immich-go は既存資産を見て重複をスキップする
- まず dry run で確認してから本番再開してもよい

## 完了後

- 取り込み結果に問題がないことを確認してから ZIP を整理する
- 取り込み漏れがあれば、同じ ZIP に対して --include-unmatched を付けて再実行する
- 長期運用するなら、今後はモバイルアプリのバックアップと併用する
