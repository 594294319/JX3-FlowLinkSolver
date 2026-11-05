# -*- coding: utf-8 -*-
"""点阵连线求解器 —— PySide6 界面"""
import sys
from PIL import ImageGrab
from PySide6 import QtCore, QtGui, QtWidgets

from . import solver, recognizer

BOARD = 560
MARGIN = 24

# 手动创建端点配色：红、黄、蓝、绿、橙、紫、青、粉，成对循环
PALETTE = [
    (232, 76, 76),
    (245, 197, 66),
    (70, 130, 230),
    (80, 200, 120),
    (232, 138, 60),
    (170, 105, 220),
    (58, 196, 196),
    (232, 120, 168),
]
MAX_GRID = 12


def _qcolor(rgb):
    return QtGui.QColor(max(0, min(255, int(rgb[0]))),
                        max(0, min(255, int(rgb[1]))),
                        max(0, min(255, int(rgb[2]))))


# ---------------------------------------------------------------------------
# 棋盘自绘控件
# ---------------------------------------------------------------------------
class BoardWidget(QtWidgets.QWidget):
    RED_FILL = QtGui.QColor("#5a2222")
    PORTAL_FILL = QtGui.QColor("#6a3d9a")
    START_COLOR = (80, 200, 120)
    END_COLOR = (70, 130, 230)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(BOARD, BOARD)
        self.N = 0
        self.endpoints = []
        self.colors = {}
        self.solution = None
        self.trace = None
        self.trace_path = None

    def set_state(self, N, endpoints, colors, solution, trace=None, trace_path=None):
        self.N = N
        self.endpoints = endpoints
        self.colors = colors
        self.solution = solution
        self.trace = trace
        self.trace_path = trace_path
        self.update()

    def _rc(self):
        if self.trace:
            return self.trace["R"], self.trace["C"]
        return self.N, self.N

    def _geom(self):
        R, C = self._rc()
        R = R or 1
        C = C or 1
        cx = (BOARD - 2 * MARGIN) / C
        cy = (BOARD - 2 * MARGIN) / R
        return MARGIN, MARGIN, cx, cy

    def _center(self, r, c):
        x0, y0, cx, cy = self._geom()
        return QtCore.QPointF(x0 + c * cx + cx / 2,
                              y0 + r * cy + cy / 2)

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor("#151f28"))
        R, C = self._rc()
        if R == 0:
            p.setPen(QtGui.QColor("#8899aa"))
            p.drawText(self.rect(), QtCore.Qt.AlignCenter, "截图识别或手动创建后在此显示棋盘")
            p.end()
            return

        x0, y0, cx, cy = self._geom()
        for r in range(R):
            for c in range(C):
                rect = QtCore.QRectF(x0 + c * cx + 2, y0 + r * cy + 2,
                                      cx - 4, cy - 4)
                p.fillRect(rect, QtGui.QColor("#2a343e"))
                p.setPen(QtGui.QColor("#3a4652"))
                p.drawRect(rect)

        if self.trace:
            self._paint_trace(p, x0, y0, cx, cy)
        else:
            self._paint_flow(p, min(cx, cy))
        p.end()

    def _paint_flow(self, p, cell):
        # 路径
        if self.solution:
            for _cid, path in self.solution.items():
                color = _qcolor(self.colors.get(_cid, (180, 180, 180)))
                pen = QtGui.QPen(color)
                pen.setWidth(max(4, cell * 0.18))
                pen.setCapStyle(QtCore.Qt.RoundCap)
                pen.setJoinStyle(QtCore.Qt.RoundJoin)
                p.setPen(pen)
                for i in range(1, len(path)):
                    p.drawLine(self._center(*path[i - 1]), self._center(*path[i]))
        # 端点
        for r, c, _label, *rgb in self.endpoints:
            pt = self._center(r, c)
            rad = cell * 0.22
            p.setBrush(_qcolor(rgb))
            p.setPen(QtGui.QPen(QtCore.Qt.white, 2))
            p.drawEllipse(pt, rad, rad)
            p.setBrush(QtGui.QColor("white"))
            p.setPen(QtCore.Qt.NoPen)
            p.drawEllipse(pt, rad * 0.35, rad * 0.35)

    def _paint_trace(self, p, x0, y0, cx, cy):
        t = self.trace
        for r, c in t["red"]:
            p.fillRect(QtCore.QRectF(x0 + c * cx + 2, y0 + r * cy + 2,
                                      cx - 4, cy - 4), self.RED_FILL)
        if t["portal"]:
            for r, c in t["portal"]:
                p.fillRect(QtCore.QRectF(x0 + c * cx + 2, y0 + r * cy + 2,
                                         cx - 4, cy - 4), self.PORTAL_FILL)
        # 路径
        if self.trace_path and len(self.trace_path) > 1:
            pen = QtGui.QPen(QtGui.QColor("#5ec8e0"))
            pen.setWidth(max(4, min(cx, cy) * 0.18))
            pen.setCapStyle(QtCore.Qt.RoundCap)
            pen.setJoinStyle(QtCore.Qt.RoundJoin)
            p.setPen(pen)
            for i in range(1, len(self.trace_path)):
                p.drawLine(self._center(*self.trace_path[i - 1]),
                           self._center(*self.trace_path[i]))
        # 起终点标记
        for cell, color, mark in ((t["start"], self.START_COLOR, "S"),
                                  (t["end"], self.END_COLOR, "T")):
            if cell is None:
                continue
            pt = self._center(*cell)
            rad = min(cx, cy) * 0.24
            p.setBrush(_qcolor(color))
            p.setPen(QtGui.QPen(QtCore.Qt.white, 2))
            p.drawEllipse(pt, rad, rad)
            p.setPen(QtGui.QColor("white"))
            p.setFont(QtGui.QFont("Microsoft YaHei", int(rad), QtGui.QFont.Bold))
            p.drawText(QtCore.QRectF(pt.x() - rad, pt.y() - rad, 2 * rad, 2 * rad),
                       QtCore.Qt.AlignCenter, mark)


