#!/usr/bin/env python3
"""二维舵机云台控制器：UI 角度 ↔ PCA9685 脉宽，软步进平滑 + 启动校正

角度约定（与 3D 画面一致）:
    yaw / pitch ∈ [-90, +90]，0 为中位
    舵机角 = 角度 + 90  →  脉宽 = 500 + 舵机角/180 * 2000  (µs)
运动     : PCA9685 是"写一次即瞬变"的硬件 PWM, 本身没有片上缓动,
          由本控制器以 50Hz 软步进把当前脉宽逐步逼近目标脉宽
          （步长由 Duration 滑块决定）。
无 PCA9685 I2C 时自动进入仿真模式（UI 正常演示, 不发送）。
启动     : 自动下发【校正后的归中位置】(中位 + TRIM), 云台上电即居中。
"""
import threading
import time

from PySide6.QtCore import QObject, Signal

from driver.pca9685 import PCA9685

PITCH_SERVO = 1   # 垂直俯仰 —— 舵机1 → PCA9685 CH1
YAW_SERVO = 0     # 水平偏航 —— 舵机2 → PCA9685 CH0

# 俯仰行程 130°: -40(低头下限) ~ +90(垂直向上)
PITCH_MIN, PITCH_MAX = -40.0, 90.0

# 中位微调(度): 补偿舵盘花键装配齿位/舵机个体中位偏差
# 程序 0° 时若实物有偏移, 按偏移方向填入: YAW 正值=向右补偿; PITCH 正值=抬高补偿
# 2026-10-10 标定记录: TRIM=0 偏左 10°→+10; 仍偏左 5°→+15
YAW_TRIM = 15.0
PITCH_TRIM = 0.0

TICK_S = 0.02                  # 软步进周期 50Hz
_STEP_EPS = 0.5                # 步进收敛判定(µs)


def angle_to_pulse(deg_0_180: float) -> int:
    """舵机角 0..180° → 脉宽 500..2500µs（90° = 1500 中位）"""
    a = max(0.0, min(180.0, deg_0_180))
    return int(round(500 + a / 180.0 * 2000))


class GimbalController(QObject):
    connectedChanged = Signal(bool, str)   # (是否连接, 说明)
    logMessage = Signal(str)

    def __init__(self, bus=7, addr=0x40, dur_ms=150):
        super().__init__()
        self.dur_ms = dur_ms
        self.yaw = 0.0     # 当前目标角（±90）
        self.pitch = 0.0
        self._lock = threading.Lock()
        self._running = True

        # 启动校正: 初始目标 = 中位 + trim 对应的舵机角脉宽, 上电即居中
        init = self._servo_pulse(0.0, 0.0)
        self._target = dict(init)
        self._cur = dict(init)             # 当前脉宽 = 目标, 开机无爬行

        self.pca = PCA9685(bus=bus, addr=addr)
        if self.pca.connected:
            for ch, us in init.items():
                self.pca.set_pulse_us(ch, us)

        threading.Thread(target=self._writer, daemon=True).start()
        self.connectedChanged.emit(*self.link_state())

    def link_state(self):
        """(是否连接, 说明) —— UI 绑定信号后调用此方法补发初始状态"""
        if self.pca.connected:
            return True, "/dev/i2c-%d · 0x%02X" % (self.pca.bus_no,
                                                   self.pca.addr)
        return False, ("Simulation mode (no PCA9685 on /dev/i2c-%d)"
                       % self.pca.bus_no)

    # ---------------- 角度接口（±90，0=中位）----------------
    @staticmethod
    def _clamp(deg):
        return max(-90.0, min(90.0, float(deg)))

    @staticmethod
    def _servo_pulse(yaw, pitch):
        """(yaw, pitch) ±90° → 舵机角 0..180° → 脉宽 µs（含 TRIM 补偿）"""
        servo_yaw = GimbalController._clamp(yaw + YAW_TRIM) + 90
        # 实机俯仰方向与程序相反: 舵机角 = 90 - pitch + trim
        servo_pitch = GimbalController._clamp(PITCH_TRIM - pitch) + 90
        return {YAW_SERVO: angle_to_pulse(servo_yaw),
                PITCH_SERVO: angle_to_pulse(servo_pitch)}

    def set_yaw(self, deg):
        self.yaw = self._clamp(deg)
        with self._lock:
            self._target[YAW_SERVO] = \
                GimbalController._servo_pulse(deg, self.pitch)[YAW_SERVO]

    def set_pitch(self, deg):
        self.pitch = max(PITCH_MIN, min(PITCH_MAX, float(deg)))
        with self._lock:
            self._target[PITCH_SERVO] = \
                GimbalController._servo_pulse(self.yaw, deg)[PITCH_SERVO]

    def set_pose(self, yaw, pitch):
        self.set_yaw(yaw)
        self.set_pitch(pitch)

    def center(self):
        self.set_pose(0.0, 0.0)

    def set_duration(self, ms):
        self.dur_ms = max(20, min(2000, int(ms)))

    def pulse_of(self, deg, invert=False):
        """±90 角度 → 脉宽（显示用）; pitch 通道实机方向相反, 显示时传 invert=True"""
        a = -self._clamp(deg) if invert else self._clamp(deg)
        return angle_to_pulse(a + 90)

    # ---------------- 后台写线程（软步进）----------------
    def _writer(self):
        """50Hz 软步进: 每拍向目标脉宽逼近 max(1, dur_ms//20) 分之一步;
        每 1s 保醒一次(防 PCA9685 被偶发 NAK/异常打进 SLEEP 自锁)"""
        steps_per_move = max(1, int(self.dur_ms / (TICK_S * 1000)))
        tick = 0
        while self._running:
            slist = []
            with self._lock:
                steps_per_move = max(1, int(self.dur_ms / (TICK_S * 1000)))
                for ch in (YAW_SERVO, PITCH_SERVO):
                    t = self._target[ch]
                    c = self._cur[ch]
                    if abs(t - c) <= _STEP_EPS:
                        if c != t:
                            self._cur[ch] = t
                            slist.append((ch, t))
                        continue
                    step = max(1.0, abs(t - c) / steps_per_move)
                    c_next = c + step if t > c else c - step
                    if (step >= abs(t - c)):
                        c_next = t
                    self._cur[ch] = c_next
                    slist.append((ch, c_next))
            for ch, us in slist:
                self.pca.set_pulse_us(ch, us)
            tick += 1
            if tick % 50 == 0:                  # 每秒一次保醒
                self.pca.ensure_awake()
            time.sleep(TICK_S)

    def close(self):
        self._running = False
        time.sleep(0.05)
        self.pca.close()