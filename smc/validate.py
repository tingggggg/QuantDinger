"""用 QuantDinger 自己的驗證管線測指標程式碼。"""
import sys
sys.path.insert(0, "/app")

import numpy as np
import pandas as pd

from app.services.indicator_validation import validate_indicator_code
from app.services.indicator_params import IndicatorParamsParser

code = open(sys.argv[1]).read()

print("=" * 68)
print("1. @param 解析")
print("=" * 68)
for p in IndicatorParamsParser.parse_params(code):
    vals = p.get("values")
    tail = ("  values=" + str(vals[:6]) + ("..." if vals and len(vals) > 6 else "")) if vals else ""
    print(f"  {p.get('name'):<16} {str(p.get('type')):<7} default={p.get('default')!r:<6}{tail}")

print()
print("=" * 68)
print("2. 沙箱執行 + 輸出結構驗證")
print("=" * 68)
r = validate_indicator_code(code)
print(f"  success      : {r.get('success')}")
print(f"  msg          : {r.get('msg')}")
if r.get("error_type"):
    print(f"  error_type   : {r.get('error_type')}")
    print(f"  details      : {str(r.get('details'))[:600]}")
print(f"  plots_count  : {r.get('plots_count')}")
print(f"  signals_count: {r.get('signals_count')}")
hints = r.get("hints")
if hints:
    print(f"  hints        : {hints}")

if not r.get("success"):
    sys.exit(1)

print()
print("=" * 68)
print("3. 真實資料試算（模擬 200 根）+ repaint 檢查")
print("=" * 68)

from app.utils.safe_exec import safe_exec_indicator_isolated


def synth(n, seed=11):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, .012, n)))
    return pd.DataFrame({
        "open": np.r_[c[0], c[:-1]],
        "high": c * (1 + np.abs(rng.normal(0, .005, n))),
        "low": c * (1 - np.abs(rng.normal(0, .005, n))),
        "close": c,
        "volume": rng.uniform(1e3, 5e3, n),
    }, index=pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC"))


def run(frame):
    res = safe_exec_indicator_isolated(code=code, df=frame, params={}, timeout=40)
    if not res.get("success"):
        raise RuntimeError(res.get("error"))
    return (res.get("result") or {}).get("output")


full = synth(400)
out = run(full.iloc[:300])
sig_counts = {}
for s in out["signals"]:
    key = s["text"] + ("↑" if s["type"] == "buy" else "↓")
    sig_counts[key] = sum(1 for v in s["data"] if v is not None)
print("  前 300 根偵測到的訊號:", sig_counts)
print("  plots:", [p["name"] for p in out["plots"]])

# repaint 檢查：多餵 100 根，看前 300 根的訊號有沒有被改寫
out2 = run(full.iloc[:400])
changed = 0
for a, b in zip(out["signals"], out2["signals"]):
    for i in range(300):
        if (a["data"][i] is None) != (b["data"][i] is None):
            changed += 1
print()
print(f"  多餵 100 根後，前 300 根的訊號改寫數: {changed}")
print("  (0 = 無 repaint；作為對照，smartmoneyconcepts 是 150/150 全部改寫)")
print("=" * 68)
