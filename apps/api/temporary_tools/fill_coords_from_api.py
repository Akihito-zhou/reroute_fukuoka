# apps/api/tools/fill_coords_from_api.py
from __future__ import annotations
import os, sys, time, re, json
from typing import Optional, Dict, Any, List
import requests
import pandas as pd

BASE = os.path.dirname(__file__)
DATA_DIR = os.path.abspath(os.path.join(BASE, "..", "data"))

STATIONS_CSV = os.path.join(DATA_DIR, "stations.csv")
MISSING_CODES_CSV = os.path.join(
    DATA_DIR, "missing_station_codes.csv"
)  # 若存在则优先从这里读
OUT_CSV = STATIONS_CSV
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("MIXWAY_API_KEY") or os.getenv("EKISP_KEY") or ""
DETAIL_URL = "https://mixway.ekispert.jp/v1/json/point/detail"
STATION_URL = "https://mixway.ekispert.jp/v1/json/station"

# 兜底：如果没有文件，就用你贴的 code 列表（去重、排序）
DEFAULT_MISSING_CODES = [
    "306389",
    "304402",
    "306499",
    "306395",
    "306394",
    "305170",
    "306396",
    "309543",
    "309544",
    "307063",
    "307136",
    "674986",
    "674987",
    "674988",
    "674979",
    "674980",
    "674985",
    "674981",
    "677836",
    "675002",
    "674876",
    "674878",
    "674879",
    "675001",
    "674880",
    "674881",
    "675073",
    "306379",
    "306382",
    "306381",
    "306380",
    "306378",
    "306377",
    "305597",
    "674843",
    "674845",
    "674846",
    "674847",
    "674844",
]


def dms_to_deg(dms: str) -> Optional[float]:
    """
    把 "130.25.7.90" 这类度.分.秒字符串转换为十进制度。
    """
    if not isinstance(dms, str) or not dms.strip():
        return None
    parts = dms.split(".")
    if len(parts) != 4:
        return None
    try:
        deg, minu, sec, centi = map(float, parts)
        sec_all = sec + centi / 100.0
        return deg + minu / 60.0 + sec_all / 3600.0
    except Exception:
        return None


def fetch_point_detail(code: str) -> Optional[Dict[str, Any]]:
    """
    优先用 point/detail 获取 name、lati_d、longi_d；若无 d 值则用 dms 转换。
    """
    params = {"key": API_KEY, "code": code}
    try:
        r = requests.get(DETAIL_URL, params=params, timeout=15)
        r.raise_for_status()
        j = r.json()
        pt = j.get("ResultSet", {}).get("Point", {})
        st = pt.get("Station") or {}
        gp = pt.get("GeoPoint") or {}
        name = st.get("Name")
        lat = gp.get("lati_d")
        lon = gp.get("longi_d")
        # 回退：只给了 DMS
        if lat is None and gp.get("lati"):
            lat = dms_to_deg(gp["lati"])
        if lon is None and gp.get("longi"):
            lon = dms_to_deg(gp["longi"])
        # 有些罕见返回没有 name，再兜底 station 接口取 name
        if not name:
            name = fetch_station_name(code)
        return {"code": code, "name": name, "lat": lat, "lon": lon}
    except Exception as e:
        print(f"   ⚠️ point/detail 失败 code={code}: {e}")
        return None


def fetch_station_name(code: str) -> Optional[str]:
    if not API_KEY:
        return None
    try:
        r = requests.get(STATION_URL, params={"key": API_KEY, "code": code}, timeout=15)
        r.raise_for_status()
        j = r.json()
        pt = j.get("ResultSet", {}).get("Point", [{}])
        if isinstance(pt, list):
            pt = pt[0] if pt else {}
        st = pt.get("Station") or {}
        return st.get("Name")
    except Exception:
        return None


def load_missing_codes() -> List[str]:
    if os.path.exists(MISSING_CODES_CSV):
        df = pd.read_csv(MISSING_CODES_CSV)
        col = None
        for c in ["station_code", "code", "ekispert_station_code"]:
            if c in df.columns:
                col = c
                break
        if col:
            codes = [str(x).strip() for x in df[col].dropna().astype(str).tolist()]
            codes = sorted(set(codes))
            print(f"🧭 将从文件读取待补站点 {len(codes)} 个: {MISSING_CODES_CSV}")
            return codes
    codes = sorted(set(DEFAULT_MISSING_CODES))
    print(f"🧭 使用脚本内置待补站点 {len(codes)} 个")
    return codes


def main():
    if not API_KEY:
        print("❌ 未发现 MIXWAY_API_KEY / EKISP_KEY 环境变量")
        sys.exit(1)
    if not os.path.exists(STATIONS_CSV):
        print(f"❌ 未找到 stations.csv: {STATIONS_CSV}")
        sys.exit(1)

    st = pd.read_csv(STATIONS_CSV)
    # 自适应列名
    code_col = None
    for c in ["ekispert_station_code", "station_code", "code"]:
        if c in st.columns:
            code_col = c
            break
    if not code_col:
        print(
            f"❌ stations.csv 缺少 code 列（候选: ekispert_station_code/station_code/code）"
        )
        sys.exit(1)

    # 确保 name/lat/lon 列存在
    if "name" not in st.columns:
        st["name"] = None
    if "lat" not in st.columns:
        st["lat"] = None
    if "lon" not in st.columns:
        st["lon"] = None

    st[code_col] = st[code_col].astype(str)

    # 读取待补 codes
    codes = load_missing_codes()

    ok, fail = 0, 0
    for i, code in enumerate(codes, 1):
        print(f"[{i}/{len(codes)}] 取坐标 code={code} …")
        res = fetch_point_detail(code)
        time.sleep(0.25)  # 轻限速，避免触发风控
        if not res:
            fail += 1
            continue
        lat, lon, name = res["lat"], res["lon"], res["name"]

        # 若 stations.csv 没有这条 code，先补一行
        if not (st[code_col] == code).any():
            st = pd.concat(
                [
                    st,
                    pd.DataFrame(
                        [{code_col: code, "name": name, "lat": lat, "lon": lon}]
                    ),
                ],
                ignore_index=True,
            )
            ok += 1
            continue

        # 回写（仅填空，不覆盖已有值；如需强制覆盖，把 fillna 改成直接赋值）
        idx = st[st[code_col] == code].index
        if len(idx) == 0:
            fail += 1
            continue

        if name:
            st.loc[idx, "name"] = st.loc[idx, "name"].fillna(name)
        if lat is not None:
            st.loc[idx, "lat"] = st.loc[idx, "lat"].fillna(lat)
        if lon is not None:
            st.loc[idx, "lon"] = st.loc[idx, "lon"].fillna(lon)

        ok += 1

    st.to_csv(OUT_CSV, index=False)
    print(f"✅ 已回写 {ok} 条，失败 {fail} 条 → {OUT_CSV}")


if __name__ == "__main__":
    main()
