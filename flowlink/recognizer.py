# -*- coding: utf-8 -*-
"""
截图识别模块：从框选截图中自动识别 点阵规模 N×N 与同色端点对。

recognize(image) -> dict
    {
      "N": int,
      "pairs": [(label, (r1,c1), (r2,c2)), ...],
      "colors": {label: (R,G,B)},
      "endpoints": [(r,c,label,R,G,B), ...],
      "ok": bool,
      "message": str,
    }
image: PIL.Image (RGB)
"""
import collections
import numpy as np


def _background_color(a):
    """取四角区域中位数作为背景色。"""
    H, W, _ = a.shape
    corners = np.concatenate([
        a[:8, :8].reshape(-1, 3), a[:8, -8:].reshape(-1, 3),
        a[-8:, :8].reshape(-1, 3), a[-8:, -8:].reshape(-1, 3),
    ])
    return np.median(corners, axis=0)


def _find_endpoints(a):
    """分割发光端点，返回 [{x,y,rgb,area,w,h}]。"""
    H, W, _ = a.shape
    r = a[:, :, 0].astype(int)
    g = a[:, :, 1].astype(int)
    b = a[:, :, 2].astype(int)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    sat = mx - mn
    # 高亮白心 或 高饱和彩色
    mask = ((mx > 150) & (sat > 35)) | (mx > 195)

    visited = np.zeros((H, W), dtype=bool)
    endpoints = []
    ys, xs = np.where(mask)
    for y0, x0 in zip(ys, xs):
        if visited[y0, x0]:
            continue
        q = collections.deque([(y0, x0)])
        visited[y0, x0] = True
        px, py = [], []
        while q:
            y, x = q.popleft()
            px.append(x); py.append(y)
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < H and 0 <= nx < W and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        q.append((ny, nx))
        area = len(px)
        if area < 10:  # 滤除按钮文字噪点
            continue
        w = max(px) - min(px) + 1
        h = max(py) - min(py) + 1
        if max(w, h) / max(1, min(w, h)) > 2.3:  # 滤除长条文字
            continue
        cx = float(np.mean(px))
        cy = float(np.mean(py))
        # 核心颜色：取最亮 30% 像素平均，避免光晕稀释
        order = np.argsort(mx[py, px])
        core = order[-max(3, len(order) // 3):]
        rgb = a[np.array(py)[core], np.array(px)[core]].mean(axis=0)
        # 滤除纯白/灰文字（无色彩饱和度）
        if rgb.max() - rgb.min() < 18 and rgb.min() > 200:
            continue
        endpoints.append({
            "x": cx, "y": cy,
            "rgb": tuple(int(v) for v in rgb),
            "area": area, "w": w, "h": h,
        })
    return endpoints


def _estimate_step(coords):
    """从一维坐标估计格距：相邻差的中位数（可能是多格间距）。"""
    coords = sorted(coords)
    if len(coords) < 2:
        return None
    diffs = [coords[i + 1] - coords[i] for i in range(len(coords) - 1)]
    diffs = [d for d in diffs if d > 6]
    if not diffs:
        return None
    return float(np.median(diffs))


def _norm_step(px, py):
    """把多格间距折算成单格步长，返回 (step, 估算依据)。"""
    if px is None and py is None:
        return None
    if px is None:
        return py
    if py is None:
        return px
    lo, hi = sorted((px, py))
    k = max(1, round(hi / lo))
    hi = hi / k
    return (lo + hi) / 2


def _grid_bounds(a, bg):
    """用 cell（略亮于背景的暗块）投影估计网格整体边界。"""
    H, W, _ = a.shape
    lum = a.mean(axis=2)
    bg_lum = float(bg.mean())
    cell = (lum > bg_lum + 6) & (lum < bg_lum + 75)
    colfrac = cell.mean(axis=0)
    rowfrac = cell.mean(axis=1)
    cols = np.where(colfrac > 0.25)[0]
    rows = np.where(rowfrac > 0.25)[0]
    if len(cols) == 0 or len(rows) == 0:
        return None
    return int(cols[0]), int(cols[-1]), int(rows[0]), int(rows[-1])


def _cluster_colors(endpoints, thr=65):
    """按 RGB 距离贪心聚类，返回 labels 列表（与 endpoints 等长）。"""
    n = len(endpoints)
    labels = [-1] * n
    cur = 0
    for i in range(n):
        if labels[i] != -1:
            continue
        labels[i] = cur
        ri = np.array(endpoints[i]["rgb"])
        for j in range(i + 1, n):
            if labels[j] != -1:
                continue
            rj = np.array(endpoints[j]["rgb"])
            if np.linalg.norm(ri - rj) < thr:
                labels[j] = cur
        cur += 1
    return labels


def recognize(image, color_thr=35):
    a = np.array(image.convert("RGB"))
    H, W, _ = a.shape
    bg = _background_color(a)
    endpoints = _find_endpoints(a)

    if len(endpoints) < 2:
        return {"ok": False, "message": f"只识别到 {len(endpoints)} 个端点，请重新框选包含完整点阵的区域。",
                "N": 0, "pairs": [], "colors": {}, "endpoints": []}

    # 步长（折算到单格）
    xs = [e["x"] for e in endpoints]
    ys = [e["y"] for e in endpoints]
    px = _estimate_step(xs)
    py = _estimate_step(ys)
    step = _norm_step(px, py)
    if step is None:
        return {"ok": False, "message": "无法估计格子间距，请放大截图后重试。",
                "N": 0, "pairs": [], "colors": {}, "endpoints": []}

    # 临时映射，得到端点覆盖的最大行列索引
    xt, yt = min(xs), min(ys)
    for e in endpoints:
        e["c"] = int(round((e["x"] - xt) / step))
        e["r"] = int(round((e["y"] - yt) / step))
    c_max = max(e["c"] for e in endpoints)
    r_max = max(e["r"] for e in endpoints)

    # 截图尺寸估算与端点覆盖范围折中（外圈最多留 1 行/列空）
    n_w = max(1, round(W / step))
    n_h = max(1, round(H / step))
    N = min(n_w, n_h, c_max + 2, r_max + 2)
    N = max(N, c_max + 1, r_max + 1)

    # 居中基准：第一格中心，重新映射
    x0 = (W - (N - 1) * step) / 2
    y0 = (H - (N - 1) * step) / 2
    for e in endpoints:
        e["c"] = int(round((e["x"] - x0) / step))
        e["r"] = int(round((e["y"] - y0) / step))

    # 越界保护
    bad = [e for e in endpoints if not (0 <= e["r"] < N and 0 <= e["c"] < N)]
    if bad:
        return {"ok": False,
                "message": f"有 {len(bad)} 个端点落在网格外，可能框选不完整，请重试。",
                "N": N, "pairs": [], "colors": {}, "endpoints": []}

    # 颜色聚类
    labels = _cluster_colors(endpoints, thr=color_thr)
    groups = collections.defaultdict(list)
    for e, lab in zip(endpoints, labels):
        groups[lab].append(e)

    pairs = []
    colors = {}
    ep_out = []
    for lab, members in groups.items():
        if len(members) != 2:
            return {"ok": False,
                    "message": f"颜色簇含 {len(members)} 个端点（应为 2 个），颜色区分度不足，请重试。",
                    "N": N, "pairs": [], "colors": {}, "endpoints": []}
        label = f"c{lab}"
        rgb = tuple(int(v) for v in np.mean([m["rgb"] for m in members], axis=0))
        colors[label] = rgb
        (e1, e2) = members
        pairs.append((label, (e1["r"], e1["c"]), (e2["r"], e2["c"])))
        for m in members:
            ep_out.append((m["r"], m["c"], label, *m["rgb"]))

    return {"ok": True, "N": N, "pairs": pairs, "colors": colors,
            "endpoints": ep_out, "message": f"识别到 {N}×{N} 网格，{len(pairs)} 对端点。"}
