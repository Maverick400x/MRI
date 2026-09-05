import urllib.request

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal, Qt
from PyQt6.QtWidgets import QLabel



class NetworkWorker(QObject):
    status_changed = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        self._running = True
        self._last_status = None

    def check(self):
        if not self._running:
            return

        connected = False

        try:
            request = urllib.request.Request(
                "https://www.google.com/generate_204",
                method="HEAD",
            )

            with urllib.request.urlopen(request, timeout=2):
                connected = True

        except Exception:
            connected = False

        # Only report when the state changes.
        if connected != self._last_status:
            self._last_status = connected
            self.status_changed.emit(connected)

    def stop(self):
        self._running = False


class NetworkStatusToast(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(42)
        self.setMaximumHeight(42)

        self.hide()

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_status(self, connected):
        if connected:
            self.setText("✓  Network Connected")
            self.setStyleSheet("""
                QLabel {
                    background: #16a34a;
                    color: white;
                    border-radius: 10px;
                    padding: 10px 22px;
                    font-size: 14px;
                    font-weight: 600;
                }
            """)
        else:
            self.setText("✕  Network Disconnected")
            self.setStyleSheet("""
                QLabel {
                    background: #dc2626;
                    color: white;
                    border-radius: 10px;
                    padding: 10px 22px;
                    font-size: 14px;
                    font-weight: 600;
                }
            """)

        self.adjustSize()
        self._position()
        self.show()
        self.raise_()

        self._hide_timer.start(2500)

    def _position(self):
        if not self.parent():
            return

        parent = self.parent()
        x = (parent.width() - self.width()) // 2
        y = parent.height() - self.height() - 30

        self.move(max(10, x), max(10, y))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position()


class NetworkStatusMonitor(QObject):
    def __init__(self, parent_window):
        super().__init__(parent_window)

        self.window = parent_window
        self.toast = NetworkStatusToast(parent_window)

        self.thread = QThread()
        self.worker = NetworkWorker()

        self.worker.moveToThread(self.thread)
        self.worker.status_changed.connect(self.toast.show_status)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._check)

        self.thread.started.connect(self._check)

        self.thread.start()

        # Check every 5 seconds.
        self.timer.start(5000)

    def _check(self):
        if self.thread.isRunning():
            QTimer.singleShot(0, self.worker.check)

    def stop(self):
        self.timer.stop()
        self.worker.stop()

        if self.thread.isRunning():
            self.thread.quit()
            self.thread.wait()