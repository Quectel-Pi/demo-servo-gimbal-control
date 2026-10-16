from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QWidget

from widgets.servo_panel import ServoPanel


class MainWindow(QMainWindow):
    def __init__(self, bus=7, addr=0x40):
        super().__init__()
        self.setWindowTitle("Servo Control Center · 2-Axis Gimbal ")
        self.resize(1460, 920)
        self.bus = bus
        self.addr = addr
        self.init_ui()
        self.statusBar().showMessage(
            "Ready · Keys: A/D yaw ±5° · W/S pitch ±5° · Space center")

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        self.servo_panel = ServoPanel(bus=self.bus, addr=self.addr)
        layout.addWidget(self.servo_panel)

        self.servo_panel.controller.connectedChanged.connect(
            lambda ok, msg: self.statusBar().showMessage(
                ("I2C ● %s · PCA9685" % msg) if ok else msg))

        self.setStyleSheet("QMainWindow{background:#101216;}"
                           "QStatusBar{color:#8a95a3;}")

    def keyPressEvent(self, event):
        panel = self.servo_panel
        k = event.key()
        if k == Qt.Key_A:
            panel.update_yaw(panel.tgt_yaw - 5)
        elif k == Qt.Key_D:
            panel.update_yaw(panel.tgt_yaw + 5)
        elif k == Qt.Key_W:
            panel.update_pitch(panel.tgt_pitch + 5)
        elif k == Qt.Key_S:
            panel.update_pitch(panel.tgt_pitch - 5)
        elif k == Qt.Key_Space:
            panel.set_target(0, 0)
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self.servo_panel.shutdown()
        super().closeEvent(event)