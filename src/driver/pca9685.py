#!/usr/bin/env python3
"""PCA9685 舵机驱动板 I2C 驱动（16 通道 / 12bit PWM）

总线   : M2 40pin **I2C7**(Pin27=SDA, Pin28=SCL), /dev/i2c-7
            (I2C3/Pin3-5 留给显示屏; 原理图 J1901 确认 Pin27=I2C7_SDA_M1, Pin28=I2C7_SCL_M1)
地址   : 0x40（默认; 可用板载 A0~A5 跳线改址, 详见模块丝印/说明）
频率   : 50Hz（LFD-01 舵机工作频率）, 脉宽 500~2500µs ↔ 舵机角 0~180°
供电   : 稳压模块双路输出 —— 固定 5V 口 → M2 40pin Pin2/Pin4 回灌供电;
           自定义口(调 5.0~5.5V) → PCA9685 V+(舵机动力);
           VCC(逻辑电) ← M2 Pin1 3.3V; GND 三者共地必需(否则 I2C 失灵)
输出   : CH0..CH15; 每通道 4 个寄存器(ON_L/H, OFF_L/H), 基址 0x06
行为   : 持久总线 + 出错限速自动重开; 只在脉宽变化时写寄存器
仿真   : 无 smbus2 或总线打不开 → 自动进入仿真模式（记录脉宽, 不驱动舵机）

注意   : MODE1 的 bit4=SLEEP 复位后默认为 1, 此时振荡器停振、PWM 无输出
        (现象: i2cdetect 能看到 0x40 但舵机不动)。唤醒写必须【无条件清
        SLEEP 位】, 且运行中需周期保醒, 详见 _init_chip / ensure_awake。
"""

import threading
import time

try:
    from smbus2 import SMBus
    _HAS_SMBUS = True
except ImportError:            # PC 端通常未安装 smbus2 → 仿真
    _HAS_SMBUS = False

REG_MODE1 = 0x00
REG_MODE2 = 0x01
REG_PWM0 = 0x06                # CH0 ON_L 起, 每通道 4B: ON_L ON_H OFF_L OFF_H
REG_PRESCALE = 0xFE

MODE1_SLEEP = 0x10
MODE1_RESTART = 0x80
MODE1_AI = 0x20                # 寄存器自动递增

OSC_HZ = 25_000_000
STEPS = 4096


