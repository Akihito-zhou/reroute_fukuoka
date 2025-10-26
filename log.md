# 開発ログ（〜2025/10/26）

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
