# planner.py 功能说明

`planner.py` 这个文件是整个路径规划功能的核心。它的主要任务是根据福冈地区的巴士线路、站点和时刻表数据，计算出满足特定“挑战”目标的最佳乘车方案。

这个文件代码比较长，功能也比较复杂。简单来说，它实现了一个高性能的公交路径规划引擎，但它寻找的不是“最快”的路线，而是满足特殊目标的“最佳”路线，例如“乘坐时间最长”、“经过最多不同站点”等。

下面我将为你详细讲解它的主要构成和各个函数的功能。

### 整体功能

`planner.py` 的核心是一个名为 `PlannerService` 的类。这个服务负责：
1.  **加载和处理数据**：从项目中的 `apps/api/data/` 目录加载所有必需的数据，包括站点信息 (`stations.csv`)、线路信息 (`freepass_lines.yml`)、时刻表 (`timetable_*.csv` 或 `segments_*.csv`) 和地理边界数据。
2.  **支持实时数据**：能够通过 `RealtimeTimetableManager` 从外部 API (Ekispert) 获取实时公交数据，使规划结果更准确。如果实时数据不可用，则会回退到使用静态的时刻表文件。
3.  **实现多种规划算法**：内置了两种主要的路径搜索算法：
    *   **RAPTOR 算法** (`_run_raptor_challenge`)：一种先进的、为公交网络优化的路径规划算法，用于高效地计算多轮换乘的复杂行程。
    *   **A\* 搜索算法** (`_run_search`)：作为备用方案。当 RAPTOR 算法找不到有效路径时，会启用这个经典的启发式搜索算法。
4.  **定义和计算“挑战”**：定义了四种不同的挑战，每种挑战都有独特的计分和优化逻辑，以找出符合特定目标的最佳路径。
5.  **缓存结果**：计算出的挑战方案会被缓存起来，以提高后续请求的响应速度。

---

### 主要构成和函数作用

#### 1. 数据类 (Data Classes)

文件开头定义了大量的 `dataclass`，用于以结构化的方式存储数据，例如：

*   `Station`: 代表一个公交站点，包含站点编码、名称和经纬度。
*   `TripEdge`: 代表公交网络中的一条“边”，即一次从A站到B站的直达行程。包含线路、出发/到达时间、距离等信息。
*   `LegPlan`: 代表最终方案中的一个“路段”，即一次完整的乘车（可能跨越多站）。
*   `Label`: 在 RAPTOR 算法中使用，代表一条到达某个站点的潜在路径。它包含了路径的所有关键指标（如总耗时、距离、访问过的站点集合等），是算法进行剪枝和优化的核心。
*   `ChallengeConfig`: 每种挑战的配置，定义了该挑战的计分函数、优化目标和各种约束（如最小换乘时间、最大重复访问次数等）。
*   `ChallengePlan`: 最终生成的、完整的挑战方案，包含了所有路段的详细信息。

#### 2. `PlannerService` 类

这是最重要的类，几乎所有功能都在这个类的方法中实现。

*   `__init__(self, ...)`: **构造函数**
    *   **作用**: 初始化 `PlannerService` 实例。
    *   **参数**:
        *   `data_dir`: 数据文件所在的目录路径。
        *   `enable_realtime`: 是否启用实时数据功能。
        *   `api_key`: 访问实时数据 API 所需的密钥。
        *   `realtime_cache_seconds`: 实时数据缓存的有效时间。

*   `list_challenges(self)` 和 `get_challenge(self, challenge_id)`: **公共接口**
    *   **作用**: 这是提供给外部调用的主要接口。`list_challenges` 返回所有已计算好的挑战方案摘要，`get_challenge` 根据 `challenge_id` 返回特定挑战的详细方案。

*   `_ensure_plans(self)`: **数据加载与缓存管理**
    *   **作用**: 确保所有挑战方案都已计算并是最新状态。它会检查数据文件是否有更新或实时缓存是否过期，如果需要，就触发重新加载和重新计算。

*   `_load_static_assets(self)`: **加载静态资源**
    *   **作用**: 加载所有基础数据，如站点、线路、地理分区等。只在服务启动或数据文件更新时执行一次。

*   `_load_edges(self, data_path)`: **加载时刻表/路段数据**
    *   **作用**: 从 `timetable_*.csv` 或 `segments_*.csv` 文件中读取所有的公交行程（`TripEdge`），这是路径规划的基础。

