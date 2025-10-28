# 開発ログ（〜2025/10/28）

## 実装済み機能まとめ

- **バックエンド（apps/api）**
  - `main.py` / `routes.py`：FastAPI を起動し、`/api/v1/challenges` でチャレンジ一覧を返却。`PlannerService` が成功した場合は計算結果、失敗時はフォールバックの静的データを返す。
  - `schemas.py`：フロントエンドに渡すレスポンスの Pydantic スキーマ。
  - `services/planner.py`：駅データ（`stations.csv`）、フリーパス路線（`freepass_lines.yml`）、最新の時刻表（`timetable_*.csv`）を読み込み、時空間グラフを構築。3 種類のチャレンジ（24 時間最長乗車、ユニーク停留所最多、市内四象限ループ）を Beam Search ベースの探索で生成する。
  - `tools/` 配下の各スクリプト
    - `fetch_dump_stations.py`（既存）：Mixway から停留所情報を取得し `stations.csv` を生成。
    - `fetch_operation_lines.py`（既存）：`/search/course/extreme` を使って路線 ID と停留所列を推定し `lines_from_extreme.csv` / `line_stop_edges.csv` を生成。
    - `tag_freepass.py`：上記路線と福岡市 GeoJSON から「福岡市内フリーパス対象路線」を判定し `freepass_lines.yml` を出力。
    - `fetch_bus_timetable.py`：`line_stop_edges.csv` の各路線に対して首尾 2 停を from/to として `/v1/json/bus/timetable` を呼び、結果を `timetable_YYYYMMDD.csv` に保存（現状は始発・終点のみの時刻しか得られない）。

- **フロントエンド（apps/web）**
  - Vite + React + Tailwind。`App.tsx` が API のチャレンジ一覧を取得してカード表示。Framer Motion でアニメーションを付加。
  - Hero 部は「博多発 3 大チャレンジ（最長乗車／最多停留所／市内一周）」を説明。タグフィルタでテーマ絞り込み可。
  - 詳細パネルには `legs` と `rest_stops` を時系列で表示。

- **データファイル（apps/api/data）**
  - `stations.csv`：エキスパート停留所コード・名称・緯度経度。
  - `line_stop_edges.csv`：line_id ごとの停留所シーケンス。`fetch_bus_timetable.py` の from/to 推定にも使用。
  - `lines_from_extreme.csv`：路線 ID とサンプル名称・会社名。
  - `freepass_lines.yml`：福岡市内 24h フリーパス対象路線の判定結果。
  - `fukuoka_city.geojson`：福岡市境界。Planner が停留所を四象限に分ける際に利用。
  - `timetable_YYYYMMDD.csv`：外部 API から取得した時刻表。現状は始発／終点のみが記録されるため、詳細な乗換計画には不足。

## 現状の課題

1. **チャレンジ生成が「午前中」「短距離」に偏る**  
   - `fetch_bus_timetable.py` が from/to の組み合わせで路線全区間の出発・到着時刻のみ取得しているため、中間停留所の時刻が一切手に入っていない。  
   - その結果、`PlannerService` は実際の乗継を再現できず、フォールバックチャレンジ（静的モック）を返している。よって UI に表示されるルートは 6～8 区間の短い行程に固定されている。

2. **「ユニーク停留所最多」の要件未満**  
   - 実データの最長路探索が未稼働のため、実際には数十停留所しか含まれないモックを表示。CSV に含まれる数千停留所を探索に活かしきれていない。

3. **24 時間制約の判定が実質機能していない**  
   - グラフが構築できないので `START_TIME_MINUTES + 24h` まで進むケースが存在せず、結果的に「午前のみ」で終わるように見える。

4. **時刻表 API からの情報不足**  
   - `/bus/timetable` は `from` と `to` の 2 点間のみ返す仕様のため、中間停留所が欠落する。`operationLine/timetable` など別エンドポイントで全停留所の StopTime を取得する必要がある。

## 生成アルゴリズムの概要

1. **データ読み込み**  
   - `stations.csv` → code, name, lat/lon。  
   - `freepass_lines.yml` → フリーパス対象路線のみを探索対象に残す。  
   - 最新の `timetable_*.csv` → TripEdge（line_id, trip_id, from/to, depart/arrive）を生成。  
   - 四象限マッピング：緯度経度の中央値で NE/SE/SW/NW を割り当て、市内一周の達成判定に使用。

