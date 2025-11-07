# apps/api/tools/find_missing_station_coords.py
from __future__ import annotations

import os

import pandas as pd

BASE = os.path.dirname(__file__)
DATA_DIR = os.path.abspath(os.path.join(BASE, "..", "data"))

stations_csv = os.path.join(DATA_DIR, "stations.csv")
edges_csv = os.path.join(DATA_DIR, "line_stop_edges.csv")
meta_csv = os.path.join(DATA_DIR, "lines_from_extreme.csv")

print(f"📄 stations: {stations_csv}")
print(f"📄 edges   : {edges_csv}")
print(f"📄 meta    : {meta_csv}")


def pick_col(df, candidates, required=False):
    for c in candidates:
        if c in df.columns:
            return c
    if required:
        raise KeyError(
            f"需要的列没找到，候选：{candidates}，实际列：{list(df.columns)}"
        )
    return None


# 读取
st = pd.read_csv(stations_csv)  # 期望: ekispert_station_code,name,lat,lon
edges = pd.read_csv(edges_csv)  # 常见: line_id, station_code, stop_order/seq/order...
meta = pd.read_csv(meta_csv)  # 常见: line_id, line_name/name/TypicalName...

# ==== 自适应列名 ====
st_code_col = pick_col(
    st, ["ekispert_station_code", "station_code", "code"], required=True
)
st_name_col = pick_col(st, ["name", "station_name", "Name"]) or "name"
st_lat_col = pick_col(st, ["lat", "latitude", "lati_d", "lati"])
st_lon_col = pick_col(st, ["lon", "longitude", "longi_d", "longi"])

edge_line_col = pick_col(
    edges, ["line_id", "route_id", "lineCode", "line_code"], required=True
)
edge_code_col = pick_col(
    edges, ["station_code", "ekispert_station_code", "code"], required=True
)
edge_order_col = pick_col(edges, ["stop_order", "order", "seq", "index", "idx"])  # 可选

meta_line_col = pick_col(
    meta, ["line_id", "route_id", "lineCode", "line_code"], required=True
)
meta_name_col = pick_col(meta, ["line_name", "name", "route_name", "TypicalName"])

# 标准化类型
st[st_code_col] = st[st_code_col].astype(str)
edges[edge_code_col] = edges[edge_code_col].astype(str)

# 关联 edges -> stations（拿经纬度）
use_cols = [st_code_col, st_name_col]
if st_lat_col:
    use_cols.append(st_lat_col)
if st_lon_col:
    use_cols.append(st_lon_col)

edges_merged = edges.merge(
    st[use_cols],
    left_on=edge_code_col,
    right_on=st_code_col,
    how="left",
    suffixes=("", "_st"),
)

# 判定缺经纬度
if st_lat_col is None or st_lon_col is None:
    # stations.csv 里本来就没有经纬度列，直接把所有经过的站都算“缺失”
    missing = edges_merged.copy()
    missing["__no_latlon_columns__"] = True
else:
    missing = edges_merged[
        edges_merged[st_lat_col].isna() | edges_merged[st_lon_col].isna()
    ].copy()

if missing.empty:
    print("✅ 所有用到的站点都有经纬度。")
else:
    # 关联线路名称（若有）
    if meta_name_col:
        missing = missing.merge(
            meta[[meta_line_col, meta_name_col]],
            left_on=edge_line_col,
            right_on=meta_line_col,
            how="left",
        )
    # 组织输出列（按可用性拼）
    out_cols = []
    for c in [
        edge_line_col,
        meta_name_col,
        edge_code_col,
        st_name_col,
        st_lat_col,
        st_lon_col,
        edge_order_col,
    ]:
        if c and c in missing.columns and c not in out_cols:
            out_cols.append(c)

    # 至少保证有 line 与 station code
    if edge_line_col not in out_cols:
        out_cols.insert(0, edge_line_col)
    if edge_code_col not in out_cols:
        out_cols.insert(1, edge_code_col)

    out = missing[out_cols].copy()

    # 友好排序
    sort_keys = [k for k in [edge_line_col, edge_order_col] if k and k in out.columns]
    if sort_keys:
        out = out.sort_values(sort_keys)

    out_path = os.path.join(DATA_DIR, "missing_station_coords.csv")
    out.to_csv(out_path, index=False)
    print(f"⚠️ 找到 {len(out)} 条“缺经纬度”站点记录，已导出: {out_path}")

    # 去重导出站点清单（给补数据用）
    uniq = out[[edge_code_col]]
    if st_name_col in out.columns:
        uniq = out[[edge_code_col, st_name_col]]
    uniq = uniq.drop_duplicates().reset_index(drop=True)
    uniq = uniq.rename(columns={edge_code_col: "station_code", st_name_col: "name"})
    uniq_path = os.path.join(DATA_DIR, "missing_station_codes.csv")
    uniq.to_csv(uniq_path, index=False)
    print(f"🧭 独立站点清单: {uniq_path}")

    print("\n🪪 列名自检：")
    print(
        "  stations.csv -> "
        f"code={st_code_col}, name={st_name_col}, lat={st_lat_col}, lon={st_lon_col}"
    )
    print(
        "  edges.csv    -> "
        f"line={edge_line_col}, station_code={edge_code_col}, order={edge_order_col}"
    )
    print(f"  meta.csv     -> line={meta_line_col}, line_name={meta_name_col}")
