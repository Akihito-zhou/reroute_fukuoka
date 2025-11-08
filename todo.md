## 简单/低代码任务 (Simple / Low-code Tasks)

*适合对项目算法和复杂逻辑不太熟悉的成员。*

1.  **数据验证与标注 (Data Validation & Annotation)**
    *   **任务**: `planner_cityloop.py` 在连接两个站点（`675300 -> 675318`）时失败了。请使用在线地图（如Google Maps）或福冈本地的公交查询App，手动查询这两个站点之间是否存在合理的公交路线。
    *   **交付**: 将查询结果（截图、路线文字描述）记录在 `log.md` 的新章节中，以判断这是数据问题还是算法问题。
    *   **技能**: 无需编程，只需使用地图和文档编辑。

2.  **文档完善 (Documentation Improvement)**
    *   **任务**: 为 `apps/api/data/` 目录下的核心数据文件（`stations.csv`, `line_stop_edges.csv`, `freepass_lines.yml`）创建一个 `README.md` 文件。
    *   **交付**: 在 `README.md` 中，为每个文件说明其用途、每一列的含义、以及数据的来源（例如，`stations.csv` 来自 `tools/fetch_dump_stations.py`）。
    *   **技能**: 文档写作，理解CSV文件格式。

3.  **前端UI优化 (Frontend UI Polish)**
    *   **任务**: 当前后端计算路线时，前端页面会卡住。请在 `apps/web/src/App.tsx` 中添加一个简单的加载动画或“计算中...”的提示。
    *   **交付**: 当用户点击“查看详情”或页面初次加载时，显示加载提示，直到从API获取到数据为止。
    *   **技能**: 基础的 React 和 CSS 知识。

---

## TODO（中文）- 2025/11/08

1. **数据说明整理**  
   - 为 `apps/api/data/` 下的 `stations.csv`、`line_stop_edges.csv`、`freepass_lines.yml`、`segments_*.csv` 等文件编写字段解释、来源与清洗流程说明。  
   - 为 `planner_explanation.md`、`log.md` 补充章节索引与更新时间，便于快速查找最新约束与测试结果。

2. **日志与监控脚本**  
   - 编写脚本统计 `planner.py` 运行期间的警告（如 “Stop sequence too short…”, “No path found…”），并输出涉及的 line_id、stop_code 及出现次数。  
   - 记录每次长测的耗时、内存占用等信息，整理成周报。

3. **数据一致性检查**  
   - 自动比对 `line_stop_edges.csv` 与 `segments_*.csv` 的停靠顺序，列出不一致的线路与缺失站点。  
   - 校验 `boundary_sequence` 中的站点是否全部存在于 `stations.csv`，生成异常列表。

4. **测试与结果记录**  
   - 定期运行 `poetry run pytest tests/test_raptor_diagnostics.py -s`，记录每个挑战的耗时、legs 数、quadrants、boundary_ratio 等指标并汇总成表格。  
   - 从 `apps/api/data/raptor_debug_*.json` 中提取关键信息，整理不同参数下的对比结果。

5. **站点与线路标签**  
   - 为重点换乘站、boundary 候选站撰写简短说明（客流、周边、可换乘线路），辅助后续权重打分。  
   - 依据公开资料或地图，为 City Loop 候选站制作可视化标注或截图。

6. **脚本与配置维护**  
   - 检查 `.env`、`Makefile`、Poetry/Pnpm 命令是否与最新流程一致，必要时更新。  
   - 为清缓存、单独运行挑战、导出 debug JSON 等常用操作编写 PowerShell/批处理脚本。