*   `_build_route_timetables(self)`: **构建线路时刻表**
    *   **作用**: 将加载的 `TripEdge` 数据按“线路+方向”进行组织，构建成 `RouteData` 结构。这个结构为 RAPTOR 算法提供了按线路进行快速查询的视图。

*   `_run_raptor_challenge(self, config)`: **RAPTOR 算法核心**
    *   **作用**: 运行 RAPTOR 算法来解决指定的挑战。它通过多轮迭代（每一轮代表一次换乘）来扩展搜索。在每个站点，它会保留一组最优的 `Label`（路径），并使用 `dominance_fn`（支配函数）来淘汰劣势路径，从而控制搜索空间。
    *   **参数**:
        *   `config`: `ChallengeConfig` 对象，定义了当前挑战的目标和约束。

*   `_config_*` 系列函数 (例如 `_config_longest_duration`)
    *   **作用**: 为每一种挑战（如“最长乘车时间”、“最多站点”）创建一个 `ChallengeConfig` 配置对象。每个函数内部定义了该挑战专属的 `scoring_fn` (计分函数)、`dominance_fn` (支配函数) 和 `accept_fn` (接受函数)，这些函数是指导 RAPTOR 算法找到正确方向的关键。

*   `_label_metrics(self, label)`: **路径指标计算**
    *   **作用**: 这是一个非常重要的辅助函数，用于计算一个 `Label`（路径）的各种量化指标。例如，它会计算路径覆盖的地理区域面积 (`hull_area`)、访问站点的平均半径 (`avg_radius`)、在城市边界附近的比例 (`boundary_ratio`) 等。这些指标随后被 `scoring_fn` 用来给路径打分。

*   `_compute_challenges(self)`: **计算所有挑战**
    *   **作用**: 调用上述的规划函数 (`_plan_*`) 来计算所有四种挑战，并将结果整合到一个字典中。

*   `_plan_*_beam(self)` 和 `_run_search(...)`: **备用 A\* 搜索算法**
    *   **作用**: 当 RAPTOR 算法因为某些原因（例如约束过于严格）未能找到解决方案时，系统会调用这些函数来执行 A\* 搜索。A\* 是一种启发式搜索，虽然可能比 RAPTOR 慢，但能保证找到一条路径。
    *   **参数**:
        *   `score_key`: 定义了 A\* 搜索的优化目标（例如 `'ride'` 表示优化乘坐时间）。
        *   `require_unique`: 是否要求访问的站点是唯一的。
        *   `require_quadrants`: 是否要求必须访问所有四个地理分区。

### 总结

`planner.py` 文件实现了一个功能强大且复杂的公交路径规划系统。它不仅仅是找路，而是通过精巧的算法（RAPTOR 和 A\*）、详细的数据模型和灵活的配置，去解决一系列带有特殊优化目标的“寻路谜题”。每个函数和数据结构都为了这个最终目标而服务。

---

## `services/` 目录职责与调用链

- **`planner_constants.py`**：集中维护时间窗口、换乘缓冲、RAPTOR 扫描次数等常量，`PlannerService`、`raptor.py` 与 `planners/*` 共用一套阈值，方便统一调参。  
- **`planner_models.py`**：提供 `Station`、`TripEdge`、`RouteData`、`ChallengeConfig`、`Label` 等数据结构，确保路网构建、RAPTOR、TSP、结果序列化之间类型一致。  
- **`planner_loader.py`**：封装 CSV/YAML/GeoJSON 加载、TripEdge 构造、boundary 检测、实时数据刷新；`_load_static_assets`、`_load_edges`、`_refresh_stop_schedules` 均通过此模块工作。  
- **`planner_utils.py`**：实现距离/投影/凸包/象限计算及 `label_leg_to_plan` 转换，RAPTOR 和 Simple RAPTOR 重复使用这些工具函数。  
- **`raptor.py`**：包含 `run_raptor_challenge` 与 `_label_metrics`，与 `PlannerService` weak coupling，通过 `ChallengeConfig` 注入目标与约束。  
- **`planner_cityloop.py`**：实现 TSP + Simple RAPTOR 组合（候选巡回生成、分段调用 `run_simple_raptor`、汇总 `LegPlan`），供 `planners/city_loop.py` 优先调用。  
- **`realtime_timetable.py` / `RealtimeTimetableManager`**：对接 Ekispert API、维护缓存并回写 `_refresh_stop_schedules`；若无实时数据则退回静态 TripEdge。  
- **`planners/` 子目录**：`longest_duration.py` 等模块通过 `get_config` / `plan` 封装不同的评分函数与约束组合，实际求解仍复用 `run_raptor_challenge` 或 `plan_city_loop_tsp`。  
- **`services/__init__.py`**：统一导出 `PlannerService`、`PlannerError`、`planner_loader` 等，以便 API 层与测试用同一入口。

