from pathlib import Path

import pandas as pd

data_dir = Path(__file__).resolve().parents[1] / "data"
files = sorted(data_dir.glob("segments_*.csv"))
if not files:
    raise SystemExit("segments_*.csv not found")
latest = files[-1]
df = pd.read_csv(latest)
print(latest, df.head())
