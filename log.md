# 開発ログ（〜2025/10/27）

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

## 2025/10/27 の作業メモ

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