2. **時空間グラフ構築**  
   - 各停留所ごとに「発車時刻昇順の Edge リスト（StopSchedule）」を持たせる。  
   - Edge（TripEdge）: 同一 trip 内で隣接する停留所間の移動、乗車時間・距離を保持。  
   - 時刻は `datetime.strptime`＋日跨ぎ補正（rollover）で分単位に正規化。

3. **探索ロジック**  
   - Beam Search 形式。状態は `(現在停留所, 現在時刻, 累計乗車分, 訪問済み停留所集合, 四象限ビットマスク)`。  
   - 制約：出発は博多駅周辺停留所、`START_TIME`（07:00）から 24 時間以内。乗換バッファは 3 分。  
   - `score_key` に応じて評価関数を切替え:  
     - `ride`: 累計乗車分を最大化。  
     - `unique`: ユニーク停留所数を優先し、同点時に乗車分で比較。  
     - `loop`: 四象限の到達数を優先し、次に乗車分。  
   - 結果は TripEdge を連結し `LegPlan`（路線まとめ）へ圧縮した上で API に返却。

4. **フォールバック（現在表示されている状態）**  
   - Planner が例外を投げた場合、`data/challenges.py` の静的 3 ルートを返す。これが現在 UI に出ている「午前のみ」のルート。

## 今後の対応方針

- `/bus/timetable` ではなく `/v1/json/operationLine/timetable` など「停留所ごとの StopTime を返す」エンドポイントに切り替え、`timetable_*.csv` をフル区間の形で再生成する。  
- 生成した CSV を `PlannerService` に読み込ませ、実際の 24 時間探索を有効化する。  
- 四象限やユニーク停留所の判定が機能するかを改めて検証し、問題があれば Beam Search の枝刈りやペナルティ設定を調整する。  
- 生成結果が 24 時間全体に分布しているか、停留所数・距離が期待通りかを可視化（ログ出力や `log.md` の追記など）して共有する。

以上が 2025/10/26 時点での到達点と課題です。***

---

## 2025/10/27 

### ✅ 実装・改善
- **区間単位の時刻表取得に刷新**  
  `fetch_bus_timetable.py` を全面改修し、`line_stop_edges.csv` の隣接停留所ごとに `/v1/json/bus/timetable` を呼び出して区間（segment）単位のデータを生成。出力を `segments_YYYYMMDD.csv` に切り替え、全 683 路線について 2025-10-26 のデータを取得。
- **Planner の segments 対応**  
  `_find_latest_data_file()` で `segments_*.csv` を優先検出し、`_load_segment_edges()` を新設。区間データから `TripEdge` を直接生成し、StopSchedule を組み立てられるようにした。従来の `timetable_*.csv` もフォールバックとして残存。
- **スコアリングと探索パラメータの調整**  
  `_score_state()` に路線多様性ボーナスと重複ペナルティを導入。`MAX_QUEUE_SIZE` / `MAX_EXPANSIONS` を引き上げ、`_run_search()` に可変パラメータ（max_queue / max_expansions / max_branch）を追加。`_plan_city_loop()` では 2 段階のリトライを実装して四象限ループを拾いやすくした。
- **3種チャレンジ用テスト整備**  
  `tests/test_planner_segments.py` を作成し、segments 読み込み後に `_plan_longest_duration()` / `_plan_most_unique_stops()` / `_plan_city_loop()` をそれぞれ実行。各チャレンジの先頭 10 区間を標準出力し、フル結果を `debug_longest_duration.json` / `debug_most_unique.json` / `debug_city_loop.json` に保存するよう変更。
- **API レイヤの動作確認**  
  `service.list_challenges()` が fallback せず 3 ルートを返すことを確認。フロントエンド（`/api/v1/challenges`）からも最新チャレンジが取得可能に。

### 🔍 アルゴリズム挙動メモ
- 区間データから 24 時間ビームサーチを再実行すると、最長乗車ルートは 87 区間・522 分、ユニーク停留所ルートは 92 区間・439 分、市内ループは 89 区間・497 分を到達。各 JSON に全 legs を保存済み。
- 重複ペナルティ導入後も、一部の長距離便で往復が残る（特に `3597` 系統）。これは「乗車時間最大化」を最優先にしているためで、今後は区間別クールタイムや路線単位の出現上限を導入する余地あり。
- 市内ループは fallback で「四象限が 3 つでも許容」するよう緩和したため、現行データでは北西寄りのルートが選ばれやすい。象限バランスを調整するなら quadrant ごとの最低訪問回数を別途課す必要がある。