# ---------------------------------------------------------------------------
# 求解线程
# ---------------------------------------------------------------------------
class SolverThread(QtCore.QThread):
    done = QtCore.Signal(object, str, dict)

    def __init__(self, N, pairs, require_fill):
        super().__init__()
        self.N = N
        self.pairs = pairs
        self.require_fill = require_fill

    def run(self):
        try:
            sol, method, info = solver.solve(
                self.N, self.pairs, require_fill=self.require_fill,
                dfs_timeout=3.0, z3_timeout=15.0)
        except Exception as e:
            self.done.emit(None, None,
                           {"reason": f"求解线程异常: {e}", "nodes": 0, "elapsed": 0})
            return
        self.done.emit(sol, method, info)


class TraceThread(QtCore.QThread):
    done = QtCore.Signal(object, str, dict)

    def __init__(self, R, C, start, end, red, portal):
        super().__init__()
        self.R, self.C = R, C
        self.pt_start, self.pt_end = start, end
        self.red, self.portal = red, portal

    def run(self):
        try:
            sol, method, info = solver.solve_trace(
                self.R, self.C, self.pt_start, self.pt_end, self.red, self.portal,
                dfs_timeout=5.0)
        except Exception as e:
            self.done.emit(None, None,
                           {"reason": f"求解线程异常: {e}", "nodes": 0, "elapsed": 0})
            return
        self.done.emit(sol, method, info)


