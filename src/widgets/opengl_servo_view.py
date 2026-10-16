#!/usr/bin/env python3
"""二维舵机云台 · 写实 3D 渲染视图（pyqtgraph.opengl）

实物感设计:
  - MG996R 风格舵机: 圆角壳体/顶盖/四角螺钉/固定耳(带过孔)/钢质输出轴+铜花键
  - U 型支架(底板+双立臂, 水平偏航) + 摄像头支架(双侧板+底托板, 垂直俯仰)
  - 相机模组: 镜筒/绿镀膜镜片/白色铭牌
  - 影棚地台: 径向渐变圆盘 + 网格 + 姿态跟随柔和投影

层级运动(顶点矩阵变换, 不依赖父子 item):
  static: 地台 / 偏航舵机体(固定)
  yaw   : 舵盘/U 型支架/俯仰舵机   —— 绕 P1(偏航轴) 水平旋转
  pitch : 舵盘/摄像头支架/相机 —— 绕 P2(俯仰轴) 垂直转动后再随 yaw 旋转
"""
import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from pyqtgraph.opengl import shaders
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

# ---------------- 工作室灯光着色器（Blinn-Phong 双光源 + 轮廓光）----------------
_STUDIO_VS = """
uniform mat4 u_mvp;
uniform mat3 u_normal;
attribute vec4 a_position;
attribute vec3 a_normal;
attribute vec4 a_color;
varying vec4 v_color;
varying vec3 v_normal;
void main() {
    v_normal = normalize(u_normal * a_normal);
    v_color = a_color;
    gl_Position = u_mvp * a_position;
}
"""
_STUDIO_FS = """
#ifdef GL_ES
precision mediump float;
#endif
varying vec4 v_color;
varying vec3 v_normal;
void main() {
    vec3 n = normalize(v_normal);
    vec3 V = vec3(0.0, 0.0, 1.0);                 /* 视线方向(相机空间近似) */
    vec3 L1 = normalize(vec3(0.42, 0.50, 0.76));   /* 主光: 右上前 */
    vec3 L2 = normalize(vec3(-0.65, -0.18, 0.48));/* 补光: 左前 */
    float d1 = max(dot(n, L1), 0.0);
    float d2 = max(dot(n, L2), 0.0);
    vec3 H1 = normalize(L1 + V);
    float sp = pow(max(dot(n, H1), 0.0), 28.0);   /* 高光 */
    float rim = pow(1.0 - max(dot(n, V), 0.0), 3.0);
    vec3 rgb = v_color.rgb * (0.42 + 0.95 * d1 + 0.35 * d2);
    rgb += (0.25 + 0.75 * v_color.rgb) * sp * 0.70;
    rgb += v_color.rgb * rim * 0.35;
    gl_FragColor = vec4(rgb, v_color.a);
}
"""
STUDIO = shaders.ShaderProgram("studio", [
    shaders.VertexShader(_STUDIO_VS), shaders.FragmentShader(_STUDIO_FS)])

# ---------------- 关键坐标（世界系, z 向上）----------------
P1 = np.array([0.00, 0.00, 4.555])     # 偏航轴（立式舵机输出轴, 沿 z）
P2 = np.array([0.00, 0.00, 7.715])     # 俯仰轴（U 臂支点/俯仰舵机输出轴, 沿 y）
CAM_CENTER = np.array([0.00, 0.00, 7.215])

# 轴向旋转矩阵（局部 z → 世界轴, 行向量约定 v @ M.T）
M_Y = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float32)   # z→+y
M_X = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]], np.float32)   # z→+x