### 调用顺序（数据→算法→结果）
1. **初始化**：`PlannerService.__init__` 记录数据目录、实时开关、API Key。  
2. **加载静态资源**：`_ensure_plans` 检查缓存 → `_load_static_assets` 读取站点/线路/边界 → `_load_edges` 解析 segments/timetable 为 TripEdge。  
3. **构建路网**：`_refresh_stop_schedules` 生成 `StopSchedule`；`_build_route_timetables` 归并为 `RouteData` / `routes_by_stop`；`planner_loader.build_boundary_sequence` 生成城市边界站序。  
4. **执行挑战**：`_compute_challenges` 调用各 `planners/*`：  
   - Longest Duration / Most Stops / Longest Distance → `run_raptor_challenge`（若失败 fallback 到 `_plan_*_beam`）。  
   - City Loop → `planner_cityloop.plan_city_loop_tsp`（基于 Simple RAPTOR）；无解时再以 `planners/city_loop.get_config` 驱动 RAPTOR。  
5. **封装输出**：`label_leg_to_plan` 生成 `LegPlan`，`ChallengePlan` 按需缓存并写入 `apps/api/data/raptor_debug_*.json`，供 API (`list_challenges` / `get_challenge`) 返回给前端。

---
---

# planner.py 機能説明

`planner.py`ファイルは、経路探索機能全体のコアです。その主なタスクは、福岡地域のバス路線、停留所、時刻表データに基づき、特定の「チャレンジ」目標を達成するための最適な乗車プランを計算することです。

このファイルはコードが長く、機能も比較的複雑です。簡単に言うと、高性能な公共交通機関の経路探索エンジンを実装していますが、それは「最速」経路を探すのではなく、「乗車時間が最長」、「通過したユニークな停留所数が最多」など、特殊な目標を達成するための「最適」な経路を探します。

以下に、その主な構成と各関数の機能について詳しく説明します。

### 全体的な機能

`planner.py`のコアは`PlannerService`というクラスです。このサービスは以下の役割を担います：
1.  **データの読み込みと処理**：プロジェクトの`apps/api/data/`ディレクトリから、停留所情報（`stations.csv`）、路線情報（`freepass_lines.yml`）、時刻表（`timetable_*.csv`または`segments_*.csv`）、地理的境界データなど、必要なすべてのデータを読み込みます。
2.  **リアルタイムデータのサポート**：`RealtimeTimetableManager`を介して外部API（Ekispert）からリアルタイムのバス運行データを取得し、計画結果の精度を高めることができます。リアルタイムデータが利用できない場合は、静的な時刻表ファイルを使用するフォールバック机制があります。
3.  **複数の探索アルゴリズムの実装**：主に2つの経路探索アルゴリズムが組み込まれています：
    *   **RAPTORアルゴリズム** (`_run_raptor_challenge`)：公共交通ネットワーク向けに最適化された先進的な経路探索アルゴリズムで、複数回の乗り換えを伴う複雑な旅程を効率的に計算します。
    *   **A\*探索アルゴリズム** (`_run_search`)：バックアッププランとして機能します。RAPTORアルゴリズムが有効な経路を見つけられなかった場合に、この古典的なヒューリスティック探索アルゴリズムが使用されます。
4.  **「チャレンジ」の定義と計算**：4つの異なるチャレンジを定義し、それぞれに独自のスコアリングロジックと最適化目標があり、特定の目的に合った最適な経路を見つけ出します。
5.  **結果のキャッシュ**：計算されたチャレンジプランはキャッシュされ、後続のリクエストに対する応答速度を向上させます。

---

### 主な構成と関数の役割

#### 1. データクラス (Data Classes)

ファイルの冒頭では、構造化された方法でデータを格納するために多数の`dataclass`が定義されています。例：

