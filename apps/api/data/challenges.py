"""
Fallback challenge definitions used when the dynamic planner cannot run.

The entries intentionally mirror the three challenge archetypes:
  1. Longest ride time within 24 hours.
  2. Most unique stops while returning to Hakata.
  3. City loop that touches every quadrant of Fukuoka city.
"""

from __future__ import annotations

from typing import TypedDict


class RestStop(TypedDict):
    at: str
    minutes: int
    suggestion: str


class Leg(TypedDict):
    sequence: int
    line_label: str
    line_name: str
    from_stop: str
    to_stop: str
    departure: str
    arrival: str
    ride_minutes: int
    distance_km: float
    notes: list[str]


class Challenge(TypedDict):
    id: str
    title: str
    tagline: str
    theme_tags: list[str]
    start_stop: str
    start_time: str
    total_ride_minutes: int
    total_distance_km: float
    transfers: int
    wards: list[str]
    badges: list[str]
    legs: list[Leg]
    rest_stops: list[RestStop]


CHALLENGES: list[Challenge] = [
    {
        "id": "longest-duration",
        "title": "24時間ロングライド",
        "tagline": "博多駅を軸にフリーパスだけで乗り続け、24時間で最長の乗車時間を稼ぐチャレンジ。",
        "theme_tags": ["時間最大化", "耐久"],
        "start_stop": "博多駅前A",
        "start_time": "07:00",
        "total_ride_minutes": 720,
        "total_distance_km": 128.4,
        "transfers": 6,
        "wards": ["博多区", "中央区", "南区", "早良区", "西区"],
        "badges": ["最長乗車"],
        "legs": [
            {
                "sequence": 1,
                "line_label": "300",
                "line_name": "都心快速 博多駅→天神",
                "from_stop": "博多駅前A",
                "to_stop": "天神北",
                "departure": "07:05",
                "arrival": "07:20",
                "ride_minutes": 15,
                "distance_km": 4.8,
                "notes": ["ウォームアップ区間"],
            },
            {
                "sequence": 2,
                "line_label": "W1",
                "line_name": "天神北→野芥駅前",
                "from_stop": "天神北",
                "to_stop": "野芥駅前",
                "departure": "07:30",
                "arrival": "08:03",
                "ride_minutes": 33,
                "distance_km": 13.6,
                "notes": ["都市高速利用", "中央区→早良区"],
            },
            {
                "sequence": 3,
                "line_label": "12",
                "line_name": "野芥駅前→片江営業所",
                "from_stop": "野芥駅前",
                "to_stop": "片江営業所",
                "departure": "08:10",
                "arrival": "08:37",
                "ride_minutes": 27,
                "distance_km": 9.3,
                "notes": ["丘陵部を縦断"],
            },
            {
                "sequence": 4,
                "line_label": "56-1",
                "line_name": "片江営業所→桧原営業所",
                "from_stop": "片江営業所",
                "to_stop": "桧原営業所",
                "departure": "08:50",
                "arrival": "09:10",
                "ride_minutes": 20,
                "distance_km": 7.1,
                "notes": ["城南区→南区"],
            },
            {
                "sequence": 5,
                "line_label": "51B",
                "line_name": "桧原営業所→那珂一丁目",
                "from_stop": "桧原営業所",
                "to_stop": "那珂一丁目",
                "departure": "09:25",
                "arrival": "10:03",
                "ride_minutes": 38,
                "distance_km": 12.0,
                "notes": ["南区→博多区"],
            },
            {
                "sequence": 6,
                "line_label": "110",
                "line_name": "博多駅→愛宕浜二丁目",
                "from_stop": "博多駅前B",
                "to_stop": "愛宕浜二丁目",
                "departure": "10:20",
                "arrival": "11:20",
                "ride_minutes": 60,
                "distance_km": 19.5,
                "notes": ["博多区→西区", "シーサイド区間"],
            },
        ],
        "rest_stops": [
            {
                "at": "天神北",
                "minutes": 8,
                "suggestion": "コンコースで朝コーヒーを入手。",
            },
            {
                "at": "愛宕浜二丁目",
                "minutes": 12,
                "suggestion": "海沿いのベンチでストレッチ。",
            },
        ],
    },
    {
        "id": "most-stops",
        "title": "ユニーク停留所コンプリート",
        "tagline": (
            "24時間以内にできるだけ多くの停留所を巡り、最後に博多へ戻る"
            "ストップハンティング。"
        ),
        "theme_tags": ["停留所制覇", "ルート探索"],
        "start_stop": "博多駅前A",
        "start_time": "07:00",
        "total_ride_minutes": 640,
        "total_distance_km": 102.0,
        "transfers": 7,
        "wards": ["博多区", "東区", "南区", "城南区", "早良区"],
        "badges": ["停留所ハンター"],
        "legs": [
            {
                "sequence": 1,
                "line_label": "29N",
                "line_name": "博多駅→香椎浜南公園前",
                "from_stop": "博多駅前A",
                "to_stop": "香椎浜南公園前",
                "departure": "07:05",
                "arrival": "07:45",
                "ride_minutes": 40,
                "distance_km": 14.0,
                "notes": ["新駅を連続取得"],
            },
            {
                "sequence": 2,
                "line_label": "21",
                "line_name": "香椎浜南公園前→土井営業所",
                "from_stop": "香椎浜南公園前",
                "to_stop": "土井営業所",
                "departure": "07:55",
                "arrival": "08:32",
                "ride_minutes": 37,
                "distance_km": 11.4,
                "notes": ["アイランドシティ経由"],
            },
            {
                "sequence": 3,
                "line_label": "90",
                "line_name": "土井営業所→大橋駅",
                "from_stop": "土井営業所",
                "to_stop": "大橋駅",
                "departure": "08:45",
                "arrival": "09:18",
                "ride_minutes": 33,
                "distance_km": 10.5,
                "notes": ["東区→南区"],
            },
            {
                "sequence": 4,
                "line_label": "47",
                "line_name": "大橋駅→別府駅前",
                "from_stop": "大橋駅",
                "to_stop": "別府駅前",
                "departure": "09:30",
                "arrival": "10:10",
                "ride_minutes": 40,
                "distance_km": 12.8,
                "notes": ["南区→城南区"],
            },
            {
                "sequence": 5,
                "line_label": "16",
                "line_name": "別府駅前→藤崎→室見駅前",
                "from_stop": "別府駅前",
                "to_stop": "室見駅前",
                "departure": "10:22",
                "arrival": "10:55",
                "ride_minutes": 33,
                "distance_km": 9.1,
                "notes": ["城南区→早良区"],
            },
        ],
        "rest_stops": [
            {
                "at": "香椎浜南公園前",
                "minutes": 10,
                "suggestion": "遊歩道で次のルートを確認。",
            },
            {
                "at": "大橋駅",
                "minutes": 8,
                "suggestion": "駅前ベーカリーで補給。",
            },
        ],
    },
    {
        "id": "city-loop",
        "title": "福岡市一周トレース",
        "tagline": "福岡市の北東・南東・南西・北西エリアをすべて踏んで博多へ戻る周回チャレンジ。",
        "theme_tags": ["シティループ", "周回"],
        "start_stop": "博多駅前A",
        "start_time": "07:00",
        "total_ride_minutes": 580,
        "total_distance_km": 95.2,
        "transfers": 5,
        "wards": ["博多区", "東区", "南区", "早良区", "西区"],
        "badges": ["周回達人"],
        "legs": [
            {
                "sequence": 1,
                "line_label": "23",
                "line_name": "博多駅→箱崎九大前",
                "from_stop": "博多駅前A",
                "to_stop": "箱崎九大前",
                "departure": "07:06",
                "arrival": "07:32",
                "ride_minutes": 26,
                "distance_km": 9.0,
                "notes": ["北東エリア到達"],
            },
            {
                "sequence": 2,
                "line_label": "74",
                "line_name": "箱崎九大前→土井営業所",
                "from_stop": "箱崎九大前",
                "to_stop": "土井営業所",
                "departure": "07:40",
                "arrival": "08:18",
                "ride_minutes": 38,
                "distance_km": 12.5,
                "notes": ["東区を横断"],
            },
            {
                "sequence": 3,
                "line_label": "41",
                "line_name": "土井営業所→那珂川市役所前",
                "from_stop": "土井営業所",
                "to_stop": "那珂川市役所前",
                "departure": "08:32",
                "arrival": "09:15",
                "ride_minutes": 43,
                "distance_km": 13.6,
                "notes": ["南東エリアへ"],
            },
            {
                "sequence": 4,
                "line_label": "13",
                "line_name": "那珂川市役所前→油山団地口",
                "from_stop": "那珂川市役所前",
                "to_stop": "油山団地口",
                "departure": "09:30",
                "arrival": "10:05",
                "ride_minutes": 35,
                "distance_km": 11.2,
                "notes": ["南西エリアへ登坂"],
            },
            {
                "sequence": 5,
                "line_label": "W3",
                "line_name": "油山団地口→藤崎→姪浜駅南口",
                "from_stop": "油山団地口",
                "to_stop": "姪浜駅南口",
                "departure": "10:18",
                "arrival": "11:07",
                "ride_minutes": 49,
                "distance_km": 16.4,
                "notes": ["西区沿岸を経由"],
            },
            {
                "sequence": 6,
                "line_label": "303",
                "line_name": "姪浜駅南口→博多駅",
                "from_stop": "姪浜駅南口",
                "to_stop": "博多駅前B",
                "departure": "11:20",
                "arrival": "12:05",
                "ride_minutes": 45,
                "distance_km": 16.5,
                "notes": ["北西→博多へ帰還"],
            },
        ],
        "rest_stops": [
            {
                "at": "那珂川市役所前",
                "minutes": 15,
                "suggestion": "河川沿いをウォークしてリセット。",
            },
            {
                "at": "姪浜駅南口",
                "minutes": 10,
                "suggestion": "ターミナルで軽食を確保。",
            },
        ],
    },
    {
        "id": "longest-distance",
        "title": "距離最長ツアー",
        "tagline": "24時間で博多を起終点に最長距離を駆け抜けるロングトリップ。",
        "theme_tags": ["距離最大化", "耐久"],
        "start_stop": "博多駅前A",
        "start_time": "07:00",
        "total_ride_minutes": 700,
        "total_distance_km": 140.0,
        "transfers": 7,
        "wards": ["博多区", "南区", "早良区", "西区", "東区"],
        "badges": ["最長距離"],
        "legs": [
            {
                "sequence": 1,
                "line_label": "300",
                "line_name": "博多駅→天神北",
                "from_stop": "博多駅前A",
                "to_stop": "天神北",
                "departure": "07:05",
                "arrival": "07:20",
                "ride_minutes": 15,
                "distance_km": 4.8,
                "notes": ["都会からスタート"],
            },
            {
                "sequence": 2,
                "line_label": "161",
                "line_name": "天神北→西新パレス前",
                "from_stop": "天神北",
                "to_stop": "西新パレス前",
                "departure": "07:30",
                "arrival": "08:05",
                "ride_minutes": 35,
                "distance_km": 13.8,
                "notes": ["都市高速経由で西区へ"],
            },
            {
                "sequence": 3,
                "line_label": "姪浜特急",
                "line_name": "西新パレス前→今宿駅前",
                "from_stop": "西新パレス前",
                "to_stop": "今宿駅前",
                "departure": "08:15",
                "arrival": "08:55",
                "ride_minutes": 40,
                "distance_km": 18.6,
                "notes": ["海沿いを一気に縦断"],
            },
        ],
        "rest_stops": [
            {
                "at": "今宿駅前",
                "minutes": 12,
                "suggestion": "海風を感じながら小休止。",
            }
        ],
    },
]
