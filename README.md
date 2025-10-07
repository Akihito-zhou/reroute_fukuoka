# Re-Route FUKUOKA – 開発メモ

バス乗り倒し体験をつくる Web アプリです。まだ開発初期なので、まずは全員が同じやり方で作業できるように手順をまとめました。

---

## 📂 ディレクトリ構成（ざっくり）

```
reroute-fukuoka/
├─ apps/
│  ├─ web/        # フロント（React + Vite）
│  │  └─ src/
│  │     ├─ App.tsx
│  │     └─ index.tsx ほか
│  └─ api/        # バックエンド（FastAPI）
│     ├─ main.py
│     ├─ routes.py
│     └─ tests/
├─ packages/      # 共有コンポーネント／ユーティリティ（任意）
├─ infra/         # Docker / Traefik などの設定
├─ scripts/       # データ投入やメンテ用スクリプト
├─ .github/       # GitHub Actions (CI/CD)
├─ .env.example   # 環境変数のテンプレ
├─ Makefile       # 短縮コマンド集
└─ README.md
```

基本は `apps/web` と `apps/api` を触れば OK。Docker 関連は `infra/` に入っています。

---

## 0. 作業フォルダを用意

1. 自分の PC に好きな作業フォルダを作ります。  
   例: `C:\Users\<YOU>\Desktop\reroute-fukuoka` や `~/projects/reroute`
2. フォルダを開き、そこでターミナル（コマンドライン）を開きます。
   - Windows: エクスプローラーでフォルダを開いて `Shift + 右クリック` → 「PowerShell をここで開く」
   - Mac: Finder でフォルダを開いて `ターミナル` を起動 → `cd フォルダパス`

---

## 1. 必要ツールの準備

- **Git**（バージョン管理）
- **Node.js 20** 以上（フロント用）  
  - `corepack` が入っていれば `pnpm` が使えます
- **Python 3.11**（バックエンド用）
- **Docker Desktop**（全員インストール推奨）

インストールできたら、以下のコマンドが通るか確認しましょう。

```bash
git --version
node -v
python --version
docker --version
```

---

## 2. リポジトリを取得

```bash
cd <作業フォルダ>
git clone https://github.com/Akihito-zhou/reroute_fukuoka.git
cd reroute_fukuoka
```

初回だけ `.env.example` をコピーしておきます（Docker や API が参照します）。

```bash
cp .env.example .env  # Windows は copy .env.example .env
```

---

## 3. チーム Git フロー（初心者向け）

### 🛫 開発スタート前に

```bash
git checkout main          # main ブランチへ
git pull origin main       # 最新状態を取得
git checkout -b feature/<name>-<task>  # 作業用ブランチを作成
```

ブランチ名は `feature/あなたの名前` のように。例: `feature/zhou`

### 🛠 コードを書いたら

```bash
git status                 # 変更確認
git add .                  # まとめてステージ（怖ければファイル指定でもOK）
git commit -m "短い説明"   # 例: "Add planner page layout"
```

### 🔄 他のメンバーの更新を取り込む

```bash
git checkout main
git pull origin main       # 最新 main を取得
git checkout feature/<name>-<task>
git rebase origin/main     # 変更を上に積み直す（難しければ merge でもOK）
```

コンフリクトが出たら、エディタで修正 → `git add <ファイル>` → `git rebase --continue`。

### ☁️ リモートへ push

```bash
git push origin feature/<name>-<task>
```

初回 `push` 後、GitHub で Pull Request (PR) を作成。  
PR の宛先は必ず `main` にしてください。  
→ リーダーや担当がレビューして問題なければ `main` へマージ。

### ✅ チームルール（忘れずに）

- `main` に直接 push しない
- 作業は必ず `feature/<name>-<task>` ブランチで
- コミットメッセージはシンプルに（例: `"Fix API timeout"`）
- 1タスク = 1 PR。マージ後は新しいブランチを作って次の作業へ

### 👩‍💻 作業例

Zhou が Planner UI を作る場合:

```bash
git checkout main
git pull origin main
git checkout -b feature/zhou

# ... コーディング ...

git add .
git commit -m "Add planner UI skeleton"
git push origin feature/zhou
```

その後、GitHub で `feature/zhou -> main` の PR を作成すれば OK です。

---

## 4. ローカルで動かす方法

### フロント（apps/web）

```bash
corepack enable            # 初回のみ
pnpm install               # 依存関係インストール
pnpm dev                   # http://localhost:5173 で動作確認
```

チェック用:

```bash
pnpm lint
pnpm build
```

### バックエンド（apps/api）

```bash
pip install poetry          # 初回のみ
poetry install              # 依存関係インストール
poetry run uvicorn main:app --reload  # http://localhost:8000
```

テスト実行:

```bash
poetry run pytest
```

---

## 5. Docker でまとめて動かす（おすすめ）

Docker を使うと、フロント + API + Redis が一括で立ち上がります。プロジェクトルートの `Makefile` に短縮コマンドが定義されているので、こちらを使うと便利です。

### 起動

```bash
make up-dev
```
このコマンドは `docker compose -f infra/compose/docker-compose.dev.yml up --build` と同じです。初回起動やコンテナを再ビルドしたいときに使います。

起動後、各サービスは以下のポートでアクセスできます:
- **Web**: http://localhost:5173
- **API**: http://localhost:8000/docs
- **Redis**: localhost:6379

### 停止

```bash
make down-dev
```
このコマンドは `docker compose -f infra/compose/docker-compose.dev.yml down --remove-orphans` と同じで、コンテナを停止・削除します。

### よく使う補助コマンド

```bash
make logs        # 全サービスのログをリアルタイムで表示
make sh-web      # Web サービスのコンテナに入る
make sh-api      # API サービスのコンテナに入る
```

---

## 6. 困ったときのメモ

- `pnpm` や `poetry` のコマンドが動かない → まずは依存のインストールを確認（パスが通っているか）
- `git push` でエラー → ブランチ名、リモート名を再確認。リベース後は `--force-with-lease` が必要なことがあります。
- Docker のポート競合 → 他のアプリが 5173 / 8000 / 5432 / 6379 を使っていないか確認。必要なら `infra/compose/docker-compose.dev.yml` の `ports` を変更。
- `.env` を更新したのに反映されない → Docker を使っている場合は `down -v` して再起動。

---

## 7. 次のTODO（初期アイデア）

1. バス乗り倒しルートのアルゴリズム下地をつくる
2. GTFS や路線データを取り込むスクリプトを準備
3. Web UI の画面・状態管理を固める
4. API の目的関数やレスポンス形式をブラッシュアップ

---

気軽に質問してください。  
「どう書けばいいかわからない」「コンフリクトが出た」など、何でも OK です。  
全員で丁寧に進めていきましょう！ 🚍✨
