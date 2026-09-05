import sys

def main():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        print("❌  pip install cryptography")
        sys.exit(1)
    from config import DB, MONGO_OK, AI_CFG, AI_FEATURES_ENABLED
    if not MONGO_OK:
        print(
            "⚠️   pymongo not found — DB features disabled.  "
            "pip install 'pymongo[srv]'"
        )
    elif DB.connected:
        print(f"✅  MongoDB: {DB.status_msg}")
    else:
        print(f"⚠️   MongoDB: {DB.status_msg}")

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon

    from config import LOGO_SVG
    from main_window import MainWindow
    from network_status import NetworkStatusMonitor

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    if LOGO_SVG.exists():
        app.setWindowIcon(QIcon(str(LOGO_SVG)))
    else:
        print(
            f"ℹ️   No logo found at {LOGO_SVG} — "
            "using default window icon"
        )
    # Create the main application window.
    w = MainWindow()
    # Start network connectivity monitoring.
    # The monitor displays a non-blocking popup whenever
    # the internet connection changes state.
    network_monitor = NetworkStatusMonitor(w)

    w.show()
    # Start the Qt event loop.
    exit_code = app.exec()
    # Stop the network monitor cleanly before exiting.
    network_monitor.stop()
    sys.exit(exit_code)

if __name__ == "__main__":
    main()