# ---------------- 配色 ----------------
BG = "#ffffff"
C_BASE = (0.32, 0.35, 0.40, 1)
C_FEET = (0.10, 0.10, 0.12, 1)
C_LED = (0.16, 0.95, 1.00, 0.95)
C_CASE = (0.23, 0.36, 0.66, 1)
C_TAB = (0.18, 0.28, 0.52, 1)
C_SCREW = (0.22, 0.23, 0.26, 1)
C_SHAFT = (0.80, 0.82, 0.86, 1)
C_SPLINE = (0.62, 0.55, 0.34, 1)
C_HORN = (0.90, 0.88, 0.80, 1)
C_FORK = (0.26, 0.29, 0.34, 1)
C_CAM = (0.15, 0.17, 0.20, 1)
C_LENS = (0.06, 0.065, 0.075, 1)
C_GLASS = (0.15, 0.42, 0.30, 0.9)
C_LABEL = (0.93, 0.93, 0.90, 1)
C_WIRE = (0.05, 0.055, 0.065, 1)


# ============================================================
#  几何构建器（z 轴向上局部系）
# ============================================================
def rot(v, m):
    return v @ m.T


class MeshBuilder:
    def __init__(self):
        self.chunks = []

    def add(self, verts, faces):
        self.chunks.append((np.asarray(verts, np.float32),
                            np.asarray(faces, np.int32)))

    def build(self):
        vs, fs, off = [], [], 0
        for v, f in self.chunks:
            vs.append(v)
            fs.append(f + off)
            off += len(v)
        return np.concatenate(vs), np.concatenate(fs)


