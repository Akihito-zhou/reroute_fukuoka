# ---- ビルドステージ ----
FROM node:20-alpine AS build
WORKDIR /web

# まず lock と workspace の定義を配置してキャッシュ効率を最大化する
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml tsconfig.base.json ./
COPY apps/web/package.json apps/web/package.json
# 共有パッケージがある場合は先にそれぞれの package.json をコピーする
# COPY packages/ui/package.json packages/ui/package.json

# pnpm を準備し、lock に基づいて依存を事前フェッチする
RUN corepack enable && corepack prepare pnpm@8.15.4 --activate && pnpm fetch

# ソースコードをコピー
COPY apps ./apps
COPY packages ./packages

# 依存をインストール（lockfile が正しければ frozen を使って再現性を高める）
RUN pnpm install --frozen-lockfile --prefer-offline

# ビルド（指定ディレクトリで実行するのが最も安定）
RUN pnpm -C apps/web build

# ---- ランタイムステージ ----
FROM nginx:alpine AS runtime
# outDir を dist 以外にしている場合はここを変更する
COPY --from=build /web/apps/web/dist/ /usr/share/nginx/html/
