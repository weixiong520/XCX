from __future__ import annotations

import sys

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QProgressDialog, QStyle, QSystemTrayIcon

from desktop_py.core.browser_runtime import install_playwright_browsers, playwright_browsers_ready
from desktop_py.ui.main_window import MainWindow
from desktop_py.ui.message_dialog import MessageDialog
from desktop_py.ui.workers import TaskThread


def ensure_browser_runtime(app: QApplication) -> bool:
    if playwright_browsers_ready():
        return True

    progress = QProgressDialog("首次启动，正在安装 Chromium 浏览器资源，请稍候。", "", 0, 0)
    progress.setWindowTitle("初始化浏览器")
    progress.setCancelButton(None)
    progress.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
    progress.setWindowModality(Qt.WindowModality.ApplicationModal)
    progress.setMinimumDuration(0)
    progress.show()
    app.processEvents()

    loop = QEventLoop()
    result: dict[str, object] = {"ok": False, "output": "未获取到安装日志。"}
    thread = TaskThread(lambda log: install_playwright_browsers(log))
    thread.message.connect(
        lambda message: progress.setLabelText(f"首次启动，正在安装 Chromium 浏览器资源，请稍候。\n\n{message}")
    )
    thread.succeeded.connect(lambda payload: result.update({"ok": bool(payload[0]), "output": payload[1]}))
    thread.succeeded.connect(lambda _payload: loop.quit())
    thread.failed.connect(lambda message: result.update({"ok": False, "output": message}))
    thread.failed.connect(lambda _message: loop.quit())
    thread.finished.connect(thread.deleteLater)
    QTimer.singleShot(0, thread.start)
    loop.exec()

    progress.close()
    if bool(result["ok"]):
        return True

    tail = str(result["output"]).strip() or "未获取到安装日志。"
    MessageDialog.show_warning(
        None,
        "浏览器资源安装失败",
        "首次启动需要联网安装 Chromium 浏览器资源，请检查网络后重新打开程序。\n\n最近日志：\n" + tail,
    )
    return False


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("小程序工具")
    app.setQuitOnLastWindowClosed(False)
    if not ensure_browser_runtime(app):
        return 1
    window = MainWindow()
    tray_icon = QSystemTrayIcon(window)
    tray_icon.setIcon(app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
    tray_icon.setToolTip("小程序工具")

    tray_menu = QMenu()
    show_action = QAction("打开窗口", tray_menu)
    show_action.triggered.connect(window.restore_from_tray)
    exit_action = QAction("退出", tray_menu)
    exit_action.triggered.connect(window.request_exit)
    tray_menu.addAction(show_action)
    tray_menu.addSeparator()
    tray_menu.addAction(exit_action)

    tray_icon.setContextMenu(tray_menu)
    tray_icon.activated.connect(
        lambda reason: window.restore_from_tray() if reason == QSystemTrayIcon.ActivationReason.Trigger else None
    )
    tray_icon.show()
    window.tray_icon = tray_icon
    window.show()
    return app.exec()