class PCA9685:
    """PCA9685 舵机驱动板（sim=True 时不发任何 I2C 写）"""

    def __init__(self, bus=7, addr=0x40, freq=50.0):
        self.bus_no = bus
        self.addr = addr
        self.freq = float(freq)
        self.lock = threading.RLock()   # _reopen/_init_chip 会重入
        self._last_reopen = 0.0         # 限速重开时间戳
        self._bus = None
        self.sim = not _HAS_SMBUS
        self._pulses = {}              # ch -> µs（仿真/回读用）
        if _HAS_SMBUS:
            try:
                self._bus = SMBus(bus)
                self._init_chip()
            except Exception:
                self._teardown_bus()
                self.sim = True

    # ---------------- 状态 ----------------
    @property
    def connected(self) -> bool:
        """I2C 总线是否打开（总线在不代表芯片在位; 芯片缺失启用仿真由
        _init_chip 抛异常决定）"""
        return self._bus is not None

    # ---------------- 底层 I2C ----------------
    def _read_reg(self, reg, n=1):
        with self.lock:
            data = self._bus.read_i2c_block_data(self.addr, reg, n)
        return bytes(data)

    def _write_regs(self, reg, data):
        with self.lock:
            self._bus.write_i2c_block_data(self.addr, reg, list(data))

    def _teardown_bus(self):
        try:
            self._bus.close()
        except Exception:
            pass
        self._bus = None

    def _init_chip(self):
        """初始化: 读回 MODE1 → 睡眠改分频 → 强制唤醒(+自动递增)

        设计要点: 唤醒写必须【无条件清除 bit4(SLEEP)】。若用 (old&0x7F)|AI
        这种"读回值按位或"的写法, 0x7F 只清 RESTART, 一旦芯片已处于休眠态
        (读回值带 0x10), 唤醒写会把 SLEEP 原样写回, 造成 0x31 睡死自锁
        (总线偶发 NAK 时更易触发)。故唤醒字取 (old&0x7F)|AI 后再 &~SLEEP。
        """
        if self._bus is None:
            raise OSError("bus closed")
        prescale = max(3, min(255, int(round(
            OSC_HZ / (STEPS * self.freq))) - 1))
        old = self._read_reg(REG_MODE1, 1)[0]
        self._write_regs(REG_MODE1, [(old & 0x7F) | MODE1_SLEEP])
        self._write_regs(REG_PRESCALE, [prescale])
        # 唤醒: 清 SLEEP(0x10) 与 RESTART(0x80), 置 AI —— 不沿用 old 任何睡眠位
        wake = ((old & 0x7F) | MODE1_AI) & ~MODE1_SLEEP
        self._write_regs(REG_MODE1, [wake])
        time.sleep(0.005)
        # 防御: 若仍处 SLEEP 再补写(最多 3 次)
        for _ in range(3):
            try:
                if not (self._read_reg(REG_MODE1, 1)[0] & MODE1_SLEEP):
                    break
            except Exception:
                pass
            self._write_regs(REG_MODE1, [wake])
            time.sleep(0.005)
        # MODE2 保持默认 0x04(推挽输出), 使能 OUTDRV
        self._pulses.clear()

    def ensure_awake(self):
        """保醒自愈(幂等): 任何时刻被置位 SLEEP 都无条件重新唤醒;
        总线失效也限速尝试重开。由控制器周期调用。"""
        if self._bus is None and not self._try_reopen():
            return
        try:
            if self._read_reg(REG_MODE1, 1)[0] & MODE1_SLEEP:
                wake = (0x01 | MODE1_AI) & ~MODE1_SLEEP   # 0x21, 保留 ALLCALL
                self._write_regs(REG_MODE1, [wake])
        except Exception:
            self._try_reopen()

    # ---------------- 对外接口 ----------------
    def set_pulse_us(self, ch, us, on=0):
        """设置通道脉宽(µs)。0 = 全关(无 PWM), 500~2500 对应舵机 0~180°。
        返回是否真的写入 I2C（仿真返回 False）; 总线失效时限速自愈重试"""
        us = max(0.0, min(50000.0, float(us)))
        self._pulses[int(ch)] = us
        if self._bus is None and not self._try_reopen():
            return False
        off = min(4095, int(round(us * STEPS * self.freq / 1.0e6)))
        base = REG_PWM0 + 4 * int(ch)
        data = [on & 0xFF, (on >> 8) & 0xFF, off & 0xFF, (off >> 8) & 0xFF]
        for _ in range(2):
            try:
                self._write_regs(base, data)
                return True
            except Exception:
                if not self._try_reopen():
                    return False
        return False

    def pulse_us(self, ch) -> float:
        """最近一次下发的脉宽(µs)"""
        return self._pulses.get(int(ch), 0.0)

    def set_off(self, ch):
        """通道置 0（无 PWM, 舵机信号保持低电平, 舵机掉力）"""
        return self.set_pulse_us(ch, 0.0)

    def _try_reopen(self):
        """限速重开总线并重新初始化(距上次尝试>=0.3s): 返回是否重新可用。

        设计要点: 重开失败不能把 _bus 永久置 None —— 否则总线一次偶发 NAK
        就再也无法自愈, 表现为"舵机忽然再也驱动不了"。故每次调用都限速
        重试, 只要有电且在位就能自行恢复。"""
        now = time.monotonic()
        if now - self._last_reopen < 0.3:
            return self._bus is not None
        self._last_reopen = now
        with self.lock:
            self._teardown_bus()
            try:
                self._bus = SMBus(self.bus_no)
                self._init_chip()
            except Exception:
                self._bus = None
        return self._bus is not None

    def close(self):
        """关闭总线, 但【不】清零 PWM: PCA9685 掉电/断线前保持最后脉宽,
        云台保持当前姿态不塌落（退出程序后仍将维持）。"""
        with self.lock:
            self._teardown_bus()