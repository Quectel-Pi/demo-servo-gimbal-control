#!/usr/bin/env python3
"""云台操控面板: 3D 视图 + 滑块/按钮/预设/自动演示/日志（PCA9685 直驱版）

交互:
  滑块(±90°) 拖动即驱动 3D 画面与真实舵机（PCA9685 50Hz 软步进）
  键盘 W/S/A/D ±5°, Space 归中（在 MainWindow 中分发）
  「Auto Demo」: 正弦扫掠, 用于展示/验收录像
"""
import math

from PySide6.QtCore import Qt, QTimer, QTime
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QSlider, QTextEdit,
    QVBoxLayout, QWidget)

from controller.gimbal_controller import GimbalController, YAW_TRIM, PITCH_TRIM
from widgets.opengl_servo_view import OpenGLServoView

ACCENT = "#29d3ff"


class ServoPanel(QWidget):
    def __init__(self, bus=7, addr=0x40):
        super().__init__()
        self.controller = GimbalController(bus=bus, addr=addr)
        self.sweeping = False
        self._sweep_t = 0.0
        self._sweep_ph_y = 0.0      # 初始相位(从当前角度续入, 避免跳变)
        self._sweep_ph_p = 0.0

        self.tgt_yaw = 0.0
        self.tgt_pitch = 0.0
        self.disp_yaw = 0.0
        self.disp_pitch = 0.0

        self.init_ui()
        self.bind_controller()
        self._anim = QTimer(self)
        self._anim.timeout.connect(self._tick)
        self._anim.start(16)

    # ---------------- UI ----------------
    def init_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # 左: 3D 视图
        self.view = OpenGLServoView()
        root.addWidget(self.view, 3)

        # 右: 控制列
        right = QVBoxLayout()
        right.setSpacing(8)

        title = QLabel("2-Axis Servo Gimbal Console")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignCenter)
        sub = QLabel(" I2C /dev/i2c-7 @ 0x40"
                     " · 50 Hz · PWM 500–2500 µs")
        sub.setObjectName("sub")
        sub.setAlignment(Qt.AlignCenter)
        right.addWidget(title)
        right.addWidget(sub)

        # 状态（PCA9685 无电压反馈, 仅显示 I2C 连接状态）
        self.lbl_link = QLabel("○ Connecting…")
        self.lbl_link.setObjectName("link")
        right.addWidget(self.lbl_link)

        # YAW
        gb1 = QGroupBox("Yaw (Horizontal · Servo 2 · CH0)")
        l1 = QVBoxLayout(gb1)
        self.yaw_readout = QLabel("0° · 1500 µs")
        self.yaw_readout.setObjectName("readout")
        self.yaw_slider = self._make_slider(-90, 90, 0)
        self.yaw_readout.setAlignment(Qt.AlignCenter)
        l1.addWidget(self.yaw_readout)
        l1.addWidget(self.yaw_slider)
        b1 = QHBoxLayout()
        for txt, fn in [("◀ −5", lambda: self.update_yaw(self.tgt_yaw - 5)),
                        ("Center", lambda: self.update_yaw(0)),
                        ("+5 ▶", lambda: self.update_yaw(self.tgt_yaw + 5))]:
            btn = QPushButton(txt)
            btn.clicked.connect(fn)
            b1.addWidget(btn)
        l1.addLayout(b1)
        right.addWidget(gb1)

        # PITCH（行程 130°: -40 低头 ~ +90 垂直向上）
        gb2 = QGroupBox("Pitch (Vertical · Servo 1 · CH1 · −40°~+90°)")
        l2 = QVBoxLayout(gb2)
        self.pitch_readout = QLabel("0° · 1500 µs")
        self.pitch_readout.setObjectName("readout")
        self.pitch_readout.setAlignment(Qt.AlignCenter)
        self.pitch_slider = self._make_slider(-40, 90, 0)
        l2.addWidget(self.pitch_readout)
        l2.addWidget(self.pitch_slider)
        b2 = QHBoxLayout()
        for txt, fn in [("▼ −5", lambda: self.update_pitch(self.tgt_pitch - 5)),
                        ("Center", lambda: self.update_pitch(0)),
                        ("+5 ▲", lambda: self.update_pitch(self.tgt_pitch + 5))]:
            btn = QPushButton(txt)
            btn.clicked.connect(fn)
            b2.addWidget(btn)
        l2.addLayout(b2)
        right.addWidget(gb2)

        # 预设 + 自动演示
        gb3 = QGroupBox("Demo Actions")
        l3 = QVBoxLayout(gb3)
        p1 = QHBoxLayout()
        for txt, yaw, pitch in [("Left", -60, 0), ("Up", 0, 90),
                                 ("Right", 60, 0), ("Down", 0, -40)]:
            btn = QPushButton(txt)
            btn.clicked.connect(lambda _, y=yaw, p=pitch: self.set_target(y, p))
            p1.addWidget(btn)
        l3.addLayout(p1)
        p2 = QHBoxLayout()
        self.btn_center = QPushButton("◎ Center Both")
        self.btn_center.setObjectName("primary")
        self.btn_center.clicked.connect(lambda: self.set_target(0, 0))
        self.btn_sweep = QPushButton("▶ Auto Demo")
        self.btn_sweep.setObjectName("sweep")
        self.btn_sweep.setCheckable(True)
        self.btn_sweep.clicked.connect(self.toggle_sweep)
        p2.addWidget(self.btn_center)
        p2.addWidget(self.btn_sweep)
        l3.addLayout(p2)
        right.addWidget(gb3)

        # 日志
        self.log_window = QTextEdit()
        self.log_window.setReadOnly(True)
        right.addWidget(self.log_window, 1)

        right_col = QWidget()
        right_col.setLayout(right)
        right_col.setFixedWidth(370)
        root.addWidget(right_col, 1)

        self.apply_theme()
        self.log("Ready · PCA9685 backend · TRIM YAW=%+.0f° PITCH=%+.0f°"
                 % (YAW_TRIM, PITCH_TRIM))

    @staticmethod
    def _make_slider(lo, hi, val):
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        s.setTickPosition(QSlider.TicksBelow)
        s.setTickInterval(30)
        return s

    # ---------------- 控制器绑定 ----------------
    def bind_controller(self):
        self.yaw_slider.sliderMoved.connect(self._on_yaw_slider)
        self.yaw_slider.sliderReleased.connect(self._on_yaw_release)
        self.pitch_slider.sliderMoved.connect(self._on_pitch_slider)
        self.pitch_slider.sliderReleased.connect(self._on_pitch_release)

        self.controller.connectedChanged.connect(self._on_link)
        self.controller.logMessage.connect(self.log)

        # 控制器构造时 UI 尚未连接信号，初始状态在此补发
        self._on_link(*self.controller.link_state())

    def _on_link(self, ok, msg):
        self.lbl_link.setProperty("ok", bool(ok))
        if ok:
            self.lbl_link.setText("● I2C connected: %s" % msg)
            self.lbl_link.setProperty("ok", True)
            self.log("I2C connected: %s" % msg)
        else:
            self.lbl_link.setText("○ %s" % msg)
            self.lbl_link.setProperty("ok", False)
            self.log(msg)
        self.lbl_link.style().unpolish(self.lbl_link)
        self.lbl_link.style().polish(self.lbl_link)

    # ---------------- 目标管理 ----------------
    def set_target(self, yaw, pitch):
        self.update_yaw(yaw)
        self.update_pitch(pitch)

    def update_yaw(self, angle):
        angle = max(-90.0, min(90.0, float(angle)))
        self.tgt_yaw = angle
        self._sync_yaw_ui()
        self.controller.set_yaw(angle)

    def update_pitch(self, angle):
        angle = max(-40.0, min(90.0, float(angle)))
        self.tgt_pitch = angle
        self._sync_pitch_ui()
        self.controller.set_pitch(angle)

    def _sync_yaw_ui(self):
        self.yaw_slider.blockSignals(True)
        self.yaw_slider.setValue(int(round(self.tgt_yaw)))
        self.yaw_slider.blockSignals(False)
        pulse = self.controller.pulse_of(self.tgt_yaw)
        self.yaw_readout.setText("%+.1f° · %d µs" % (self.tgt_yaw, pulse))

    def _sync_pitch_ui(self):
        self.pitch_slider.blockSignals(True)
        self.pitch_slider.setValue(int(round(self.tgt_pitch)))
        self.pitch_slider.blockSignals(False)
        pulse = self.controller.pulse_of(self.tgt_pitch, invert=True)
        self.pitch_readout.setText("%+.1f° · %d µs" % (self.tgt_pitch, pulse))

    def _on_yaw_slider(self, v):
        self.update_yaw(v)

    def _on_pitch_slider(self, v):
        self.update_pitch(v)

    def _on_yaw_release(self):
        self.log("YAW → %+.0f° (%d µs)" % (self.tgt_yaw,
                                           self.controller.pulse_of(self.tgt_yaw)))

    def _on_pitch_release(self):
        self.log("PITCH → %+.0f° (%d µs)" % (self.tgt_pitch,
                                            self.controller.pulse_of(
                                                self.tgt_pitch, invert=True)))

    # ---------------- 自动演示（最开始的演示速度, 3 个周期后自动停）----------------
    # 恢复最早的演示速度(rad/s): YAW 0.9 / PITCH 0.6
    # "3 个周期"按 YAW 计 3 圈(≈20.9s); 期间 PITCH 恰好完成 2 圈,
    # 两轴都在整圈时刻结束 -> 收尾平滑回到起始姿态、无跳变
    SWEEP_W_Y = 0.9
    SWEEP_W_P = 0.6
    SWEEP_CYCLES = 3

    @property
    def _sweep_end(self):
        return self.SWEEP_CYCLES * (2.0 * math.pi / self.SWEEP_W_Y)

    def toggle_sweep(self):
        self.sweeping = self.btn_sweep.isChecked()
        if self.sweeping:
            # 从云台当前角度解算初始相位, 演示自当前位置平滑续入
            self._sweep_t = 0.0
            self._sweep_ph_y = math.asin(
                max(-1.0, min(1.0, self.tgt_yaw / 50.0)))
            self._sweep_ph_p = math.asin(
                max(-1.0, min(1.0, self.tgt_pitch / 35.0)))
            self.log("Auto demo: 3 cycles from current pose"
                     " (YAW ±50° / PITCH ±35°, ~%.0fs)" % self._sweep_end)
        else:
            self.log("Auto demo: stopped")

    # ---------------- 动画循环 ----------------
    def _tick(self):
        if self.sweeping:
            self._sweep_t += 0.016
            y = 50.0 * math.sin(self._sweep_t * self.SWEEP_W_Y
                                + self._sweep_ph_y)
            p = 35.0 * math.sin(self._sweep_t * self.SWEEP_W_P
                                + self._sweep_ph_p)
            if self._sweep_t >= self._sweep_end:
                # 满 3 周期: 收尾精确回到起始姿态并自动停止
                y = 50.0 * math.sin(self._sweep_ph_y)
                p = 35.0 * math.sin(self._sweep_ph_p)
                self.sweeping = False
                self.btn_sweep.setChecked(False)
                self.log("Auto demo: 3 cycles completed")
            self.tgt_yaw, self.tgt_pitch = y, p
            self._sync_yaw_ui()
            self._sync_pitch_ui()
            self.controller.set_yaw(y)
            self.controller.set_pitch(p)

        # 显示角度缓动逼近目标（3D 画面平滑）
        k = 0.25
        if abs(self.tgt_yaw - self.disp_yaw) > 0.02 or \
           abs(self.tgt_pitch - self.disp_pitch) > 0.02:
            self.disp_yaw += (self.tgt_yaw - self.disp_yaw) * k
            self.disp_pitch += (self.tgt_pitch - self.disp_pitch) * k
            self.view.set_pose(self.disp_yaw, self.disp_pitch)

    # ---------------- 日志 ----------------
    def log(self, text):
        self.log_window.append(
            QTime.currentTime().toString("HH:mm:ss") + "  " + text)

    def shutdown(self):
        self._anim.stop()
        self.controller.close()

    # ---------------- 主题 ----------------
    def apply_theme(self):
        self.setStyleSheet("""
            QWidget { background:#14161a; color:#dfe5ec; font-size:14px; }
            QLabel#title { font-size:17px; font-weight:700; color:#eaf6ff; }
            QLabel#sub { color:#7c8794; font-size:12px; }
            QLabel#readout { font-family:Consolas,monospace; font-size:16px;
                             color:#7fe8ff; font-weight:700; }
            QLabel#link { font-size:13px; color:#e0a93c; padding:2px 0; }
            QLabel#link[ok="true"] { color:#3ddc84; }
            QGroupBox { border:1px solid #2a2f38; border-radius:10px;
                        margin-top:14px; padding:10px 10px 8px 10px;
                        font-weight:600; color:#aebccd; }
            QGroupBox::title { subcontrol-origin:margin; left:12px;
                               padding:0 4px; }
            QSlider::groove:horizontal { height:6px; border-radius:3px;
                                          background:#262b33; }
            QSlider::sub-page:horizontal { border-radius:3px;
                                           background:qlineargradient(
                                           x1:0,y1:0,x2:1,y2:0,
                                           stop:0 #16688c, stop:1 %s); }
            QSlider::handle:horizontal { width:18px; height:18px;
                margin:-7px 0; border-radius:9px; background:#e8f6ff;
                border:2px solid %s; }
            QPushButton { background:#1d2229; border:1px solid #333a45;
                          border-radius:8px; padding:9px 6px; color:#dfe5ec; }
            QPushButton:hover { background:#242b34; border-color:#3d4753; }
            QPushButton:pressed { background:#2c3a3f; }
            QPushButton:disabled { color:#5a6470; }
            QPushButton#primary { background:#0f7c5a; border-color:#17a97c;
                                  font-weight:700; }
            QPushButton#primary:hover { background:#139a70; }
            QPushButton#sweep { background:#5a4a12; border-color:#8a6d1c;
                                font-weight:700; }
            QPushButton#sweep:checked { background:#8a6d1c; }
            QTextEdit { background:#101318; color:#9db2c5; border:1px solid #262b33;
                        border-radius:8px; font-family:Consolas,monospace;
                        font-size:12px; }
        """ % (ACCENT, ACCENT))