7. **算法与论文调研**  
   - RAPTOR/RAPTOR-family：阅读 Delling 等人的 RAPTOR 与 Trip-Based Routing 论文，整理剪枝与预处理思路。  
   - 图搜索优化：调研 OpenTripPlanner 2.x、Conveyal R5 等项目的多轮扫描与缓存策略，输出对比摘要。  
   - TSP/几何启发式：查阅 LKH、OR-Tools 等 2-opt/3-opt 改进方法，评估对 City Loop 的适用性。  
   - **参考文献**：  
     - D. Delling, T. Pajor, R. F. Werneck. *[Round-Based Public Transit Routing](https://www.microsoft.com/en-us/research/wp-content/uploads/2012/01/raptor_alenex.pdf)*. ALENEX 2012.  
     - Sascha Witt. *[Trip-Based Public Transit Routing](https://arxiv.org/abs/1504.07149)*. ESA 2015 (LNCS 9294, pp.1025-1036).  
     - D. L. Applegate, R. E. Bixby, V. Chvátal, W. J. Cook. *[The Traveling Salesman Problem: A Computational Study](https://books.google.com/books/about/The_Traveling_Salesman_Problem.html?id=zfIm94nNqPoC)*. Princeton University Press, 2006.  
     - S. Lin, B. W. Kernighan. *[An Effective Heuristic Algorithm for the Traveling-Salesman Problem](https://pubsonline.informs.org/doi/10.1287/opre.21.2.498)*. Operations Research, 1973.  
     - OpenTripPlanner 2.x 开发文档（多模式交通路由）：<https://docs.opentripplanner.org/>  
     - Conveyal R5 “Rapid Realistic Routing” 引擎 GitHub＋文档：<https://github.com/conveyal/r5>

8. **LLM / 启发式权重探索**  
   - 收集站点/线路的地理、客流、设施信息，整理成结构化表格，供后续 LLM 或规则模型使用。  
   - 试验 degree、boundary 距离、象限覆盖潜力等规则打分，统计筛选后线路数量，以评估复杂度下降空间。

---
## シンプルなタスク (Simple / Low-code Tasks)

*プロジェクトのアルゴリズムや複雑なロジックに不慣れなメンバー向けです。*

1.  **データ検証と注釈 (Data Validation & Annotation)**
    *   **タスク**: `planner_cityloop.py` が2つの停留所（`675300 -> 675318`）を接続する際に失敗しています。オンラインマップ（Google Mapsなど）や福岡のバス検索アプリを使い、この2停留所間に合理的なバス路線が存在するか手動で確認してください。
    *   **成果物**: これがデータの問題かアルゴリズムの問題かを判断するため、調査結果（スクリーンショット、路線のテキスト説明）を `log.md` の新しいセクションに記録してください。
    *   **スキル**: プログラミングは不要。地図アプリとドキュメント編集のスキルのみ。

2.  **ドキュメントの改善 (Documentation Improvement)**
    *   **タスク**: `apps/api/data/` ディレクトリにあるコアデータファイル（`stations.csv`, `line_stop_edges.csv`, `freepass_lines.yml`）のために、`README.md` ファイルを作成してください。
    *   **成果物**: `README.md` に、各ファイルの用途、各列の意味、データの取得元（例：`stations.csv` は `tools/fetch_dump_stations.py` から）を説明してください。
    *   **スキル**: ドキュメント作成、CSVファイル形式の理解。

3.  **フロントエンドUIの改善 (Frontend UI Polish)**
    *   **タスク**: 現在、バックエンドが経路を計算している間、フロントエンドの画面が固まってしまいます。`apps/web/src/App.tsx` に、簡単なローディングアニメーションか「計算中...」というテキスト表示を追加してください。
    *   **成果物**: ユーザーが「詳細を見る」をクリックした際や初回読み込み時に、APIからデータを取得するまでローディング表示が出るようにしてください。
    *   **スキル**: 基本的なReactとCSSの知識。

---

## TODO（日本語）- 2025/11/08

1. **データ説明の整備**  
   - `apps/api/data/` 配下の `stations.csv`、`line_stop_edges.csv`、`freepass_lines.yml`、`segments_*.csv` について、列の意味・入手元・前処理手順をまとめる。  
   - `planner_explanation.md` と `log.md` に目次や更新履歴を追加し、最新の制約やテスト結果を参照しやすくする。

2. **ログ監視スクリプト**  
   - `planner.py` 実行時の警告（例 “Stop sequence too short…”, “No path found…”）を集計し、line_id・stop_code・出現回数を一覧化する。  
   - 長時間テストの実行時間やメモリ使用量を記録し、週次レポートにまとめる。

3. **データ整合性チェック**  
   - `line_stop_edges.csv` と `segments_*.csv` の停車順を照合し、不一致の路線や欠損停留所を列挙する。  
   - `boundary_sequence` の停留所が `stations.csv` に存在するか検証し、異常リストを作る。

4. **テスト実行と結果集約**  
   - 定期的に `poetry run pytest tests/test_raptor_diagnostics.py -s` を実行し、各チャレンジの実行時間・legs 数・quadrants・boundary_ratio などを表に整理する。  
   - `apps/api/data/raptor_debug_*.json` から主要指標を抜き出し、パラメータ変更による差分を可視化する。

5. **停留所・路線のタグ付け**  
   - 主要な乗換停留所や境界候補について、利用状況・周辺環境・乗換可能路線を短くまとめる。  
   - City Loop 候補停留所を地図やスクリーンショットで可視化する。

6. **スクリプト／設定メンテナンス**  
   - `.env`、`Makefile`、Poetry/Pnpm コマンドが現行フローに合っているか確認し、必要に応じて更新する。  
   - キャッシュクリア、チャレンジ単体実行、debug JSON 出力などを自動化する PowerShell/バッチスクリプトを整備する。

7. **アルゴリズム・論文調査**  
   - RAPTOR 系文献（Delling ら）の読解と、支配判定・前処理アイデアの整理。  
   - OpenTripPlanner 2.x、Conveyal R5 などの実装を調べ、multi-round 最適化やキャッシュ戦略を比較。  
   - LKH、OR-Tools など 2-opt/3-opt 改善を調査し、City Loop への適用可否を検討。  
   - **参考文献**：  
     - D. Delling, T. Pajor, R. F. Werneck. *[Round-Based Public Transit Routing](https://www.microsoft.com/en-us/research/wp-content/uploads/2012/01/raptor_alenex.pdf)*. ALENEX 2012.  
     - Sascha Witt. *[Trip-Based Public Transit Routing](https://arxiv.org/abs/1504.07149)*. ESA 2015 (LNCS 9294, pp.1025-1036).  
     - D. L. Applegate, R. E. Bixby, V. Chvátal, W. J. Cook. *[The Traveling Salesman Problem: A Computational Study](https://books.google.com/books/about/The_Traveling_Salesman_Problem.html?id=zfIm94nNqPoC)*. Princeton University Press, 2006.  
     - S. Lin, B. W. Kernighan. *[An Effective Heuristic Algorithm for the Traveling-Salesman Problem](https://pubsonline.informs.org/doi/10.1287/opre.21.2.498)*. Operations Research, 1973.  
     - OpenTripPlanner 2.x 開発ドキュメント（マルチモーダル経路探索）：<https://docs.opentripplanner.org/>  
     - Conveyal R5 “Rapid Realistic Routing” エンジン GitHub／ドキュメント：<https://github.com/conveyal/r5>

8. **LLM・ヒューリスティック重み付け**  
   - 停留所／路線の地理・需要・設備情報を収集し、LLM やルールモデルで扱える表形式に整える。  
   - 度数、境界までの距離、象限カバレッジなどの指標で重み付けし、フィルター後の路線数を記録して複雑度削減効果を確認する。