# -*- coding: utf-8 -*-
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"C:\Users\59429\Doubao\chats\2026-11-05\new-chat\flowlink")
import solver

cases = [
    ("示例6x6 填满", 6, [
        ("c0", (0, 0), (3, 2)), ("c1", (1, 0), (3, 4)), ("c2", (2, 4), (4, 4))], True),
    ("示例6x6 不填满", 6, [
        ("c0", (0, 0), (3, 2)), ("c1", (1, 0), (3, 4)), ("c2", (2, 4), (4, 4))], False),
    ("无解题(端点被分隔)", 4, [
        ("c0", (0, 0), (3, 3)), ("c1", (0, 3), (3, 0))], True),
]

out = []
for name, N, pairs, fill in cases:
    t0 = time.time()
    sol, method, info = solver.solve(N, pairs, require_fill=fill,
                                     dfs_timeout=2.0, z3_timeout=10.0)
    dt = time.time() - t0
    if sol:
        ok, msg = solver.validate(N, pairs, sol, require_fill=fill)
        lens = {k: len(v) for k, v in sol.items()}
        out.append(f"[{name}] method={method} ok={ok} {msg} {dt:.2f}s len={lens}")
    else:
        out.append(f"[{name}] 无解 method={method} {info} {dt:.2f}s")

# 强制走 Z3：DFS 超时设 0.05s
t0 = time.time()
sol, method, info = solver.solve(6, cases[0][2], require_fill=True,
                                 dfs_timeout=0.05, z3_timeout=10.0)
ok, msg = solver.validate(6, cases[0][2], sol, require_fill=True) if sol else (False, "无")
out.append(f"[强制Z3兜底] method={method} ok={ok} {msg} {time.time()-t0:.2f}s info={info}")

open(r"C:\Users\59429\Doubao\chats\2026-11-05\new-chat\cases.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