# ---------------------------------------------------------------------------
# 全屏框选
# ---------------------------------------------------------------------------
class SelectRect(QtWidgets.QWidget):
    """覆盖全部屏幕的半透明置顶遮罩，拖拽出矩形区域。

    信号 rect_ready(bbox, reason)：bbox 为 None 表示取消/失败，reason 说明原因。
    """
    rect_ready = QtCore.Signal(object, str)

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.origin = None
        self.cur = None
        self.done = False

        app = QtWidgets.QApplication.instance()
        self.virtual_geo = app.primaryScreen().virtualGeometry()
        self.setGeometry(self.virtual_geo)
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

    # ---- Win32 强制置顶（Qt 的 hint 在置顶/全屏游戏前可能失效）----
    def _force_topmost(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            HWND_TOPMOST = -1
            SWP_NOMOVE = 0x0001
            SWP_NOSIZE = 0x0002
            SWP_SHOWWINDOW = 0x0040
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                 SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def showEvent(self, e):
        super().showEvent(e)
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self._force_topmost()
        # 延迟再置顶一次，防止 z-order 被回弹
        QtCore.QTimer.singleShot(120, self._force_topmost)

    def _to_local(self, pt):
        return pt - self.virtual_geo.topLeft()

    def keyPressEvent(self, e):
        if e.key() == QtCore.Qt.Key_Escape:
            self._finish(None, "已取消截图（Esc）")

    def mousePressEvent(self, e):
        if e.button() != QtCore.Qt.LeftButton:
            return
        self.origin = e.globalPosition().toPoint()
        self.cur = self.origin
        self.update()

    def mouseMoveEvent(self, e):
        if self.origin:
            self.cur = e.globalPosition().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != QtCore.Qt.LeftButton or not self.origin:
            return
        self.cur = e.globalPosition().toPoint()
        x1, y1 = self.origin.x(), self.origin.y()
        x2, y2 = self.cur.x(), self.cur.y()
        bbox = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        if bbox[2] - bbox[0] < 10 or bbox[3] - bbox[1] < 10:
            self._finish(None, "框选区域过小，请按住左键拖拽出点阵范围后松开。")
        else:
            self._finish(bbox, "")

    def _finish(self, bbox, reason):
        if self.done:
            return
        self.done = True
        # 先把遮罩从屏幕上撤掉，再通知主窗口；避免遮罩残留在最前层
        self.hide()
        self.close()
        self.rect_ready.emit(bbox, reason)

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 120))
        p.setPen(QtGui.QColor("white"))
        p.setFont(QtGui.QFont("Microsoft YaHei", 15, QtGui.QFont.Bold))
        p.drawText(QtCore.QRect(0, 24, self.width(), 44),
                   QtCore.Qt.AlignHCenter, "按住左键拖拽框选点阵区域，松开确认；Esc 取消")
        if self.origin and self.cur:
            r = QtCore.QRect(self._to_local(self.origin),
                             self._to_local(self.cur)).normalized()
            pen = QtGui.QPen(QtGui.QColor("lime"), 2)
            p.setPen(pen)
            p.drawRect(r)
        p.end()