*   `Station`: バス停留所を表し、停留所コード、名称、緯度経度を含みます。
*   `TripEdge`: 公共交通ネットワーク内の「エッジ」を表し、A停留所からB停留所への一度の直行移動を指します。路線、出発/到着時刻、距離などの情報を含みます。
*   `LegPlan`: 最終的なプランにおける一つの「区間」を表し、一回の完全な乗車（複数の停留所をまたぐことがある）を指します。
*   `Label`: RAPTORアルゴリズムで使用され、ある停留所に到達するための潜在的な経路を表します。経路のすべての主要な指標（総所要時間、距離、訪問済み停留所の集合など）を保持し、アルゴリズムが枝刈りや最適化を行うためのコアとなります。
*   `ChallengeConfig`: 各チャレンジの設定で、そのチャレンジのスコアリング関数、最適化目標、および様々な制約（最小乗り換え時間、最大重複訪問回数など）を定義します。
*   `ChallengePlan`: 最终的に生成される、完全なチャレンジプランで、すべての区間の詳細情報を含みます。

#### 2. `PlannerService` クラス

これが最も重要なクラスであり、ほぼすべての機能がこのクラスのメソッド内で実装されています。

*   `__init__(self, ...)`: **コンストラクタ**
    *   **役割**: `PlannerService`インスタンスを初期化します。
    *   **引数**:
        *   `data_dir`: データファイルが格納されているディレクトリのパス。
        *   `enable_realtime`: リアルタイムデータ機能を有効にするかどうか。
        *   `api_key`: リアルタイムデータAPIにアクセスするために必要なキー。
        *   `realtime_cache_seconds`: リアルタイムデータのキャッシュ有効期間。

*   `list_challenges(self)` と `get_challenge(self, challenge_id)`: **公開インターフェース**
    *   **役割**: 外部から呼び出される主要なインターフェースです。`list_challenges`は計算済みのすべてのチャレンジプランの要約を返し、`get_challenge`は`challenge_id`に基づいて特定のチャレンジの詳細なプランを返します。

*   `_ensure_plans(self)`: **データ読み込みとキャッシュ管理**
    *   **役割**: すべてのチャレンジプランが計算済みで最新の状態であることを保証します。データファイルの更新やリアルタイムキャッシュの期限切れをチェックし、必要であれば再読み込みと再計算をトリガーします。

*   `_load_static_assets(self)`: **静的リソースの読み込み**
    *   **役割**: 停留所、路線、地理的区分など、すべての基本データを読み込みます。サービスの起動時やデータファイルが更新されたときに一度だけ実行されます。

*   `_load_edges(self, data_path)`: **時刻表/区間データの読み込み**
    *   **役割**: `timetable_*.csv`または`segments_*.csv`ファイルからすべてのバスの行程（`TripEdge`）を読み取ります。これは経路探索の基礎となります。

*   `_build_route_timetables(self)`: **路線時刻表の構築**
    *   **役割**: 読み込んだ`TripEdge`データを「路線＋方向」で整理し、`RouteData`構造を構築します。この構造は、RAPTORアルゴリズムが路線ごとに高速なクエリを実行するために使用されます。

*   `_run_raptor_challenge(self, config)`: **RAPTORアルゴリズムのコア**
    *   **役割**: 指定されたチャレンジを解決するためにRAPTORアルゴリズムを実行します。複数回のイテレーション（各イテレーションが1回の乗り換えに相当）を通じて探索を拡大します。各停留所で、最適ないくつかの`Label`（経路）を保持し、`dominance_fn`（支配関数）を使用して劣った経路を排除し、探索空間を制御します。
    *   **引数**:
        *   `config`: `ChallengeConfig`オブジェクトで、現在のチャレンジの目標と制約を定義します。

*   `_config_*` シリーズの関数 (例: `_config_longest_duration`)
    *   **役割**: 各チャレンジ（例：「最長乗車時間」、「最多停留所」）ごとに`ChallengeConfig`設定オブジェクトを作成します。各関数の内部で、そのチャレンジ専用の`scoring_fn`（スコアリング関数）、`dominance_fn`（支配関数）、`accept_fn`（受理関数）が定義されており、これらがRAPTORアルゴリズムを正しい方向に導く鍵となります。

*   `_label_metrics(self, label)`: **経路メトリクスの計算**
    *   **役割**: `Label`（経路）の様々な定量的メトリクスを計算するための非常に重要な補助関数です。例えば、経路がカバーする地理的領域の面積（`hull_area`）、訪問した停留所の平均半径（`avg_radius`）、都市の境界付近にいる割合（`boundary_ratio`）などを計算します。これらのメトリクスは、`scoring_fn`によって経路のスコア付けに使用されます。

