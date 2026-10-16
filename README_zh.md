# 🎮 二自由度舵机云台控制 - 2-Axis Servo Gimbal Control

[English](README.md) | 中文

本项目是一个基于 **Quectel Pi M2** 智能主控板实现的二自由度舵机云台控制示例。PCA9685 舵机驱动板直连 M2 40pin 排针（I2C 总线），驱动云台上的两只 LFD-01 舵机，不依赖扩展板，也不使用 UART 协议。

图形界面提供滑块、步进按钮、快捷键、一键预设与自动演示，左侧 OpenGL 3D 视图与实物同步转动，完整展示 **"UI 角度指令 → PWM 脉宽 → 舵机实际姿态"** 的控制链路。

![界面预览](assets/servo_control.png)

▶ **[观看演示视频](assets/gimbal-demo.mp4)**（mp4，23 MB）

核心功能：
- 拖动 **Yaw** / **Pitch** 滑块即可调整云台指向，读数同时显示当前角度与真正写入 PCA9685 的脉宽。
- 左侧 **OpenGL 3D 视图** 与实物同步转动，整条控制链路在屏幕上即可观察到。
- **一键预设、键盘快捷键与 `▶ Auto Demo`** 可把云台移动到已知姿态，便于展示与验收录像。

## 🎯 功能特点

- **I2C 直驱**：PCA9685（16 通道 / 12bit PWM）挂载于 `/dev/i2c-7`，地址 `0x40`，频率 50 Hz，脉宽 500~2500 µs ↔ 0~180°
- **软件平滑**：PCA9685 本身没有片上缓动，因此由控制器以 50 Hz 把脉宽逐步逼近目标（默认 150 ms 行程）
- **启动校正**：启动即下发"校正后的归中位置"（中位 + TRIM），云台上电即居中
- **3D 同步视图**：写实 OpenGL 模型（舵机壳体、U 型支架、相机模组、影棚地台）以缓动方式跟随虚拟与实物姿态
- **仿真模式**：未安装 `smbus2`，或总线上没有 PCA9685 应答时，界面照常演示，不发送任何 I2C 写
- **链路健壮**：唤醒时强制清除 PCA9685 的 SLEEP 位并每秒保醒一次（修复"`i2cdetect` 能看到 `0x40` 但舵机完全不动"）；持久 I2C 句柄出错后以限速（0.3 s）自动重开
- **退出保持姿态**：退出程序时不清零 PWM，云台保持最后姿态不塌落

## 🖥️ 界面展示

主界面分为两个主要区域：左侧 **3D 视图** 与右侧 **控制面板**。

- 🧊 **3D 视图**：舵机壳体、U 型支架、相机模组与影棚地台，与实物同步转动
- 📊 **连接状态**：芯片应答时为绿色 `● I2C connected: /dev/i2c-7 · 0x40`，否则显示琥珀色 `○ Simulation mode`
- 🎚️ **双轴控制**：偏航 −90° ~ +90°、俯仰 −40° ~ +90° 滑块，读数显示角度 + 脉宽，并提供 `−5 / Center / +5` 步进按钮
- 🎮 **演示动作**：`Left / Up / Right / Down` 预设、`◎ Center Both`、`▶ Auto Demo`，下方为日志窗口

## ⚙️ 工作原理

### 角度 ↔ 脉宽映射

先把 `−90° ~ +90°` 的角度映射到舵机角 `0° ~ 180°`（0° 为中位），再映射到脉宽：

```
舵机角 = 角度 + 90
脉宽   = 500 + 舵机角 / 180 × 2000   (µs)
```

| 轴 | 舵机 | 通道 | 行程 | 说明 |
| --- | --- | --- | --- | --- |
| 偏航 Yaw（水平） | 舵机2 | CH0 | −90° ~ +90° | 0° 为中位 |
| 俯仰 Pitch（垂直） | 舵机1 | CH1 | −40° ~ +90° | 共 130° 行程；+90° 为垂直向上 |

### 软件平滑与启动校正

PCA9685 只保持最后一次写入的值，因此由后台写线程以 50 Hz 把脉宽逐步逼近目标，且仅在数值变化时才写寄存器；控制器启动即下发校正后的归中位置，程序一运行云台就居中。

### SLEEP 自愈与总线容错

`MODE1.SLEEP` 复位后默认为 `1`，此时内部振荡器停振、PWM 完全无输出——即经典的"`i2cdetect` 能看到 `0x40` 但舵机不动"。因此驱动在唤醒时**无条件清除 SLEEP 位**并每秒保醒一次；I2C 句柄持久化，出错后以限速（0.3 s）自动重开，总线被短暂干扰后可自行恢复。