# ---------------------------------------------------------------------------
# 手动创建关卡
# ---------------------------------------------------------------------------
class ManualCanvas(QtWidgets.QWidget):
    """手动编辑画布：size 拖拽选 R×C；其余阶段按当前模式点击设置。"""

    RED_FILL = QtGui.QColor("#5a2222")
    PORTAL_FILL = QtGui.QColor("#6a3d9a")
    START_COLOR = (80, 200, 120)
    END_COLOR = (70, 130, 230)

    def __init__(self, dialog):
        super().__init__()
        self.dlg = dialog
        self.setFixedSize(BOARD, BOARD)
        self.setMouseTracking(True)
        self._drag_start = None
        self._drag_cur = None

    def _rc(self):
        if self.dlg.stage == "size":
            return MAX_GRID, MAX_GRID
        return self.dlg.R, self.dlg.C

    def _geom(self):
        R, C = self._rc()
        R = R or 1
        C = C or 1
        cx = (BOARD - 2 * MARGIN) / C
        cy = (BOARD - 2 * MARGIN) / R
        return MARGIN, MARGIN, cx, cy

    def _center(self, r, c):
        x0, y0, cx, cy = self._geom()
        return QtCore.QPointF(x0 + c * cx + cx / 2,
                               y0 + r * cy + cy / 2)

    def _cell_at(self, pos):
        R, C = self._rc()
        if R <= 0 or C <= 0:
            return None
        x0, y0, cx, cy = self._geom()
        c = int((pos.x() - x0) / cx)
        r = int((pos.y() - y0) / cy)
        if 0 <= r < R and 0 <= c < C:
            return (r, c)
        return None

    def paintEvent(self, _e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        p.fillRect(self.rect(), QtGui.QColor("#151f28"))
        R, C = self._rc()
        if R <= 0 or C <= 0:
            p.end()
            return
        x0, y0, cx, cy = self._geom()
        for r in range(R):
            for c in range(C):
                rect = QtCore.QRectF(x0 + c * cx + 2, y0 + r * cy + 2,
                                      cx - 4, cy - 4)
                p.fillRect(rect, QtGui.QColor("#2a343e"))
                p.setPen(QtGui.QColor("#3a4652"))
                p.drawRect(rect)

        dlg = self.dlg
        if dlg.stage == "size":
            if self._drag_start and self._drag_cur:
                a = self._center(*self._drag_start)
                b = self._center(*self._drag_cur)
                r = QtCore.QRect(a.toPoint(), b.toPoint()).normalized()
                p.setPen(QtGui.QPen(QtGui.QColor("lime"), 2))
                p.drawRect(r)
        elif dlg.mode == "flow":
            for r, c, _label, *rgb in dlg.endpoints:
                pt = self._center(r, c)
                rad = min(cx, cy) * 0.22
                p.setBrush(_qcolor(rgb))
                p.setPen(QtGui.QPen(QtCore.Qt.white, 2))
                p.drawEllipse(pt, rad, rad)
                p.setBrush(QtGui.QColor("white"))
                p.setPen(QtCore.Qt.NoPen)
                p.drawEllipse(pt, rad * 0.35, rad * 0.35)
        else:
            # 红区
            for r, c in dlg.red:
                p.fillRect(QtCore.QRectF(x0 + c * cx + 2, y0 + r * cy + 2,
                                         cx - 4, cy - 4), self.RED_FILL)
            # 传送门
            for r, c in dlg.portal:
                p.fillRect(QtCore.QRectF(x0 + c * cx + 2, y0 + r * cy + 2,
                                         cx - 4, cy - 4), self.PORTAL_FILL)
            # 起点 / 终点
            for cell, color, mark in ((dlg.start, self.START_COLOR, "S"),
                                      (dlg.end, self.END_COLOR, "T")):
                if cell is None:
                    continue
                pt = self._center(*cell)
                rad = min(cx, cy) * 0.24
                p.setBrush(_qcolor(color))
                p.setPen(QtGui.QPen(QtCore.Qt.white, 2))
                p.drawEllipse(pt, rad, rad)
                p.setPen(QtGui.QColor("white"))
                p.setFont(QtGui.QFont("Microsoft YaHei", int(rad), QtGui.QFont.Bold))
                p.drawText(QtCore.QRectF(pt.x() - rad, pt.y() - rad, 2 * rad, 2 * rad),
                           QtCore.Qt.AlignCenter, mark)
        p.end()

    def mousePressEvent(self, e):
        if e.button() != QtCore.Qt.LeftButton:
            return
        cell = self._cell_at(e.position())
        if cell is None:
            return
        if self.dlg.stage == "size":
            self._drag_start = cell
            self._drag_cur = cell
            self.update()
        else:
            self.dlg.place_at(cell)

    def mouseMoveEvent(self, e):
        if self.dlg.stage == "size" and self._drag_start:
            cell = self._cell_at(e.position())
            if cell:
                self._drag_cur = cell
                self.update()

    def mouseReleaseEvent(self, _e):
        if self.dlg.stage != "size" or not self._drag_start:
            return
        cur = self._drag_cur or self._drag_start
        self._finish_drag(self._drag_start, cur)
        self._drag_start = self._drag_cur = None

    def _finish_drag(self, a, b):
        r1, r2 = sorted((a[0], b[0]))
        c1, c2 = sorted((a[1], b[1]))
        rows, cols = r2 - r1 + 1, c2 - c1 + 1
        if rows < 2 or cols < 2:
            self.dlg.set_status("框选范围过小，至少 2 行 2 列。")
            return
        self.dlg.begin_size(rows, cols)


class ManualDialog(QtWidgets.QDialog):
    """手动创建弹窗：flow 连线 / trace 盘迹 两种模式，置顶。"""

    submitted = QtCore.Signal(int, list, dict, list)
    submitted_trace = QtCore.Signal(int, int, tuple, tuple, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("手动创建关卡")
        self.setWindowFlags(self.windowFlags() |
                            QtCore.Qt.WindowStaysOnTopHint)
        self.mode = "flow"
        self.R = 0
        self.C = 0
        self.stage = "size"
        self.endpoints = []
        self.start = None
        self.end = None
        self.red = set()
        self.portal = []
        self._build_ui()

    def _build_ui(self):
        lay = QtWidgets.QVBoxLayout(self)
        self.chk_trace = QtWidgets.QCheckBox("盘迹模式：起点走满棋盘到终点，含红区与传送门")
        self.chk_trace.toggled.connect(self._on_mode_toggle)
        lay.addWidget(self.chk_trace)

        self.hint = QtWidgets.QLabel("第一步：拖拽框选棋盘大小（支持长方形）")
        lay.addWidget(self.hint)
        self.canvas = ManualCanvas(self)
        lay.addWidget(self.canvas, alignment=QtCore.Qt.AlignHCenter)
        self.status = QtWidgets.QLabel("")
        self.status.setStyleSheet("color:#333; padding:4px;")
        lay.addWidget(self.status)

        row = QtWidgets.QHBoxLayout()
        self.btn_undo = QtWidgets.QPushButton("撤销")
        self.btn_clear = QtWidgets.QPushButton("清空点")
        self.btn_resize = QtWidgets.QPushButton("重新设置大小")
        self.btn_next = QtWidgets.QPushButton("确定")
        self.btn_undo.clicked.connect(self.undo)
        self.btn_clear.clicked.connect(self.clear_points)
        self.btn_resize.clicked.connect(self.reset_size)
        self.btn_next.clicked.connect(self._on_next)
        row.addWidget(self.btn_undo)
        row.addWidget(self.btn_clear)
        row.addWidget(self.btn_resize)
        row.addStretch(1)
        row.addWidget(self.btn_next)
        lay.addLayout(row)

    def showEvent(self, e):
        super().showEvent(e)
        self.raise_()
        self.activateWindow()
        self._force_topmost()

    def _force_topmost(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0,
                                 0x0001 | 0x0002 | 0x0040)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def set_status(self, text):
        self.status.setText(text)

    # ---- 模式 / 阶段 ----
    def _on_mode_toggle(self, checked):
        self.mode = "trace" if checked else "flow"
        self.reset_size()

    def begin_size(self, rows, cols):
        self.R, self.C = rows, cols
        if self.mode == "flow":
            self.stage = "edit"
            self.hint.setText(f"点击格子放置端点（{rows}×{cols}），"
                              "颜色按 红→黄→蓝→绿 成对出现")
        else:
            self.stage = "t_start"
            self.hint.setText("请点击一个格子作为起点")
        self.set_status("")
        self._refresh_button()
        self.canvas.update()

    def reset_size(self):
        self.R = 0
        self.C = 0
        self.stage = "size"
        self.endpoints = []
        self.start = self.end = None
        self.red = set()
        self.portal = []
        self.hint.setText("第一步：拖拽框选棋盘大小（支持长方形）")
        self.set_status("")
        self._refresh_button()
        self.canvas.update()

    def _can_next(self):
        if self.stage == "size":
            return self.R >= 2 and self.C >= 2
        if self.stage == "t_start":
            return self.start is not None
        if self.stage == "t_end":
            return self.end is not None
        return True

    def _refresh_button(self):
        if self.mode == "flow":
            self.btn_next.setText("确定")
            self.btn_next.setEnabled(True)
            return
        self.btn_next.setText("确定" if self.stage == "t_portal" else "下一步")
        self.btn_next.setEnabled(self._can_next())

    def _on_next(self):
        if self.mode == "flow":
            self._accept_flow()
            return
        if not self._can_next():
            return
        if self.stage == "t_start":
            self.stage = "t_end"
            self.hint.setText("请点击另一个格子作为终点")
        elif self.stage == "t_end":
            self.stage = "t_red"
            self.hint.setText("点击格子设置红区（不可走；再点一次取消）")
        elif self.stage == "t_red":
            self.stage = "t_portal"
            self.hint.setText("点击格子设置传送门（至多两个，可留空；再点一次取消）")
        elif self.stage == "t_portal":
            self._accept_trace()
            return
        self._refresh_button()
        self.canvas.update()

    # ---- 放格 ----
    def place_at(self, cell):
        if self.mode == "flow":
            self._place_flow(cell)
        else:
            self._place_trace(cell)

    def _place_flow(self, cell):
        r, c = cell
        if any((er, ec) == (r, c) for er, ec, *_ in self.endpoints):
            self.set_status("该格已有端点。")
            return
        rgb, idx = self.next_color()
        label = f"c{idx}"
        self.endpoints.append((r, c, label, *rgb))
        slot = len(self.endpoints) % 2
        who = "第二个" if slot == 0 else "第一个"
        self.set_status(f"已放置 {who} {label} 端点。")
        self.canvas.update()

    def _place_trace(self, cell):
        if self.stage == "t_start":
            if cell == self.end:
                self.set_status("该格已设为终点。")
                return
            self.start = cell
            self.set_status("起点已设置，点「下一步」。")
        elif self.stage == "t_end":
            if cell == self.start:
                self.set_status("该格已设为起点。")
                return
            self.end = cell
            self.set_status("终点已设置，点「下一步」。")
        elif self.stage == "t_red":
            if cell == self.start or cell == self.end or cell in self.portal:
                self.set_status("该格已被起点/终点/传送门占用。")
                return
            if cell in self.red:
                self.red.remove(cell)
            else:
                self.red.add(cell)
        elif self.stage == "t_portal":
            if cell == self.start or cell == self.end or cell in self.red:
                self.set_status("该格已被起点/终点/红区占用。")
                return
            if cell in self.portal:
                self.portal.remove(cell)
            elif len(self.portal) >= 2:
                self.set_status("传送门至多两个。")
                return
            else:
                self.portal.append(cell)
        self._refresh_button()
        self.canvas.update()

    def next_color(self):
        idx = len(self.endpoints) // 2
        return PALETTE[idx % len(PALETTE)], idx

    # ---- 撤销 / 清空 ----
    def undo(self):
        if self.mode == "flow":
            if self.endpoints:
                self.endpoints.pop()
                self.set_status("已撤销最新端点。")
            else:
                self.reset_size()
                self.set_status("没有可撤销的点，已返回大小设置。")
            self.canvas.update()
            return
        # trace：回退上一阶段
        if self.stage == "t_start":
            self.reset_size()
        elif self.stage == "t_end":
            self.start = None
            self.stage = "t_start"
            self.hint.setText("请点击一个格子作为起点")
        elif self.stage == "t_red":
            self.end = None
            self.stage = "t_end"
            self.hint.setText("请点击另一个格子作为终点")
        elif self.stage == "t_portal":
            self.red = set()
            self.stage = "t_red"
            self.hint.setText("点击格子设置红区（不可走；再点一次取消）")
        self._refresh_button()
        self.canvas.update()

    def clear_points(self):
        if self.mode == "flow":
            self.endpoints = []
            self.set_status("已清空所有端点。")
        else:
            self.red = set()
            self.portal = []
            self.set_status("已清空红区与传送门。")
        self.canvas.update()

    # ---- 提交 ----
    def _accept_flow(self):
        if self.stage == "size" or self.R < 2:
            self.set_status("请先拖拽框选题目大小。")
            return
        if self.R != self.C:
            self.set_status("连线模式请拖出正方形棋盘（行数=列数）。")
            return
        if len(self.endpoints) < 2:
            self.set_status("请至少放置一对端点。")
            return
        if len(self.endpoints) % 2 != 0:
            self.set_status("端点需成对：还差一个同色端点。")
            return
        pairs = []
        colors = {}
        for i in range(0, len(self.endpoints), 2):
            r1, c1, lab, *rgb1 = self.endpoints[i]
            r2, c2, _, *_ = self.endpoints[i + 1]
            pairs.append((lab, (r1, c1), (r2, c2)))
            colors[lab] = tuple(int(v) for v in rgb1)
        self.submitted.emit(self.R, pairs, colors, list(self.endpoints))
        self.accept()

    def _accept_trace(self):
        if self.start is None or self.end is None:
            self.set_status("请先设置起点和终点。")
            return
        portal = tuple(self.portal) if len(self.portal) == 2 else None
        self.submitted_trace.emit(self.R, self.C, self.start, self.end,
                                   set(self.red), portal)
        self.accept()


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("点阵连线求解器")
        self.mode = "flow"
        self.N = 0
        self.pairs = []
        self.colors = {}
        self.endpoints = []
        self.solution = None
        self.trace = None
        self.trace_path = None
        self.worker = None

        layout = QtWidgets.QVBoxLayout(self)

        bar = QtWidgets.QHBoxLayout()
        self.btn_capture = QtWidgets.QPushButton("截图识别")
        self.btn_capture.clicked.connect(self.on_capture)
        self.btn_manual = QtWidgets.QPushButton("手动创建")
        self.btn_manual.clicked.connect(self.open_manual)
        self.btn_solve = QtWidgets.QPushButton("求解")
        self.btn_solve.clicked.connect(self.on_solve)
        self.btn_clear = QtWidgets.QPushButton("清空")
        self.btn_clear.clicked.connect(self.on_clear)
        self.fill_chk = QtWidgets.QCheckBox("填满全部格子")
        self.fill_chk.setChecked(True)
        self.method_lbl = QtWidgets.QLabel("")
        bar.addWidget(self.btn_capture)
        bar.addWidget(self.btn_manual)
        bar.addWidget(self.btn_solve)
        bar.addWidget(self.btn_clear)
        bar.addWidget(self.fill_chk)
        bar.addStretch(1)
        bar.addWidget(self.method_lbl)
        layout.addLayout(bar)

        self.board = BoardWidget()
        layout.addWidget(self.board, alignment=QtCore.Qt.AlignHCenter)

        self.status = QtWidgets.QLabel("点击「截图识别」框选游戏点阵区域。")
        self.status.setStyleSheet("color:#333; padding:6px;")
        layout.addWidget(self.status)

    # ---- 截图 ----
    def on_capture(self):
        if self.worker and self.worker.isRunning():
            return
        self.hide()
        QtCore.QTimer.singleShot(120, self._open_selector)

    def _open_selector(self):
        # 遮罩显示前先抓一张干净全屏底图存内存；松手后从底图裁剪，
        # 这样截到的图不会带上遮罩的半透明加暗效果。
        try:
            self._full = ImageGrab.grab(all_screens=True)
        except Exception:
            self._full = None
        self.sel = SelectRect()
        self.sel.rect_ready.connect(self._on_region)
        self.sel.show()
        # 60 秒无操作自动恢复，避免主窗口一直隐藏
        QtCore.QTimer.singleShot(60000, self._selector_timeout)

    def _selector_timeout(self):
        sel = getattr(self, "sel", None)
        if sel is None:
            return
        try:
            if sel.isVisible():
                sel._finish(None, "框选超时，已自动取消。")
        except RuntimeError:
            pass

    def _on_region(self, bbox, reason=""):
        # 优先从遮罩出现前存下的干净底图裁剪；底图缺失时才实时截屏兜底
        img = None
        if bbox:
            full = getattr(self, "_full", None)
            if full is not None:
                try:
                    img = full.crop(bbox)
                except Exception as e:
                    reason = f"裁剪截图失败：{e}"
            if img is None:
                try:
                    img = ImageGrab.grab(bbox=bbox, all_screens=True)
                except Exception as e:
                    reason = f"截图失败：{e}"
        self.show()
        self.activateWindow()
        if not bbox or img is None:
            self.status.setText(reason or "已取消截图。")
            return
        res = recognizer.recognize(img)
        if not res["ok"]:
            self.status.setText(res["message"])
            QtWidgets.QMessageBox.warning(self, "识别失败", res["message"])
            return
        self.mode = "flow"
        self.trace = None
        self.trace_path = None
        self.N = res["N"]
        self.pairs = res["pairs"]
        self.colors = res["colors"]
        self.endpoints = res["endpoints"]
        self.solution = None
        self.method_lbl.setText("")
        self.status.setText(res["message"])
        self._refresh()

    # ---- 手动创建 ----
    def open_manual(self):
        if self.worker and self.worker.isRunning():
            return
        dlg = ManualDialog(self)
        dlg.submitted.connect(self._on_manual_done)
        dlg.submitted_trace.connect(self._on_trace_done)
        dlg.exec()

    def _on_manual_done(self, N, pairs, colors, endpoints):
        self.mode = "flow"
        self.trace = None
        self.trace_path = None
        self.N = N
        self.pairs = pairs
        self.colors = colors
        self.endpoints = endpoints
        self.solution = None
        self.method_lbl.setText("")
        self.status.setText("已按手动设置建立关卡，正在求解…")
        self._refresh()
        self._start_solve()

    def _on_trace_done(self, R, C, start, end, red, portal):
        self.mode = "trace"
        self.N = R
        self.pairs = []
        self.endpoints = []
        self.colors = {}
        self.solution = None
        self.trace = {"R": R, "C": C, "start": start, "end": end,
                      "red": set(red), "portal": portal}
        self.trace_path = None
        self.method_lbl.setText("")
        self.status.setText("已按盘迹设置建立关卡，正在求解…")
        self._refresh()
        self._start_trace_solve()

    # ---- 求解 ----
    def on_solve(self):
        w = self.worker
        if w is not None and w.isRunning():
            return
        if self.mode == "trace":
            if not self.trace:
                self.status.setText("当前为盘迹模式，但关卡数据为空，请重新手动创建。")
                return
            self._start_trace_solve()
            return
        if not self.pairs:
            QtWidgets.QMessageBox.information(self, "提示", "请先截图识别或手动创建关卡。")
            return
        self._start_solve()

    def _start_solve(self):
        self.btn_solve.setEnabled(False)
        self.status.setText("正在求解…")
        self.solution = None
        self._refresh()
        self.worker = SolverThread(self.N, self.pairs, self.fill_chk.isChecked())
        self.worker.done.connect(self._on_solve_done)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _on_worker_finished(self):
        self.worker = None

    def _start_trace_solve(self):
        self.btn_solve.setEnabled(False)
        self.status.setText("正在求解…")
        self.trace_path = None
        self._refresh()
        t = self.trace
        self.worker = TraceThread(t["R"], t["C"], t["start"], t["end"],
                                  t["red"], t["portal"])
        self.worker.done.connect(self._on_trace_done_solve)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()

    def _on_trace_done_solve(self, path, method, info):
        self.btn_solve.setEnabled(True)
        t = self.trace
        if path is None:
            self.status.setText(
                f"未找到可行路径（{info.get('reason', '超时或无解')}）。")
            self.method_lbl.setText("")
            return
        ok, msg = solver.validate_trace(t["R"], t["C"], t["start"], t["end"],
                                        t["red"], t["portal"], path)
        if not ok:
            self.status.setText(f"路径校验未通过：{msg}")
            return
        self.trace_path = path
        name = {"dfs": "DFS 回溯"}.get(method, method)
        nodes = info.get("nodes", "")
        elapsed = info.get("elapsed", 0)
        extra = f"，搜索节点 {nodes}" if nodes != "" else ""
        self.method_lbl.setText(f"求解：{name}　{elapsed:.2f}s{extra}")
        self.status.setText("求解完成，路径已绘制。")
        self._refresh()

    def _on_solve_done(self, sol, method, info):
        self.btn_solve.setEnabled(True)
        if sol is None:
            self.status.setText(
                f"未找到解（{info.get('reason', '超时或无解')}）。可尝试取消「填满全部格子」后重试。")
            self.method_lbl.setText("")
            return
        ok, msg = solver.validate(self.N, self.pairs, sol,
                                  require_fill=self.fill_chk.isChecked())
        if not ok:
            self.status.setText(f"解校验未通过：{msg}")
            return
        self.solution = sol
        name = {"dfs": "DFS 回溯", "z3": "Z3 兜底"}.get(method, method)
        nodes = info.get("nodes", "")
        elapsed = info.get("elapsed", 0)
        extra = f"，搜索节点 {nodes}" if nodes != "" else ""
        self.method_lbl.setText(f"求解：{name}　{elapsed:.2f}s{extra}")
        self.status.setText("求解完成，连线已绘制。")
        self._refresh()

    def on_clear(self):
        self.mode = "flow"
        self.N = 0
        self.pairs = []
        self.colors = {}
        self.endpoints = []
        self.solution = None
        self.trace = None
        self.trace_path = None
        self.method_lbl.setText("")
        self.status.setText("已清空。点击「截图识别」框选游戏点阵区域。")
        self._refresh()

    def _refresh(self):
        self.board.set_state(self.N, self.endpoints, self.colors, self.solution,
                              trace=self.trace, trace_path=self.trace_path)


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