### ⚠️ 未解決・要改善ポイント
- **スタート時刻の上限設定**：segments を 24 時間ぶん取得しているため、07:00 以前に出発する区間も検索対象に残っている。`START_TIME_MINUTES` を基準に早朝便を除外するフィルタが必要。
- **探索コスト**：`MAX_EXPANSIONS` を大きくしたことで city-loop が成立したが、全探索で 20～30 秒かかるケースがある。キャッシュや事前アンカー指定で探索幅を減らす対策が必要。
- **ルート品質**：現状は距離や停留所の偏りを緩和するための制約が不足。以下を今後の候補とする。
  - 路線ごとのクールタイム／乗車回数上限。
  - 一定範囲内の停留所重複（徒歩圏内の同系列停留所）を同一扱いするルール。
  - 休憩ポイントや乗継余裕時間を評価に組み込む。
- **リアルタイム化**：segments を全路線で生成すると API 呼び出し数が大きいため、将来的には `--line_ids` + `--window` を使った部分更新、または pattern API によるオンデマンド補正が必要。

### 📎 チェックに使うコマンド
```bash
# 区間取得
python tools/fetch_bus_timetable.py --date 20251026 --limit 0 --sleep 0.3

# 3種チャレンジのテスト＆JSON出力
poetry run pytest -s tests/test_planner_segments.py

# API 経由でチェック
poetry run python - <<'PY'
from services.planner import PlannerService, PlannerError

service = PlannerService()
try:
    for plan in service.list_challenges():
        print(plan['id'], plan['total_ride_minutes'])
except PlannerError as exc:
    print('fallback:', exc)
PY
```

以上が 2025/10/27 の成果と残課題です。

---

## 2025/10/28

### 🔰 背景と到達点
- これまでの課題（短距離の静的モックしか返らない・実データ探索が成立しない）を踏まえ、**データ収集 → グラフ構築 → 探索 → API → フロント描画** の全工程を改めて整理し、欠落していたドキュメントを補完した。
- 特に「なぜ区間単位で時刻表を取得するのか」「探索ロジックの内部構造」「リアルタイム補正の流れ」「Leaflet による描画手順」といった暗黙知を明文化。

### 🚌 時刻表収集の全体像（0 → 100）
1. **種データ作成**  
   - `/v1/json/search/course/extreme` を使うツール（`tools/fetch_operation_lines.py`）で、代表ルートから路線 ID と停留所列を推定し `line_stop_edges.csv` を生成。  
   - 停留所位置は `/v1/json/station`（もしくは BC のバルク CSV）を `tools/fetch_dump_stations.py` で保存し `stations.csv` に集約。
2. **区間化の必然性**  
   - `/v1/json/bus/timetable` は **from・to を指定した区間** のみ返す API。全停留所の時刻表を得るには、路線上の隣接停留所ペアをすべて走査するしかない。  
   - 1 区間ずつ取得することで、trip_id ごとの厳密な出発・到着時刻、延着の有無を取りこぼさず収集できる。  
   - 各 API 呼び出しはキャッシュ（`tools/.cache_ttb`）に保存し、再実行時は 200 件超の再取得を避ける。  
3. **CSV 生成**  
   - `fetch_bus_timetable.py` は `(line_id, direction, service_date, from_stop, to_stop, depart, arrive, segment_id)` を縦持ちした `segments_YYYYMMDD.csv` を出力。trip_id が無い場合は `segment_id` を代替キーにする。  
   - これが Planner のグラフ入力となり、1 行 = 1 エッジ、として扱える。

### 🗺️ グラフ構築とデータ流通
- `PlannerService._load_segment_edges()` が `segments` CSV を読み込み `TripEdge` を生成。`TripEdge` には line 名・trip ID・前後停留所名・分単位の depart/arrive・距離（`haversine_km`）・緯度経度をすべて格納。  
- 同一停留所のエッジは `StopSchedule`（depart 昇順）に集約され、`bisect_left` で「指定時刻以降の便」を即座に引ける。  
- 連続する trip 内区間は `collapse_edges()` で 1 レグに圧縮し、レスポンスでは `geometry`（GeoJSON LineString）と `path`（lat/lon 配列）を両方提供。フロントはどちらでも描画可能。