def box(w, d, h, cx=0.0, cy=0.0, cz=0.0):
    x0, x1 = cx - w / 2, cx + w / 2
    y0, y1 = cy - d / 2, cy + d / 2
    z0, z1 = cz - h / 2, cz + h / 2
    v = np.array([
        [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
        [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], np.float32)
    f = np.array([
        [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4], [3, 7, 6], [3, 6, 2],
        [0, 4, 7], [0, 7, 3], [1, 2, 6], [1, 6, 5]], np.int32)
    return v, f


def rounded_box(w, d, h, r=0.1, seg=6):
    """圆角盒（竖直棱圆角），中心在原点"""
    r = max(0.005, min(r, w / 2 - 0.01, d / 2 - 0.01, h / 2 - 0.01))
    corners = [((w / 2 - r), (d / 2 - r), 0.0), (-(w / 2 - r), (d / 2 - r), 90.0),
               (-(w / 2 - r), -(d / 2 - r), 180.0), ((w / 2 - r), -(d / 2 - r), 270.0)]
    ring = []
    for cx, cy, a0 in corners:
        for t in np.linspace(0, np.pi / 2, seg + 1)[:-1]:
            a = np.radians(a0) + t
            ring.append((cx + r * np.cos(a), cy + r * np.sin(a)))
    n = len(ring)
    ring = np.array(ring, np.float32)
    bot = np.concatenate([ring, np.zeros((n, 1))], 1)
    top = np.concatenate([ring, np.full((n, 1), h)], 1)
    v = np.concatenate([bot, top, [[0, 0, 0]], [[0, 0, h]]]).astype(np.float32)
    f = []
    for i in range(n):
        j = (i + 1) % n
        f += [[i, j, n + j], [i, n + j, n + i],
              [2 * n, j, i], [2 * n + 1, n + i, n + j]]
    return v, np.array(f, np.int32)


def cylinder(r, h, seg=28, caps=True):
    """z 向圆柱，底面在原点"""
    t = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    b = np.stack([r * np.cos(t), r * np.sin(t), np.zeros(seg)], 1)
    tp = np.stack([r * np.cos(t), r * np.sin(t), np.full(seg, h)], 1)
    f = []
    for i in range(seg):
        j = (i + 1) % seg
        f += [[i, j, seg + j], [i, seg + j, seg + i]]
    if caps:
        v = np.concatenate([b, tp, [[0, 0, 0]], [[0, 0, h]]]).astype(np.float32)
        for i in range(seg):
            j = (i + 1) % seg
            f += [[2 * seg, j, i], [2 * seg + 1, seg + i, seg + j]]
        return v, np.array(f, np.int32)
    return np.concatenate([b, tp]), np.array(f, np.int32)


def tube(points, r, seg=10):
    """沿折线圆管（线缆）"""
    pts = np.asarray(points, np.float32)
    tang = np.gradient(pts, axis=0)
    tang /= (np.linalg.norm(tang, axis=1, keepdims=True) + 1e-9)
    rings = []
    for p, t in zip(pts, tang):
        up = np.array([0, 0, 1.0]) if abs(np.dot(t, [0, 0, 1])) < 0.9 else np.array([1, 0, 0.0])
        n = np.cross(t, up)
        n /= (np.linalg.norm(n) + 1e-9)
        b = np.cross(t, n)
        th = np.linspace(0, 2 * np.pi, seg, endpoint=False)
        rings.append((p + r * (np.cos(th)[:, None] * n + np.sin(th)[:, None] * b)).astype(np.float32))
    m = len(rings)
    v = np.concatenate(rings)
    f = []
    for i in range(m - 1):
        for k in range(seg):
            l = (k + 1) % seg
            a, b1, c, d = i * seg + k, i * seg + l, (i + 1) * seg + l, (i + 1) * seg + k
            f += [[a, b1, c], [a, c, d]]
    return v, np.array(f, np.int32)


def radial_disc(r, seg=64, col_center=(0.2, 0.2, 0.2, 1), col_edge=(0, 0, 0, 0),
                frac=0.35):
    """三层径向渐变圆盘（z=0 平面），返回 (verts, faces, colors)"""
    t = np.linspace(0, 2 * np.pi, seg, endpoint=False)
    ri = np.stack([frac * r * np.cos(t), frac * r * np.sin(t), np.zeros(seg)], 1)
    ro = np.stack([r * np.cos(t), r * np.sin(t), np.zeros(seg)], 1)
    v = np.concatenate([np.zeros((1, 3), np.float32), ri, ro])
    f = []
    for i in range(seg):
        j = (i + 1) % seg
        f += [[0, 1 + j, 1 + i],
              [1 + i, 1 + j, 1 + seg + j], [1 + i, 1 + seg + j, 1 + seg + i]]
    cmid = tuple((a + b) / 2 for a, b in zip(col_center, col_edge))
    cols = np.concatenate([
        np.tile(np.array(col_center, np.float32), (1, 1)),
        np.tile(np.array(cmid, np.float32), (seg, 1)),
        np.tile(np.array(col_edge, np.float32), (seg, 1))])
    return v.astype(np.float32), np.array(f, np.int32), cols


# ============================================================
#  可运动部件
# ============================================================
class _Part:
    """保存基础顶点; 姿态更新后矩阵变换并重传 VBO"""

    def __init__(self, view, verts, faces, color, smooth=False,
                 shader=STUDIO, glopts="opaque", vertex_colors=None):
        self.v0 = np.ascontiguousarray(verts, np.float32)
        self.faces = np.ascontiguousarray(faces, np.int32)
        self._vc = vertex_colors
        if vertex_colors is not None:
            md = gl.MeshData(vertexes=self.v0, faces=self.faces,
                             vertexColors=vertex_colors)
        else:
            md = gl.MeshData(vertexes=self.v0, faces=self.faces)
        self.item = gl.GLMeshItem(meshdata=md, smooth=smooth, shader=shader,
                                  color=color, glOptions=glopts)
        view.addItem(self.item)

    def update(self, verts):
        self.item.setMeshData(vertexes=np.ascontiguousarray(verts, np.float32),
                              faces=self.faces, vertexColors=self._vc)


def _mk(view, verts, faces, color, **kw):
    """静态部件"""
    _Part(view, verts, faces, color, **kw)


def servo_vertical(cx, cy, z0, sx, sy, sz, shaft_dx=0.85):
    """立式舵机（轴 +z，偏航位）→ [(v, f, color), ...]
    壳体+顶盖+固定耳(带过孔) / 螺钉 / 钢轴+铜花键"""
    case, detail, metal = MeshBuilder(), MeshBuilder(), MeshBuilder()
    v, f = rounded_box(sx, sy, sz, r=0.10)
    case.add(v + np.array([cx, cy, z0 + sz / 2]), f)
    v, f = rounded_box(sx, sy, sz * 0.14, r=0.10)
    case.add(v + np.array([cx, cy, z0 + sz * 1.07]), f)
    for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
        v, f = cylinder(0.07, 0.05, seg=10)
        detail.add(v + np.array([cx + dx * (sx / 2 - 0.25),
                                cy + dy * (sy / 2 - 0.22), z0 + sz * 1.14]), f)
    for dx in (-1, 1):
        for dy in (-1, 1):
            tx, ty = cx + dx * 1.15, cy + dy * (sy / 2 + 0.26)
            v, f = box(1.05, 0.55, 0.30, tx, ty, z0 + sz * 0.52)
            case.add(v, f)
            v, f = cylinder(0.14, 0.60, seg=12)
            detail.add(rot(v, M_Y) + np.array([tx, ty - 0.30, z0 + sz * 0.52]), f)
    ax, ay = cx + shaft_dx, cy
    v, f = cylinder(0.32, 0.08, seg=18)
    metal.add(v + np.array([ax, ay, z0 + sz * 1.14]), f)
    v, f = cylinder(0.24, 0.50, seg=22)
    metal.add(v + np.array([ax, ay, z0 + sz * 1.14 + 0.06]), f)
    v, f = cylinder(0.12, 0.12, seg=16)
    metal.add(v + np.array([ax, ay, z0 + sz * 1.14 + 0.56]), f)
    return [(*case.build(), C_CASE), (*detail.build(), C_SCREW),
            (*metal.build(), C_SHAFT)]


# ============================================================
#  主视图
# ============================================================
class OpenGLServoView(QWidget):
    def __init__(self):
        super().__init__()
        self.yaw = 0.0
        self.pitch = 0.0

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.view = gl.GLViewWidget()
        self.view.setBackgroundColor(BG)
        self.view.antialias = True
        # 初始视角: 云台正对屏幕（镜头朝 +x 正对观察者）
        self.view.setCameraPosition(pos=pg.Vector(0, 0, 6.2), distance=25,
                                    elevation=12, azimuth=0)
        lay.addWidget(self.view)

        self.hud = QLabel(self)
        self.hud.setStyleSheet(
            "color:#7fe8ff;background:rgba(10,14,20,160);"
            "font-family:Consolas,monospace;font-size:15px;"
            "border:1px solid rgba(90,200,255,70);border-radius:6px;"
            "padding:5px 10px;")
        self.hud.move(14, 12)
        # 启动即显示当前初始角度(0,0); 否则 _tick 在无差值时不触发
        # set_pose, HUD 会一直空白直到用户首次操作
        self.hud.setText("YAW %+.1f°   PITCH %+.1f°" % (self.yaw, self.pitch))
        self.hud.adjustSize()

        self.parts_yaw = []
        self.parts_pitch = []
        self._build_scene()

    # ---------------- 场景 ----------------
    def _build_scene(self):
        V = self.view

        # 影棚地面（径向渐变）+ 网格
        gv, gf, gc = radial_disc(16, seg=72, frac=0.30,
                                 col_center=(0.58, 0.59, 0.62, 1),
                                 col_edge=(0.76, 0.77, 0.80, 1))
        md = gl.MeshData(vertexes=gv, faces=gf, vertexColors=gc)
        V.addItem(gl.GLMeshItem(meshdata=md, smooth=False, shader=STUDIO))

        grid = gl.GLGridItem(color=(0.50, 0.54, 0.60, 0.50))
        grid.scale(2, 2, 1)
        grid.translate(0, 0, 0.012)
        V.addItem(grid)

        # 柔和投影: 底座（静态）+ 相机（随姿态）
        sv, sf, sc = radial_disc(5.4, seg=48, frac=0.4,
                                 col_center=(0, 0, 0, 0.42), col_edge=(0, 0, 0, 0))
        md = gl.MeshData(vertexes=sv + np.array([0, 0, 0.02]), faces=sf,
                         vertexColors=sc)
        V.addItem(gl.GLMeshItem(meshdata=md, smooth=False, shader=None,
                                glOptions="translucent"))
        cv, cf, cc = radial_disc(1.8, seg=36, frac=0.4,
                                 col_center=(0, 0, 0, 0.30), col_edge=(0, 0, 0, 0))
        self.cam_shadow = _Part(V, cv + np.array([CAM_CENTER[0], CAM_CENTER[1], 0.03]),
                                cf, (0, 0, 0, 1), shader=None,
                                glopts="translucent", vertex_colors=cc)

        # 底座（枪灰圆角地台 + 橡胶脚垫 + 灯带）
        v, f = rounded_box(7.6, 7.6, 0.75, r=0.22)
        _mk(V, v + np.array([0, 0, 0.725]), f, C_BASE)
        for sx, sy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
            v, f = cylinder(0.40, 0.35, seg=20)
            _mk(V, v + np.array([sx * 3.0, sy * 3.0, 0.0]), f, C_FEET)
        lv, lf = box(0.22, 6.4, 0.10, 3.42, 0, 1.13)
        _mk(V, lv, lf, C_LED, shader=None, glopts="translucent")

        # 偏航舵机（立式, 装于底座盒内, 输出轴自盒顶穿出, 居中于 P1）
        for v, f, c in servo_vertical(0, 0, 0.21, 4.0, 2.05, 2.10, shaft_dx=0.0):
            _mk(V, v, f, c)

        # 长方形底座盒（把偏航舵机封装在内, 盒宽大于 U 臂, 盒底紧贴地台顶）
        mb = MeshBuilder()
        v, f = rounded_box(6.2, 5.6, 2.57, r=0.08)
        mb.add(v + np.array([0, 0, 1.475]), f)              # 盒体 z 1.475..4.045
        v, f = mb.build()
        _mk(V, v, f, C_FORK)
        mb = MeshBuilder()
        v, f = cylinder(0.16, 0.10, seg=16)                 # 线缆孔圈(-y 面)
        mb.add(rot(v, M_Y) + np.array([0.90, -2.90, 1.79]), f)
        v, f = box(0.12, 2.2, 1.4, 3.16, 0, 1.89)           # 侧面铭牌(+x 正面)
        mb.add(v, f)
        v, f = mb.build()
        _mk(V, v, f, C_HORN)
        mb = MeshBuilder()                                   # 盒四侧面盖螺丝(恒亮银)
        v, f = cylinder(0.11, 0.09, seg=14)
        mb.add(rot(v, M_X) + np.array([3.10, 0, 1.89]), f)    # +x 面
        v, f = cylinder(0.11, 0.09, seg=14)
        mb.add(rot(v, M_X) + np.array([-3.19, 0, 1.89]), f)    # -x 面
        v, f = cylinder(0.11, 0.09, seg=14)
        mb.add(rot(v, M_Y) + np.array([0.80, 2.80, 1.89]), f)  # +y 面
        v, f = cylinder(0.11, 0.09, seg=14)
        mb.add(rot(v, M_Y) + np.array([0.80, -2.89, 1.89]), f)  # -y 面
        v, f = mb.build()
        _mk(V, v, f, C_SHAFT, shader=None)

        # 支座（盒顶与 U 底板之间衔接; 舵机轴与舵盘藏于其内）
        # 两端各微重叠 0.02 消除共面衔接的 z-fighting(否则正对视角边线闪烁似穿模)
        v, f = cylinder(0.60, 1.125, seg=24)
        _mk(V, v + np.array([0, 0, 4.03]), f, C_SHAFT)    # 支座 z 4.03..5.155

        # 线缆（自盒 -y 面线缆孔引出, 绕至底座）
        v, f = tube([[0.90, -2.95, 1.79], [1.35, -3.55, 1.49],
                     [1.40, -3.75, 1.04], [1.35, -3.80, 0.69]], 0.085, seg=10)
        _mk(V, v, f, C_WIRE, smooth=True)

        # ---------- yaw 层: U 型支架 + 俯仰舵机 ----------
        def yaw_part(verts, faces, color, **kw):
            self.parts_yaw.append(_Part(V, verts, faces, color, **kw))

        # 尼龙舵盘（轴套, 套在 P1 输出轴上, 藏于支座内; 上段穿入 U 底板连接）
        mb = MeshBuilder()
        v, f = cylinder(0.40, 0.18, seg=32)
        mb.add(v + np.array([P1[0], P1[1], P1[2] - 0.09]), f)
        v, f = cylinder(0.28, 0.15, seg=20)
        mb.add(v + np.array([P1[0], P1[1], P1[2] + 0.09]), f)
        v, f = mb.build()
        yaw_part(v, f, C_HORN)

        # U 型支架: 圆角底板 + 双立臂 + 臂顶帽梁（阳极氧化黑铝）
        # 立臂高度缩减为 3/4(4.6→3.45), 以俯仰轴 P2 为中心
        mb = MeshBuilder()
        v, f = rounded_box(5.2, 5.2, 0.38, r=0.18)
        mb.add(v + np.array([0, 0, P1[2] + 0.20]), f)            # 底板 z 4.755..5.135
        for dy in (-1, 1):
            v, f = box(4.6, 0.42, 3.45, 0, dy * 2.0, 5.99)     # 立臂 z 4.265..7.715
            mb.add(v, f)
            v, f = box(4.6, 0.42, 0.30, 0, dy * 2.0, 7.865)      # 臂顶帽梁 z 7.715..8.015
            mb.add(v, f)
        v, f = mb.build()
        yaw_part(v, f, C_FORK)

        # 立臂俯仰轴过孔（轴套圈, 自支架侧板外面凸至臂面）
        mb = MeshBuilder()
        for a, h in ((1.77, 0.44), (-2.21, 0.44)):
            v, f = cylinder(0.36, h, seg=16)
            mb.add(rot(v, M_Y) + np.array([0, a, P2[2]]), f)
        v, f = mb.build()
        yaw_part(v, f, C_SCREW)

        # 俯仰舵盘（-y 立臂外侧面, 固定不动——舵机转子驱动摄像头支架总成绕其转动）
        mb = MeshBuilder()
        v, f = cylinder(0.95, 0.18, seg=32)
        mb.add(rot(v, M_Y) + np.array([0, -2.39, P2[2]]), f)   # 圆盘 y -2.39..-2.21
        v, f = cylinder(0.28, 0.26, seg=20)
        mb.add(rot(v, M_Y) + np.array([0, -2.65, P2[2]]), f)   # 轴套 y -2.65..-2.39
        v, f = mb.build()
        yaw_part(v, f, C_HORN)
        mb = MeshBuilder()                                      # 盘面固定螺丝
        for px_, pz_ in [(0.42, 0.42), (-0.42, -0.42)]:
            v, f = cylinder(0.08, 0.06, seg=10)
            mb.add(rot(v, M_Y) + np.array([px_, -2.45, P2[2] + pz_]), f)
        v, f = mb.build()
        yaw_part(v, f, C_SCREW, shader=None)

        # +y 侧支点: 六角螺栓自臂外拧入, 螺杆穿臂与侧板连接摄像头支架
        mb = MeshBuilder()
        v, f = cylinder(0.34, 0.14, seg=6)
        mb.add(rot(v, M_Y) + np.array([0, 2.21, P2[2]]), f)    # 六角头 y 2.21..2.35
        v, f = cylinder(0.10, 0.74, seg=12)
        mb.add(rot(v, M_Y) + np.array([0, 1.48, P2[2]]), f)    # 螺杆 y 1.48..2.22
        v, f = mb.build()
        yaw_part(v, f, C_SHAFT, shader=None)

        # ---------- pitch 层: 摄像头支架(内装俯仰舵机) + 相机 ----------
        # 装配链: U 型架内侧边 -> 支架外侧边 -> 支架底边 -> 摄像头(绑于底边反面)
        def pitch_part(verts, faces, color, **kw):
            self.parts_pitch.append(_Part(V, verts, faces, color, **kw))

        # 摄像头支架: C 形框(双外侧板 + 底边竖板), 外侧板贴合 U 型架内侧边
        # 框高与相机壳体一致(2.6), 以俯仰轴 P2 为中心
        mb = MeshBuilder()
        for dy in (-1, 1):                                      # 双外侧板 y ±1.47..1.77
            v, f = box(2.40, 0.30, 2.60, 0, dy * 1.62, 7.715)
            mb.add(v, f)                                        # 板 z 6.415..9.015
        v, f = box(0.30, 3.54, 2.60, 1.05, 0, 7.715)            # 底边竖板 x 0.90..1.20
        mb.add(v, f)                                            # 板 z 6.415..9.015
        v, f = mb.build()
        pitch_part(v, f, C_FORK)

        # 俯仰舵机（装于支架框内, 输出轴穿侧板与 U 臂过孔, 接 -y 外侧舵盘）
        mb = MeshBuilder()
        v, f = rounded_box(2.05, 2.91, 1.80, r=0.10)           # 壳体 y -1.47..1.44
        mb.add(v + np.array([0, -0.015, 6.90]), f)             # 壳体 z 6.00..7.80
        v, f = box(1.85, 0.12, 1.60, 0, 1.38, 6.90)            # 尾部端盖 z 6.10..7.70
        mb.add(v, f)
        v, f = cylinder(0.24, 0.77, seg=22)                     # 输出轴穿板至舵盘
        mb.add(rot(v, M_Y) + np.array([0, -2.21, 6.90]), f)    # 轴 y -2.21..-1.44
        v, f = cylinder(0.12, 0.28, seg=16)                    # 花键尖穿舵盘
        mb.add(rot(v, M_Y) + np.array([0, -2.49, 6.90]), f)    # 尖 y -2.49..-2.21
        v, f = mb.build()
        pitch_part(v, f, C_CASE)
        mb = MeshBuilder()                                      # 壳体面板小螺钉
        for px_, pz_ in [(-0.7, -0.60), (0.7, -0.60),
                         (-0.7, 0.60), (0.7, 0.60)]:
            v, f = cylinder(0.06, 0.05, seg=10)
            mb.add(rot(v, M_Y) + np.array([px_, -1.49, 6.90 + pz_]), f)
        v, f = mb.build()
        pitch_part(v, f, C_SCREW, shader=None)

        # 舵机固定螺栓（自侧板外面拧入, 4 颗恒亮银）
        mb = MeshBuilder()
        for px_, pz_ in [(-0.70, 7.065), (0.70, 7.065),
                         (-0.70, 8.365), (0.70, 8.365)]:
            v, f = cylinder(0.09, 0.07, seg=12)
            mb.add(rot(v, M_Y) + np.array([px_, -1.84, pz_]), f)
        v, f = mb.build()
        pitch_part(v, f, C_SHAFT, shader=None)

        # 舵机线缆（框内短辫, 自壳尾下垂）
        v, f = tube([[0, 1.44, 7.415], [0.15, 1.30, 6.915],
                     [0.30, 1.18, 6.535]], 0.055, seg=8)
        pitch_part(v, f, C_WIRE, smooth=True)

        # 相机安装垫板（底边反面, 与相机同高）
        v, f = box(0.12, 1.70, 1.60, 1.26, 0, 7.215)            # 垫板 x 1.20..1.32
        pitch_part(v, f, C_SCREW)

        # 相机模组（壳体背贴垫板, 镜头沿 +x; 与 C 形支架同高居中, 镜头在壳体正中）
        CAM_Z = 7.215                                            # 相机中心 z
        mb = MeshBuilder()
        v, f = rounded_box(2.00, 2.6, 2.4, r=0.06)
        mb.add(v + np.array([2.32, 0, CAM_Z - 1.2]), f)         # 壳体底面落位 z 6.015..8.415
        v, f = box(1.8, 2.4, 0.08, 2.32, 0, CAM_Z + 1.16)       # 顶盖接缝
        mb.add(v, f)
        v, f = cylinder(0.58, 0.62, seg=28)                     # 镜筒
        mb.add(rot(v, M_X) + np.array([3.32, 0, CAM_Z]), f)
        v, f = cylinder(0.65, 0.06, seg=28)                     # 镜头压圈
        mb.add(rot(v, M_X) + np.array([3.94, 0, CAM_Z]), f)
        v, f = mb.build()
        pitch_part(v, f, C_CAM)

        # 前面板四角固定螺丝（按实物）
        mb = MeshBuilder()
        for py_, pz_ in [(-0.95, -0.85), (0.95, -0.85),
                         (-0.95, 0.85), (0.95, 0.85)]:
            v, f = cylinder(0.07, 0.07, seg=12)
            mb.add(rot(v, M_X) + np.array([3.32, py_, CAM_Z + pz_]), f)
        v, f = mb.build()
        pitch_part(v, f, C_SHAFT, shader=None)

        # 镜片（半透明绿镀膜 + 内瞳）
        v, f = cylinder(0.48, 0.07, seg=24)
        pitch_part(rot(v, M_X) + np.array([4.00, 0, CAM_Z]), f, C_GLASS,
                   shader=None, glopts="translucent")
        v, f = cylinder(0.22, 0.04, seg=20)
        pitch_part(rot(v, M_X) + np.array([4.07, 0, CAM_Z]), f,
                   (0.02, 0.02, 0.03, 1), shader=None)
        # 白色铭牌（前面板下部, 按实物）
        v, f = box(0.05, 1.00, 0.55, 3.345, 0, CAM_Z - 0.80)
        pitch_part(v, f, C_LABEL, shader=None)

    # ---------------- 姿态 ----------------
    @staticmethod
    def _rot_z(t):
        c, s = np.cos(t), np.sin(t)
        return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], np.float32)

    @staticmethod
    def _rot_y(t):
        c, s = np.cos(t), np.sin(t)
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], np.float32)

    def set_pose(self, yaw_deg, pitch_deg):
        self.yaw = float(np.clip(yaw_deg, -90, 90))
        self.pitch = float(np.clip(pitch_deg, -90, 90))
        y, p = np.radians(self.yaw), np.radians(self.pitch)
        Rz = self._rot_z(y)
        Ry = self._rot_y(-p)     # +pitch = 抬头

        def tf_yaw(v):
            return (v - P1) @ Rz.T + P1

        def tf_pitch(v):
            return tf_yaw((v - P2) @ Ry.T + P2)

        for part in self.parts_yaw:
            part.update(tf_yaw(part.v0))
        for part in self.parts_pitch:
            part.update(tf_pitch(part.v0))

        # 相机地面投影柔影
        c = tf_pitch(CAM_CENTER)
        r = 1.3 + c[2] * 0.09
        t = np.linspace(0, 2 * np.pi, 36, endpoint=False)
        ro = np.stack([r * np.cos(t) + c[0], r * np.sin(t) + c[1],
                       np.full(36, 0.03)], 1)
        ri = 0.4 * (ro - np.array([c[0], c[1], 0.0])) + np.array([c[0], c[1], 0.03])
        v = np.concatenate([np.array([[c[0], c[1], 0.03]], np.float32), ri, ro])
        self.cam_shadow.update(v)

        self.hud.setText("YAW %+.1f°   PITCH %+.1f°" % (self.yaw, self.pitch))
        self.hud.adjustSize()
        self.view.update()


# ---------------- 独立预览/截图 ----------------
if __name__ == "__main__":
    import os
    import sys

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    w = OpenGLServoView()
    w.resize(1100, 760)
    w.show()

    state = {"t": 0.0}

    def tick():
        state["t"] += 0.03
        w.set_pose(50 * np.sin(state["t"]), 35 * np.sin(state["t"] * 0.7))

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(33)

    shot = os.environ.get("SERVO_VIEW_SHOT")
    pose_str = os.environ.get("SERVO_VIEW_POSE", "24,14")
    if shot:
        timer.stop()
        pw = [float(x) for x in pose_str.split(",")]
        w.set_pose(pw[0], pw[1])

        def grab():
            w.grab().save(shot)
            app.quit()
        QTimer.singleShot(1200, grab)

    sys.exit(app.exec())
