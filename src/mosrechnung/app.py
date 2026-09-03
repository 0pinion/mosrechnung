from __future__ import annotations

import sys

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError:  # Ubuntu 22.04/24.04
    from PySide2.QtWidgets import QApplication, QMessageBox

from .db import Repository
from .paths import database_path
from .ui import MainWindow, configure_application


def main() -> int:
    application = QApplication(sys.argv)
    configure_application(application)
    try:
        repository = Repository(database_path())
        window = MainWindow(repository)
        window.show()
        return application.exec() if hasattr(application, "exec") else application.exec_()
    except Exception as exc:
        QMessageBox.critical(None, "Mosrechnung konnte nicht gestartet werden", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
