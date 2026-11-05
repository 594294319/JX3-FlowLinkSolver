# -*- coding: utf-8 -*-
"""
点阵连线（Numberlink / Flow Free）求解器
- 主力：活动路径回溯 DFS + 强剪枝
- 兜底：Z3 约束求解（DFS 超时/失败时启用）

输入：
    N : 边长
    pairs : [(cid, (r1,c1), (r2,c2)), ...]
    require_fill : True 要求填满全部格子；False 只需连通同色两端

输出：
    solve(...) -> (result, method, info)
        result: {cid: [(r,c),...]} 或 None
"""
import time
from collections import deque

_DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1)]


def _neighbors(r, c, N):
    for dr, dc in _DIRS:
        nr, nc = r + dr, c + dc
        if 0 <= nr < N and 0 <= nc < N:
            yield nr, nc


# ---------------------------------------------------------------------------
# 主力：活动路径回溯 DFS
# ---------------------------------------------------------------------------
class _DfsSolver:
    def __init__(self, N, pairs, require_fill=True, deadline=None):
        self.N = N
        self.pairs = list(pairs)
        self.require_fill = require_fill
        self.deadline = deadline
        self.owner = [[0] * N for _ in range(N)]   # 0 空，否则 cid
        self.path = {}                              # cid -> 有序格子列表
        self.tail = {}                              # cid -> 另一端点
        self.done = set()
        self.nodes = 0

    def _occupied(self, r, c):
        return self.owner[r][c] != 0

    # ---- 剪枝 ----
    def _free_endpoints(self):
        eps = set()
        for cid, _, b in self.pairs:
            if cid not in self.done:
                eps.add(self.tail[cid])
        return eps

    def _prune(self):
        N = self.N
        free_eps = self._free_endpoints()

        # 1) 孤立空格：四邻全占且不是自由端点
        for r in range(N):
            for c in range(N):
                if self._occupied(r, c):
                    continue
                if (r, c) in free_eps:
                    continue
                n = sum(1 for nr, nc in _neighbors(r, c, N)
                        if self._occupied(nr, nc))
                if n == 4:
                    return False

        # 2) 未占连通分量必须含自由端点（端点格虽已占位，但视为分量可触及）
        seen = [[False] * N for _ in range(N)]
        for r in range(N):
            for c in range(N):
                if seen[r][c]:
                    continue
                if self._occupied(r, c) and (r, c) not in free_eps:
                    continue
                q = deque([(r, c)])
                seen[r][c] = True
                has_ep = False
                while q:
                    cr, cc = q.popleft()
                    if (cr, cc) in free_eps:
                        has_ep = True
                    for nr, nc in _neighbors(cr, cc, N):
                        if seen[nr][nc]:
                            continue
                        if self._occupied(nr, nc) and (nr, nc) not in free_eps:
                            continue
                        seen[nr][nc] = True
                        q.append((nr, nc))
                if not has_ep:
                    return False

        # 3) 未完成颜色的 head 与 tail 仍可达
        for cid, _, _ in self.pairs:
            if cid in self.done:
                continue
            head = self.path[cid][-1]
            tail = self.tail[cid]
            if not self._reachable(head, tail, free_eps):
                return False
        return True

    def _reachable(self, src, dst, free_eps):
        if src == dst:
            return True
        q = deque([src])
        seen = {src}
        while q:
            r, c = q.popleft()
            for nr, nc in _neighbors(r, c, self.N):
                if (nr, nc) == dst:
                    return True
                if (nr, nc) in seen:
                    continue
                # 空格可走；自由端点（tail）放行；其它已占格阻挡
                if self._occupied(nr, nc) and (nr, nc) not in free_eps:
                    continue
                seen.add((nr, nc))
                q.append((nr, nc))
        return False

    def _pick_color(self):
        """选可走步数最少的未完成颜色（约束最强优先）。"""
        best, best_moves = None, 10 ** 9
        for cid, _, _ in self.pairs:
            if cid in self.done:
                continue
            head = self.path[cid][-1]
            moves = 0
            for nr, nc in _neighbors(head[0], head[1], self.N):
                if not self._occupied(nr, nc) or (nr, nc) == self.tail[cid]:
                    moves += 1
            if moves < best_moves:
                best, best_moves = cid, moves
                if moves <= 1:
                    break
        return best

    def solve(self):
        for cid, a, b in self.pairs:
            self.owner[a[0]][a[1]] = cid
            self.owner[b[0]][b[1]] = cid
            self.path[cid] = [a]
            self.tail[cid] = b
        return self._backtrack()

    def _backtrack(self):
        if self.deadline and time.time() > self.deadline:
            return False
        self.nodes += 1

        if len(self.done) == len(self.pairs):
            if self.require_fill:
                for r in range(self.N):
                    for c in range(self.N):
                        if not self._occupied(r, c):
                            return False
            return True

        cid = self._pick_color()
        head = self.path[cid][-1]
        tail = self.tail[cid]

        for nr, nc in _neighbors(head[0], head[1], self.N):
            if self._occupied(nr, nc) and (nr, nc) != tail:
                continue

            if (nr, nc) == tail:
                # 延伸到另一端，路径完成
                self.owner[nr][nc] = cid
                self.path[cid].append((nr, nc))
                self.done.add(cid)
                if self._prune() and self._backtrack():
                    return True
                self.done.discard(cid)
                self.path[cid].pop()
                self.owner[nr][nc] = 0
            else:
                self.owner[nr][nc] = cid
                self.path[cid].append((nr, nc))
                if self._prune() and self._backtrack():
                    return True
                self.path[cid].pop()
                self.owner[nr][nc] = 0

            if self.deadline and time.time() > self.deadline:
                return False
        return False

    def result(self):
        return {cid: list(p) for cid, p in self.path.items()}