## 📋 系统要求

### 硬件要求

| 配件名称 | 数量 | 规格参数 |
| --- | --- | --- |
| Quectel Pi M2 智能主控板 | 1 块 | 出厂默认搭载 Debian 13 系统镜像，无需烧录 |
| PCA9685 舵机驱动板 | 1 块 | 16 通道 / 12bit PWM / I2C 接口，默认地址 `0x40`，VCC 与 V+ 分离供电 |
| 二维舵机云台（含摄像头） | 1 个 | LFD-01 舵机 ×2（棕/红/橙 = GND/5V/信号），供电范围 4.8~6.0V |
| 双路降压稳压模块 | 1 个 | 固定 5V 输出口 + 自定义可调口；总输出 ≥5A，舵机路电流 ≥2A |
| 18650 电池盒（2S） | 1 个 | 7.4V 输出；亦可用 6~24V 直流电源替代 |
| 显示屏（可选） | 1 个 | HDMI 显示器；通过 SSH 远程开发时可不接 |

![配件实物](assets/accessories.png)

### 软件要求

- 操作系统：Debian 13（Quectel Pi M2 默认系统镜像），Python 3
- 工程内隔离环境 + `requirements.txt` 中的固定依赖：PySide6 6.11.2、pyqtgraph 0.14.0、numpy 2.5.3、PyOpenGL 3.1.10，以及 `smbus2` 0.4.3（可选，缺失时程序进入仿真模式）

## 🔌 硬件连接

![Quectel Pi M2 板载接口](assets/m2_board_ports.png)

1. **逻辑与 I2C（M2 40pin → PCA9685）**：3.3V → **Pin1/VCC**，GND → **Pin9/GND**，SDA → **Pin27/SDA**，SCL → **Pin28/SCL**（即 M2 的 `/dev/i2c-7`；Pin3/5 留给显示屏）。
2. **电源链**：电池盒 → 稳压模块 IN+/IN−；稳压模块**固定 5V 口**经 **Pin2/Pin4** 给主控板回灌供电（替代 Type-C）；**自定义口**（调至 5.0~5.5V，≥2A）接 PCA9685 **V+** 供舵机动力电。
3. **共地**：稳压模块 GND、M2 **Pin9** 与 PCA9685 GND 必须接在同一节点——**不共地则 I2C 失灵**。
4. **舵机**：偏航舵机接 **CH0**，俯仰舵机接 **CH1**，两只舵机电源线并联接入 V+/GND。LFD-01 线序为 **棕 / 红 / 橙 = GND / 5V / 信号**，接反会烧毁舵机。

> **Tips**：VCC（逻辑电，数 mA）与 V+（动力电，≥1A）务必分离供电 · 勿同时接 Type-C 与 40pin 5V 回灌 · 板上 **OE** 引脚必须接 **GND** · 连接完成后用 `i2cdetect -y 7` 验证，显示 `0x40` 即通信正常。

## 🚀 安装与运行

**Quectel Pi M2** 出厂默认搭载 **Debian 13** 系统镜像，无需再次烧录，按如下步骤操作即可。

1. 克隆项目，并在工程内创建隔离环境。

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/Quectel-Pi/demo-servo-gimbal-control.git
cd demo-servo-gimbal-control
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

2. 运行程序，图形界面正常弹出即部署成功。

```bash
python3 run_gimbal.py
```

*run_gimbal.py* 会自动定位工程内的隔离环境（`.venv` 或 `venv`），在 SSH / Wayland 场景下补全 `DISPLAY` 与 Xwayland 授权，随后启动 `src/main.py`。**Servo Control Center · 2-Axis Gimbal** 窗口左侧为 3D 实物视图，右侧为控制面板。

### 配置开机自启动（可选）

先把 `deploy/demo-servo-gimbal-control.desktop` 中的 `Exec` 与 `Path` 改成你的实际工程路径，再安装：

```bash
mkdir -p ~/.config/autostart
cp deploy/demo-servo-gimbal-control.desktop ~/.config/autostart/
```

## 🎛️ 使用说明

1. **启动**：控制器连接 `/dev/i2c-7` 并下发校正后的归中位置。
2. **调整指向**：拖动 Yaw / Pitch 滑块，或使用步进按钮与键盘快捷键。
3. **观察同步**：左侧 3D 视图跟随云台转动，读数同时显示 µs 脉宽。
4. **自动演示**：`▶ Auto Demo` 从当前姿态起扫 3 个正弦周期（偏航 ±50°、俯仰 ±35°），结束后精确回到起始姿态。