*   `_compute_challenges(self)`: **すべてのチャレンジを計算**
    *   **役割**: 上記の探索関数（`_plan_*`）を呼び出して、4種類すべてのチャレンジを計算し、結果を辞書にまとめます。

*   `_plan_*_beam(self)` と `_run_search(...)`: **バックアップのA\*探索アルゴリズム**
    *   **役割**: RAPTORアルゴリズムが何らかの理由（例えば制約が厳しすぎるなど）で解を見つけられなかった場合に、これらの関数が呼び出されてA\*探索を実行します。A\*はヒューリスティック探索であり、RAPTORより遅いかもしれませんが、経路を見つけることを保証します。
    *   **引数**:
        *   `score_key`: A\*探索の最適化目標を定義します（例：`'ride'`は乗車時間の最適化）。
        *   `require_unique`: 訪問する停留所がユニークであることを要求するかどうか。
        *   `require_quadrants`: 4つすべての地理的区分を訪問する必要があるかどうか。

### まとめ

`planner.py`ファイルは、強力かつ複雑な公共交通機関の経路探索システムを実装しています。単に道を探すだけでなく、洗練されたアルゴリズム（RAPTORとA\*）、詳細なデータモデル、柔軟な設定を通じて、特殊な最適化目標を持つ一連の「探索パズル」を解決します。各関数とデータ構造は、すべてこの最終目標のために機能しています。

## `services` ディレクトリの役割と呼び出しチェーン

- **`planner_constants.py`**：時間窓・乗換バッファ・RAPTOR ラウンド数などの定数を集中管理し、`PlannerService` / `raptor.py` / `planners/*` が同じ値を参照できるようにする。  
- **`planner_models.py`**：`Station`、`TripEdge`、`RouteData`、`ChallengeConfig`、`Label` などのデータ構造を定義し、ネットワーク構築〜RAPTOR〜TSP〜出力整形まで一貫した型を提供。  
- **`planner_loader.py`**：CSV/YAML/GeoJSON の読み込み、TripEdge 生成、境界シーケンス検出、リアルタイム更新を担当し、`_load_static_assets` `_load_edges` `_refresh_stop_schedules` の実体作業を受け持つ。  
- **`planner_utils.py`**：距離計算、平面投影、凸包・象限メトリクス、`label_leg_to_plan` などのユーティリティを提供し、RAPTOR と Simple RAPTOR の両方から利用される。  
- **`raptor.py`**：`run_raptor_challenge` と `_label_metrics` を実装したアルゴリズム層で、`ChallengeConfig` を渡すだけでプランを得られる。  
- **`planner_cityloop.py`**：TSP + Simple RAPTOR のハイブリッド戦略を実装し、City Loop チャレンジで最初に呼び出される。  
- **`realtime_timetable.py` / `RealtimeTimetableManager`**：Ekispert API との連携・キャッシュ管理を担い、必要なら `_refresh_stop_schedules` へ最新 TripEdge を供給。  
- **`planners/` 配下**：`longest_duration.py` などが `get_config` / `plan` を実装し、目標ごとにスコア関数・制約セットを切り替えつつ RAPTOR / Simple RAPTOR を再利用。  
- **`services/__init__.py`**：`PlannerService` と主要型をエクスポートし、FastAPI 層やテストが同一の import 経路を使えるようにする。

### 呼び出しフロー
1. **初期化**：`PlannerService.__init__` がデータパスとリアルタイム設定を受け取る。  
2. **静的ロード**：`_ensure_plans` がキャッシュを確認し、必要なら `_load_static_assets` → `_load_edges` を実行。  
3. **ネットワーク構築**：`_refresh_stop_schedules` で停留所スケジュールを生成し、`_build_route_timetables` が `RouteData`/`routes_by_stop` を組み立て、`build_boundary_sequence` が City Loop 用境界列を作成。  
4. **チャレンジ計算**：`_compute_challenges` が各 `planners/*` を呼び、Longest Duration/Most Stops/Longest Distance は RAPTOR（必要なら `_plan_*_beam` へフォールバック）、City Loop は TSP+Simple RAPTOR → RAPTOR の順に試す。  
5. **結果整形**：`label_leg_to_plan` で `LegPlan` を生成し、`ChallengePlan` を API (`list_challenges` / `get_challenge`) に返しつつ、デバッグ用 JSON も出力する。