# ---------------------------------------------------------------------------
# 兜底：Z3 边 + 流 模型
# ---------------------------------------------------------------------------
def _solve_z3(N, pairs, require_fill=True, timeout_ms=15000):
    try:
        import z3
    except ImportError:
        return None

    s = z3.Solver()
    s.set("timeout", timeout_ms)

    colors = [cid for cid, _, _ in pairs]
    cindex = {cid: i for i, cid in enumerate(colors)}
    K = len(colors)
    D = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    opp = [1, 0, 3, 2]

    in_k = [[[z3.Bool(f"in_{k}_{r}_{c}") for c in range(N)] for r in range(N)]
            for k in range(K)]
    e = [[[[z3.Bool(f"e_{k}_{r}_{c}_{d}") for d in range(4)]
           for c in range(N)] for r in range(N)] for k in range(K)]
    f = [[[[z3.Int(f"f_{k}_{r}_{c}_{d}") for d in range(4)]
           for c in range(N)] for r in range(N)] for k in range(K)]

    if require_fill:
        for r in range(N):
            for c in range(N):
                s.add(z3.PbEq([(in_k[k][r][c], 1) for k in range(K)], 1))
    else:
        # 不要求填满：每格至多一色
        for r in range(N):
            for c in range(N):
                s.add(z3.PbLe([(in_k[k][r][c], 1) for k in range(K)], 1))

    for cid, a, b in pairs:
        k = cindex[cid]
        ek, fk, ink = e[k], f[k], in_k[k]
        s.add(ink[a[0]][a[1]])
        s.add(ink[b[0]][b[1]])

        for r in range(N):
            for c in range(N):
                for d, (dr, dc) in enumerate(D):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < N and 0 <= nc < N:
                        s.add(ek[r][c][d] == ek[nr][nc][opp[d]])
                        s.add(z3.Implies(ek[r][c][d],
                                         z3.And(ink[r][c], ink[nr][nc])))
                        s.add(z3.Or(fk[r][c][d] == 0, fk[r][c][d] == 1))
                        s.add(z3.Implies(fk[r][c][d] == 1, ek[r][c][d]))
                    else:
                        s.add(z3.Not(ek[r][c][d]))
                        s.add(fk[r][c][d] == 0)

        for r in range(N):
            for c in range(N):
                incident = [ek[r][c][d] for d in range(4)]
                deg = z3.Sum([z3.If(x, 1, 0) for x in incident])
                if (r, c) == a or (r, c) == b:
                    s.add(deg == 1)
                else:
                    s.add(z3.Implies(ink[r][c], deg == 2))
                    s.add(z3.Implies(z3.Not(ink[r][c]), deg == 0))

                outflow = z3.Sum([fk[r][c][d] for d in range(4)])
                inflow = z3.Sum([fk[nr][nc][opp[d]]
                                 for d, (dr, dc) in enumerate(D)
                                 for nr, nc in [(r + dr, c + dc)]
                                 if 0 <= nr < N and 0 <= nc < N])
                if (r, c) == a:
                    s.add(outflow - inflow == 1)
                elif (r, c) == b:
                    s.add(inflow - outflow == 1)
                else:
                    s.add(outflow == inflow)

        # 归属由流覆盖：in 格必须与某条流边关联（端点除外）
        for r in range(N):
            for c in range(N):
                if (r, c) == a or (r, c) == b:
                    continue
                touched = z3.Or([fk[r][c][d] == 1 for d in range(4)])
                s.add(ink[r][c] == touched)

    if s.check() != z3.sat:
        return None

    model = s.model()
    result = {}
    for cid, a, b in pairs:
        k = cindex[cid]
        ek = e[k]
        path = [a]
        prev, cur, guard = None, a, 0
        while cur != b and guard < N * N:
            guard += 1
            nxt = None
            for d, (dr, dc) in enumerate(D):
                nr, nc = cur[0] + dr, cur[1] + dc
                if 0 <= nr < N and 0 <= nc < N and (nr, nc) != prev \
                        and z3.is_true(model.eval(ek[cur[0]][cur[1]][d])):
                    nxt = (nr, nc)
                    break
            if nxt is None:
                break
            prev, cur = cur, nxt
            path.append(cur)
        result[cid] = path
    return result


