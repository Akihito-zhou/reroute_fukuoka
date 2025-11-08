from __future__ import annotations

from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"  # 数据目录 / データ保存場所
TIMETABLE_PREFIX = "timetable_"  # 时刻表文件前缀 / ダイヤCSVの接頭辞
SEGMENTS_PREFIX = "segments_"  # 片段文件前缀 / セグメントCSVの接頭辞

START_TIME_MINUTES = 7 * 60  # 默认开始时间07:00 / デフォルト開始時刻07:00
TRANSFER_BUFFER_MINUTES = 3  # 最小换乘缓冲 / 乗換最低待機時間
MAX_BRANCH_PER_EXPANSION = 6  # Beam搜索分支上限 / ビーム探索の分岐数
MAX_QUEUE_SIZE = 2000  # 优先队列容量 / 優先度キュー上限
MAX_EXPANSIONS = 120000  # 搜索扩展步数 / 探索ステップ上限
REST_STOP_THRESHOLD = 15  # 触发休息建议的等待分钟 / 休憩提案を出す待ち時間
DEFAULT_REALTIME_CACHE_SECONDS = 120  # 实时API缓存秒数 / リアルタイムAPIキャッシュ秒
MAX_LABELS_PER_STOP = 6  # 每站保留的标签数 / 各停留所のラベル保持数
MAX_TRANSFERS = 50  # RAPTOR允许的换乘轮数 / RAPTORの最大ラウンド
ALL_QUADRANTS_MASK = 1 | 2 | 4 | 8  # 四象限全覆盖位掩码 / 4象限制覇ビット
BOUNDARY_BIN_COUNT = 18  # 边界角度分桶 / 境界角度ビン数
BOUNDARY_MIN_DIST_KM = 0.3  # 视为边界站的最小距离 / 境界候補の最小距離
BOUNDARY_MAX_DIST_KM = 4.0  # 视为边界站的最大距离 / 境界候補の最大距離
MAX_ROUTES_FOR_RAPTOR = 400  # 预加载线路数 / 事前構築する路線
MAX_TRIPS_PER_ROUTE = 60  # 每线路保留班次数 / 路線あたりの便数

REST_SUGGESTIONS = [
    "コンビニで飲み物を補給しよう",
    "近くのベーカリーでテイクアウトを",
    "周辺を5分だけ散策して気分転換を",
    "ベンチで次のルートを確認しよう",
    "軽くストレッチしてリフレッシュ",
]

__all__ = [
    "DATA_DIR",
    "TIMETABLE_PREFIX",
    "SEGMENTS_PREFIX",
    "START_TIME_MINUTES",
    "TRANSFER_BUFFER_MINUTES",
    "MAX_BRANCH_PER_EXPANSION",
    "MAX_QUEUE_SIZE",
    "MAX_EXPANSIONS",
    "REST_STOP_THRESHOLD",
    "DEFAULT_REALTIME_CACHE_SECONDS",
    "MAX_LABELS_PER_STOP",
    "MAX_TRANSFERS",
    "ALL_QUADRANTS_MASK",
    "BOUNDARY_BIN_COUNT",
    "BOUNDARY_MIN_DIST_KM",
    "BOUNDARY_MAX_DIST_KM",
    "MAX_ROUTES_FOR_RAPTOR",
    "MAX_TRIPS_PER_ROUTE",
    "REST_SUGGESTIONS",
]
