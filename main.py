import sys

def main():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        print("❌  pip install cryptography"); sys.exit(1)

    from config import DB, MONGO_OK, AI_CFG, AI_FEATURES_ENABLED
    if not MONGO_OK:
        print("⚠️   pymongo not found — DB features disabled.  pip install 'pymongo[srv]'")
    elif DB.connected:
        print(f"✅  MongoDB: {DB.status_msg}")
    else:
        print(f"⚠️   MongoDB: {DB.status_msg}")


    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui     import QIcon
    from config import LOGO_SVG
    from main_window import MainWindow

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    if LOGO_SVG.exists():
        app.setWindowIcon(QIcon(str(LOGO_SVG)))
    else:
        print(f"ℹ️   No logo found at {LOGO_SVG} — using default window icon")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