| 操控方式 | 控制功能 |
| --- | --- |
| 拖动 Yaw / Pitch 滑块 | 绝对角度控制 |
| `◀ −5 / Center / +5 ▶` | 偏航步进 / 归中 |
| `▼ −5 / Center / +5 ▲` | 俯仰步进 / 归中 |
| 键盘 `A` / `D` | 偏航 ±5° |
| 键盘 `W` / `S` | 俯仰 ±5° |
| 键盘 `Space` / `◎ Center Both` | 双轴归中 |
| `Left / Up / Right / Down` | 一键预设姿态 |
| `▶ Auto Demo` | 自动演示（3 周期扫掠） |

## 📁 项目结构

```
demo-servo-gimbal-control/
├── README.md                            # 英文文档
├── README_zh.md                         # 中文文档（本文件）
├── requirements.txt                     # Python 依赖
├── run_gimbal.py                        # 启动器：定位隔离环境、补全 DISPLAY/XAUTHORITY 后启动程序
├── assets/                              # 截图、实物图与演示视频
├── deploy/
│   └── demo-servo-gimbal-control.desktop  # M2 上开机自启动的 desktop 文件
└── src/                                 # 源代码
    ├── main.py                          # Qt 应用入口
    ├── controller/
    │   └── gimbal_controller.py         # 角度 ↔ 脉宽映射、TRIM 标定、50 Hz 软步进
    ├── driver/
    │   └── pca9685.py                   # PCA9685 I2C 驱动：唤醒、保醒、自动重开、仿真兜底
    ├── ui/
    │   └── main_window.py               # 主窗口、状态栏、键盘快捷键
    └── widgets/
        ├── opengl_servo_view.py         # 写实 OpenGL 3D 云台视图
        └── servo_panel.py               # 控制面板：滑块、按钮、预设、自动演示、日志
```

## 🛠️ 配置参数

| 参数名 | 默认值 | 说明 |
| --- | --- | --- |
| `YAW_SERVO` / `PITCH_SERVO` | `0` / `1` | 各轴使用的 PCA9685 通道（CH0 = 偏航，CH1 = 俯仰） |
| `PITCH_MIN` / `PITCH_MAX` | `-40.0` / `90.0` | 俯仰行程上下限（度），共 130° |
| `YAW_TRIM` / `PITCH_TRIM` | `15.0` / `0.0` | 中位补偿（度，正值 = 向右 / 抬高），为实机标定值 |
| `TICK_S` / `dur_ms` | `0.02` / `150` | 软步进周期（50 Hz）与单次运动行程时间（毫秒） |
| `bus` / `addr` / `freq` | `7` / `0x40` / `50.0` | I2C 总线、PCA9685 地址与 PWM 频率 |

前四项位于 [src/controller/gimbal_controller.py](src/controller/gimbal_controller.py) 顶部，最后一项位于 [src/driver/pca9685.py](src/driver/pca9685.py) 的 `PCA9685` 构造函数。

## ❓ 常见问题

| 现象 | 排查 |
| --- | --- |
| 程序显示 `Simulation mode (no PCA9685 on /dev/i2c-7)` | 确认 V+ 为 5.0~5.5V、`ls /dev/i2c-7` 与 `i2cdetect -y 7` 正常、SDA/SCL 未接反、共地良好，并确认已安装 `smbus2` |
| `i2cdetect` 全空（看不到任何地址） | 检查总线是否存在、SDA/SCL 是否接反，重点查**共地**：断电后用万用表蜂鸣档量 M2 Pin9 与稳压模块 GND 应导通（≈0Ω）；带电时自定义口应稳定读到 5.0~5.5V |
| 舵机有电（卡紧）但完全不动 | 通常是 PCA9685 进入 SLEEP：驱动已在唤醒时清 SLEEP 位并每秒保醒，重启程序即可；若仍不动，检查板上 **OE** 引脚是否接地 |
| 舵机转动时抖动 / 异响 | 在 V+/GND 端并接 1000 µF 电解电容，并确认自定义口输出处于 5.0~5.5V 区间 |
| 舵机只有一侧转动 | 检查对应通道信号线（CH0 = 偏航、CH1 = 俯仰）与该舵机电源线（可用万用表测 V+/GND） |
| 程序启动后云台没有居中 | 调整 [src/controller/gimbal_controller.py](src/controller/gimbal_controller.py) 中的 `YAW_TRIM` / `PITCH_TRIM` 后重启程序 |

## 报告问题

如在使用过程中遇到问题，欢迎在 [移远官方论坛](https://forumschinese.quectel.com/c/quectel-pi/58) 提交技术咨询，我们的技术支持团队将及时为您解答。

欢迎提交 Issue 反馈问题或 Pull Request 贡献代码改进！
