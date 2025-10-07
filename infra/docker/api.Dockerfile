FROM python:3.11-slim AS api
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on

# 任意: ビルドが必要な依存があれば build-essential などを有効にする
# RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

# まずメタデータをコピーしてキャッシュを効かせる
COPY apps/api/pyproject.toml apps/api/poetry.lock* ./

# Poetry をインストールし、仮想環境を作らないようにしてコンテナ環境と統一する
RUN pip install --no-cache-dir "poetry==2.2.1" \
 && poetry config virtualenvs.create false

# pyproject を変更して lock と不一致になった場合はコンテナ内で lock を再生成する
RUN poetry lock --no-interaction

# 依存をインストール（本番依存のみ。開発依存はローカルで使用）
RUN poetry install --no-interaction --no-ansi --only main

# ソースをコピー（変更のたびに依存を入れ直さないようにする）
COPY apps/api/ ./

# エントリーモジュールは apps/api/main.py で app = FastAPI() を定義している
# そのため uvicorn のモジュールパスは "main:app"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
