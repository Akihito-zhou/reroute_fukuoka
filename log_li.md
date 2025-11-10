## 2025/11/10 - Data Validation (Stops 675300 → 675318)

### Investigation
- Method: Checked via Google Maps.
- Stops:
  - 675300 = 675300,百年橋／西鉄バス,33.573777,130.418733
  - 675318 = 675318,中尾二丁目／西鉄バス,33.539993,13041103
- Result: Found direct bus route (66番, 約20分).
  - Picture:
  ![alt text](image.png)

### Conclusion
→ 現実には直通路線（66番線）が存在するため、データまたはアルゴリズムの接続処理に問題がある可能性が高い。
推定原因：
1. line_stop_edges.csv に 675300 → 675318 の接続が含まれていない。
2. boundary／象限インデックスの計算時に除外されている。
3. Simple RAPTOR の探索制限（分岐数／深さ）が厳しすぎる。