### 🛰️ リアルタイム補正エンジン
- 環境変数 `PLANNER_ENABLE_REALTIME=true` と `EKISPERT_API_KEY=<mixway-key>` を指定すると、`EkispertBusClient` が `/v1/json/realtime/trip`・`/v1/json/realtime/search/course/extreme` 等にアクセス可能になる。  
- `RealtimeTimetableManager` は静的 `TripEdge` を保持しつつ、TTL（デフォ 120 秒）を超えたらリアルタイムを取得→区間別に `depart/arrive/status/delay` を上書き。キャンセル便は検索対象から除外。  
- 失敗時は静的データにフォールバックし、`routes.py` の `_debug_cache` で `debug_*.json` を返す仕組みも用意。こうして API は常に 3 ルートを提供できる。

### 🔍 探索アルゴリズム詳細
- **手法**：RAPTOR ではなく、課題に合わせた **Beam Search / Best First Search** を採用。  
  - 状態 `SearchState`：  
    ```
    priority（ヒープキー）, ride_minutes, current_time,
    stop_code, path(TripEdge 配列), visited(停留所集合),
    unique_count, quadrant_mask
    ```
  - 初期状態は博多駅周辺の複数停留所。`quadrant_mask` は市内を NE/SE/SW/NW の 4 象限に分けたビットフラグ。  
  - `priority` は `_score_state` が `score_key`（ride/unique/loop）に応じて決定。  
    - `ride`: 乗車分 + 路線多様性ボーナス − 重複路線ペナルティ。  
    - `unique`: ユニーク停留所数 × 1200 + 乗車分 + 路線多様性 ×12 − 重複 ×6。  
    - `loop`: 象限達成数×2000 + 乗車分 + 路線多様性 ×15 − 重複 ×4。  
  - 制約：キュー上限（既定 2000～5200）、分岐数（6～18）、最大展開回数、24 時間以内、乗換バッファ 3 分。  
  - 完了条件：パスが存在し、博多系停留所へ戻り、開始から 120 分以上経過。`loop` の場合は全象限達成で即打ち切り。
- **ヒューリスティック**：重複路線を罰するほか、象限未達成の場合は**初期遷移で同象限へ戻らないようスキップ**し、探索を外側へ広げる。  
- Beam Search を選んだ理由：RAPTOR は厳密最適性が強みだが、今回の 3 ルートは「耐久」「ユニーク」「象限」など複合スコアが目的で、Pareto 最適ではなくカスタム評価が必要だったため。

### 🗺️ フロント描画の実装ディテール
- スタック：React 18 + Vite + Tailwind + Framer Motion。  
- ルーティング：`react-router-dom` の `BrowserRouter` で `/`（概要）と `/challenge/:id`（詳細）を分離。  
- 地図：`react-leaflet` + CARTO Light タイル。  
  - `RouteMap` は `path` → `geometry.coordinates` → `from_coord/to_coord` の順で座標配列を決定し、`Polyline`（太さ 5）で leg ごとの折線を描画。  
  - `FitBounds` コンポーネントで全座標からバウンディングボックスを計算し、自動ズーム。  
  - `CircleMarker` でスタート（シアン）/ゴール（オレンジ）を表示。  
  - path が欠落している旧フォーマットにも対応するため、起終点しか無い場合は直線 2 点を生成して描画。

### ✅ データ検証と運用メモ
- `pytest apps/api/tests/test_planner_segments.py` で最新 CSV を用いたチャレンジ出力を再生成し、`debug_*.json` を更新。  
- `curl http://localhost:8000/api/v1/challenges/longest-duration | jq '.legs[0]'` で geometry/path の存在を確認。  
- Docker（`make up-dev`）起動時は API と Web がホットリロードするため、コード更新後は必ず `make down-dev && make up-dev` で再起動してキャッシュを更新する。

### 📌 今後の改善ポイント
- **データ収集**：バッチ取得の高速化、`/operationLine/timetable` など全停留所を返す API の再調査、`--line_ids` を使った差分更新。  
- **探索性能**：路線クールタイム、象限達成のヒューリスティック強化、RAPTOR/CSA へのリプレース検討、探索統計のメトリクス化。  
- **リアルタイム**：TTL の動的制御、複数 trip クエリのバッチング、API 失敗時のリトライ戦略強化、フォールバック検知ログ。  
- **UI**：区間ハイライト、 hover tooltip、行程の共有ボタン、i18n（日本語/中国語/英語）切り替え。  
- **テスト**：API の契約テスト・フロント E2E を追加し、リアルタイム補正時のリグレッションを検知できるようにする。

---