# ---------------------------------------------------------------------------
# 解合法性校验
# ---------------------------------------------------------------------------
def validate(N, pairs, result, require_fill=True):
    """返回 (ok, message)。检查：端点匹配、链连通无重复、不重叠、填满（可选）。"""
    if not result:
        return False, "无解"
    owner = {}
    for cid, path in result.items():
        if len(path) < 2:
            return False, f"{cid} 路径过短"
        if len(set(path)) != len(path):
            return False, f"{cid} 路径含重复格"
        for i in range(1, len(path)):
            dr = abs(path[i][0] - path[i - 1][0])
            dc = abs(path[i][1] - path[i - 1][1])
            if dr + dc != 1:
                return False, f"{cid} 路径存在不相邻格"
        for cell in path:
            if cell in owner:
                return False, f"格子 {cell} 被多条路径占用"
            owner[cell] = cid
    # 端点匹配
    pair_map = {cid: (a, b) for cid, a, b in pairs}
    for cid, (a, b) in pair_map.items():
        path = result.get(cid, [])
        if a not in path or b not in path:
            return False, f"{cid} 端点未接入路径"
    if require_fill and len(owner) != N * N:
        return False, f"未填满：{len(owner)}/{N*N}"
    return True, "OK"


# ---------------------------------------------------------------------------
# 盘迹模式：哈密顿路径（起点遍历所有可走格到终点）+ 红区 + 传送门
# ---------------------------------------------------------------------------
def solve_trace(R, C, start, end, red, portal=None, dfs_timeout=5.0):
    """
    R, C：行列（支持长方形）；start/end=(r,c)；red：不可走格集合；
    portal=(p1,p2) 或 None（双向传送，整局仅可用一次）。
    返回 (path, method, info)，path=[(r,c),...] 或 None。
    """
    t0 = time.time()
    red = set(red)
    start = tuple(start)
    end = tuple(end)
    if R <= 0 or C <= 0:
        return None, None, {"reason": "棋盘尺寸非法"}
    if start in red or end in red:
        return None, None, {"reason": "起点/终点不能落在红区"}
    if start == end:
        return None, None, {"reason": "起点与终点不能为同一格"}

    walkable = [(r, c) for r in range(R) for c in range(C) if (r, c) not in red]
    total = len(walkable)
    if total < 2:
        return None, None, {"reason": "可走格不足"}

    p1 = p2 = None
    if portal:
        p1, p2 = tuple(portal[0]), tuple(portal[1])
        if p1 in red or p2 in red:
            return None, None, {"reason": "传送门不能落在红区"}
        if p1 == p2:
            return None, None, {"reason": "两个传送门不能为同一格"}

    DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    def _idx(cell):
        return cell[0] * C + cell[1]

    def _free_degree(cell):
        r, c = cell
        cnt = 0
        for dr, dc in DIRS:
            nr, nc = r + dr, c + dc
            if 0 <= nr < R and 0 <= nc < C and (nr, nc) not in red:
                cnt += 1
        return cnt

    visited = 1 << _idx(start)
    path = [start]
    deadline = t0 + dfs_timeout
    nodes = 0

    def _neighbors(cur, used):
        r, c = cur
        for dr, dc in DIRS:
            nr, nc = r + dr, c + dc
            if 0 <= nr < R and 0 <= nc < C and (nr, nc) not in red:
                yield (nr, nc), False
        if p1 is not None and not used:
            if cur == p1:
                yield p2, True
            elif cur == p2:
                yield p1, True

    def _connected(cur, visited_mask):
        """未访问可走格与终点是否仍和当前格连通（已访问格阻挡）。"""
        seen = {cur}
        q = deque([cur])
        while q:
            r, c = q.popleft()
            for dr, dc in DIRS:
                nr, nc = r + dr, c + dc
                if not (0 <= nr < R and 0 <= nc < C):
                    continue
                if (nr, nc) in red or (nr, nc) in seen:
                    continue
                if visited_mask >> _idx((nr, nc)) & 1:
                    continue
                seen.add((nr, nc))
                q.append((nr, nc))
        return end in seen

    def _dfs(cur, used):
        nonlocal nodes, visited
        nodes += 1
        if time.time() > deadline:
            return False
        if len(path) == total:
            return cur == end
        cands = []
        for nxt, is_portal in _neighbors(cur, used):
            if visited >> _idx(nxt) & 1:
                continue
            if nxt == end and len(path) < total - 1:
                continue  # 未走满前不能进入终点
            cands.append((nxt, is_portal))
        # Warnsdorff：剩余出口少的优先，减少分叉
        cands.sort(key=lambda x: _free_degree(x[0]))
        for nxt, is_portal in cands:
            visited |= 1 << _idx(nxt)
            path.append(nxt)
            new_used = used or is_portal
            if _connected(nxt, visited) and _dfs(nxt, new_used):
                return True
            path.pop()
            visited &= ~(1 << _idx(nxt))
        return False

    ok = _dfs(start, False)
    if ok:
        return list(path), "dfs", {"nodes": nodes, "elapsed": time.time() - t0}
    reason = "无解或超时" if time.time() > deadline else "无解"
    return None, None, {"nodes": nodes, "elapsed": time.time() - t0, "reason": reason}


def validate_trace(R, C, start, end, red, portal, path):
    """校验盘迹路径：起终点、相邻/传送边、不重复、不踩红区、走满可走格。"""
    if not path or len(path) < 2:
        return False, "路径过短"
    if path[0] != tuple(start):
        return False, "起点未接入路径"
    if path[-1] != tuple(end):
        return False, "终点未接入路径"
    red = set(red)
    p1 = p2 = None
    if portal:
        p1, p2 = tuple(portal[0]), tuple(portal[1])
    seen = set()
    for i, cell in enumerate(path):
        if cell in red:
            return False, f"路径踩入红区 {cell}"
        if cell in seen:
            return False, f"格子 {cell} 被重复经过"
        seen.add(cell)
        if i == 0:
            continue
        prev = path[i - 1]
        dr = abs(cell[0] - prev[0])
        dc = abs(cell[1] - prev[1])
        adj = dr + dc == 1
        portal_edge = portal and (
            (prev == p1 and cell == p2) or (prev == p2 and cell == p1))
        if not adj and not portal_edge:
            return False, f"第 {i} 步不相邻"
    walkable = {(r, c) for r in range(R) for c in range(C) if (r, c) not in red}
    if seen != walkable:
        return False, f"未走满：{len(seen)}/{len(walkable)}"
    return True, "OK"


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------
def solve(N, pairs, require_fill=True, dfs_timeout=3.0, z3_timeout=15.0):
    t0 = time.time()
    pairs = list(pairs)
    if N <= 0 or not pairs:
        return None, None, {"reason": "空输入"}

    deadline = time.time() + dfs_timeout
    dfs = _DfsSolver(N, pairs, require_fill=require_fill, deadline=deadline)
    try:
        res = dfs.solve()
    except RecursionError:
        res = False
    if res:
        return dfs.result(), "dfs", {"nodes": dfs.nodes, "elapsed": time.time() - t0}

    res = _solve_z3(N, pairs, require_fill=require_fill,
                    timeout_ms=int(z3_timeout * 1000))
    if res is not None:
        return res, "z3", {"elapsed": time.time() - t0}
    return None, None, {"elapsed": time.time() - t0, "reason": "无解或超时"}


# 自检
if __name__ == "__main__":
    demo = [
        ("gold", (0, 0), (3, 2)),
        ("green", (1, 0), (3, 4)),
        ("blue", (2, 4), (4, 4)),
    ]
    for fill in (False, True):
        res, method, info = solve(6, demo, require_fill=fill, dfs_timeout=5.0)
        print(f"require_fill={fill} method={method} info={info}")
        if res:
            grid = [["."] * 6 for _ in range(6)]
            sym = {"gold": "G", "green": "g", "blue": "B"}
            for cid, path in res.items():
                for r, c in path:
                    grid[r][c] = sym[cid]
            for row in grid:
                print(" ".join(row))
            print("filled:", sum(x != "." for row in grid for x in row))
