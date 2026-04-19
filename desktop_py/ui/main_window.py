from __future__ import annotations

from datetime import datetime
import os

from PySide6.QtCore import QEvent, QItemSelectionModel, QTimer, Signal, Qt
from PySide6.QtGui import QColor, QCloseEvent, QGuiApplication, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QStyledItemDelegate,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from desktop_py.core.fetcher import (
    fetch_account,
    fetch_accounts_batch,
    fetch_switchable_accounts,
    keep_alive_account_state,
    save_login_state,
    save_login_state_with_profile,
    validate_account_state,
)
from desktop_py.core.models import AccountConfig, AppSettings, FetchResult
from desktop_py.core.notifier import build_summary, send_feishu_text
from desktop_py.core.store import (
    account_state_path,
    default_state_path,
    ensure_runtime_dirs,
    load_accounts,
    load_settings,
    save_accounts,
    save_settings,
    validate_shared_browser_profile_dir,
)
from desktop_py.ui.account_presenter import (
    apply_batch_fetch_results,
    apply_fetch_result,
    deadline_tooltip_text,
    display_account_name,
    display_deadline_text,
    display_result_text,
    is_no_business_page_note,
    next_auto_fetch_push_interval_ms,
    parse_deadline_for_sort,
    sort_accounts_for_display,
)
from desktop_py.ui.account_dialog import AccountDialog
from desktop_py.ui.message_dialog import MessageDialog
from desktop_py.ui.task_runner import WindowTaskRunner
from desktop_py.ui.workers import TaskThread


BLOCKED_ACCOUNT_NAMES = {
    "山每北荒修僊1",
    "山每北荒修僊2",
    "山每北荒修僊4",
    "叨空SSR",
}

KEEP_ALIVE_INTERVAL_MS = 5 * 60 * 60 * 1000
ACTUAL_ACCOUNT_PREFIX = "当前实际账号："


class HoverTableWidget(QTableWidget):
    hovered_row_changed = Signal(int)

    def __init__(self, rows: int, columns: int, parent: QWidget | None = None) -> None:
        super().__init__(rows, columns, parent)
        self._hovered_row = -1
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    def mouseMoveEvent(self, event) -> None:
        row = self.rowAt(event.position().toPoint().y())
        if row != self._hovered_row:
            self._hovered_row = row
            self.hovered_row_changed.emit(row)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hovered_row != -1:
            self._hovered_row = -1
            self.hovered_row_changed.emit(-1)
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.SelectAll):
            event.accept()
            return
        super().keyPressEvent(event)

    @property
    def hovered_row(self) -> int:
        return self._hovered_row


class RowHighlightDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index) -> None:
        table = self.parent()
        row = index.row()
        selected_rows = {item.row() for item in table.selectionModel().selectedRows()} if table.selectionModel() else set()

        default_bg = QColor("#ffffff")
        alt_bg = QColor("#f7fafe")
        hover_bg = QColor("#eef5ff")
        selected_bg = QColor("#d7e9ff")
        text_color = QColor("#132238")

        if row in selected_rows:
            bg = selected_bg
        elif getattr(table, "hovered_row", -1) == row:
            bg = hover_bg
        else:
            bg = alt_bg if row % 2 else default_bg

        painter.save()
        painter.fillRect(option.rect, bg)

        draw_option = option
        draw_option.state &= ~QStyle.StateFlag.State_Selected
        draw_option.state &= ~QStyle.StateFlag.State_MouseOver
        draw_option.state &= ~QStyle.StateFlag.State_HasFocus
        draw_option.palette.setColor(draw_option.palette.ColorRole.Text, text_color)
        draw_option.palette.setColor(draw_option.palette.ColorRole.HighlightedText, text_color)

        super().paint(painter, draw_option, index)
        painter.restore()


class ToggleActionButton(QPushButton):
    def paintEvent(self, event) -> None:
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        track_width = 34
        track_height = 18
        knob_size = 14
        track_x = self.width() - 12 - track_width
        track_y = (self.height() - track_height) // 2
        knob_y = (self.height() - knob_size) // 2
        knob_x = track_x + (track_width - knob_size - 2 if self.isChecked() else 2)

        track_color = QColor(255, 255, 255, 72 if self.isChecked() else 90)
        knob_color = QColor("#ffffff")

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track_x, track_y, track_width, track_height, 9, 9)

        painter.setBrush(knob_color)
        painter.setPen(QPen(QColor(19, 34, 56, 24), 1))
        painter.drawEllipse(knob_x, knob_y, knob_size, knob_size)
        painter.end()


class MainWindow(QMainWindow):
    # 当前工作台以双栏信息密度为优先，固定窗口尺寸是有意设计；
    # 若未来要支持小屏自适应，需要连同卡片排布与滚动策略一起重构。
    CLIENT_WIDTH = 1376
    CLIENT_HEIGHT = 956

    def __init__(self) -> None:
        super().__init__()
        ensure_runtime_dirs()
        self.accounts = load_accounts()
        self.settings = load_settings()
        self._reset_current_main_account_name()
        self._threads: list[TaskThread] = []
        self._task_runner = WindowTaskRunner(
            parent=self,
            threads=self._threads,
            append_log=self.append_log,
            update_action_buttons=self._update_action_buttons,
            set_status_text=self._set_status_text,
            status_message=lambda message, timeout: self.statusBar().showMessage(message, timeout),
        )
        self._summary_labels: dict[str, QLabel] = {}
        self._status_label: QLabel | None = None
        self.login_button: QPushButton | None = None
        self.edit_button: QPushButton | None = None
        self.import_button: QPushButton | None = None
        self.validate_button: QPushButton | None = None
        self.fetch_selected_button: QPushButton | None = None
        self.send_summary_button: QPushButton | None = None
        self.stop_fetch_button: QPushButton | None = None
        self.delete_button: QPushButton | None = None
        self.browse_profile_button: QPushButton | None = None
        self.auto_fetch_push_switch: QPushButton | None = None
        self.tray_icon: QSystemTrayIcon | None = None
        self._allow_close = False
        self._auto_fetch_timer = QTimer(self)
        self._auto_fetch_timer.setSingleShot(True)
        self._auto_fetch_timer.timeout.connect(self._handle_auto_fetch_push_timeout)
        self._keep_alive_timer = QTimer(self)
        self._keep_alive_timer.setSingleShot(True)
        self._keep_alive_timer.timeout.connect(self._handle_keep_alive_timeout)

        self.setWindowTitle("小程序工具")
        self.setWindowFlag(Qt.WindowType.WindowTitleHint, True)
        self.setWindowFlag(Qt.WindowType.WindowSystemMenuHint, True)
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, False)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)
        self.setFixedSize(self.CLIENT_WIDTH, self.CLIENT_HEIGHT)
        self._build_ui()
        self._apply_styles()
        self.refresh_table()
        self._center_on_screen()
        QTimer.singleShot(0, self._auto_validate_entry_account)
        QTimer.singleShot(0, self._apply_auto_fetch_push_schedule)
        QTimer.singleShot(0, self._apply_keep_alive_schedule)

    def _center_on_screen(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        frame = self.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        self.move(frame.topLeft())

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close or self.tray_icon is None or not self.tray_icon.isVisible():
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()

    def restore_from_tray(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def request_exit(self) -> None:
        self._allow_close = True
        if self.tray_icon is not None:
            self.tray_icon.hide()
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _build_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        root.addLayout(self._build_summary_strip())

        self.table = HoverTableWidget(0, 5)
        self.table.setObjectName("accountTable")
        self.table.setHorizontalHeaderLabels(["账号", "最近截止时间", "最近状态", "结果", "启用"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(False)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.verticalHeader().setVisible(False)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.setMinimumHeight(360)
        self.table.setItemDelegate(RowHighlightDelegate(self.table))
        header = self.table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setDefaultSectionSize(96)
        header.setMinimumSectionSize(52)
        header.setFixedHeight(42)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.resizeSection(0, 182)
        header.resizeSection(1, 178)
        header.resizeSection(2, 108)
        header.resizeSection(3, 74)
        self.table.hovered_row_changed.connect(lambda _row: self.table.viewport().update())
        self.table.itemSelectionChanged.connect(self._handle_selection_changed)

        self.log_edit = QPlainTextEdit()
        self.log_edit.setObjectName("logPanel")
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText("这里会实时显示登录、校验、抓取和汇总发送日志。")
        self.log_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.log_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.log_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.log_edit.setMinimumHeight(170)

        body_layout = QGridLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setHorizontalSpacing(14)
        body_layout.setVerticalSpacing(14)

        settings_panel = self._build_settings_box()
        actions_panel = self._build_actions_card()
        account_panel = self._wrap_card("账号概览", "集中查看账号状态、截止时间与最近抓取结果。", self.table)
        log_panel = self._wrap_card("运行日志", "保留后台任务回传信息，便于排查失败原因。", self.log_edit)

        settings_panel.setMinimumHeight(210)
        actions_panel.setMinimumHeight(210)
        account_panel.setMinimumHeight(510)
        log_panel.setMinimumHeight(510)

        body_layout.addWidget(settings_panel, 0, 0)
        body_layout.addWidget(actions_panel, 0, 1)
        body_layout.addWidget(account_panel, 1, 0)
        body_layout.addWidget(log_panel, 1, 1)
        body_layout.setColumnStretch(0, 1)
        body_layout.setColumnStretch(1, 1)
        body_layout.setRowStretch(0, 0)
        body_layout.setRowStretch(1, 1)
        root.addLayout(body_layout, stretch=1)

        self._status_label = QLabel("当前状态：就绪")
        self.statusBar().setFixedHeight(30)
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addPermanentWidget(self._status_label, 1)
        self.statusBar().showMessage("就绪")

    def _build_summary_strip(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(12)
        cards = [
            ("total", "账号总数", "0"),
            ("enabled", "启用账号", "0"),
            ("healthy", "状态正常", "0"),
            ("recent", "最近抓取", "暂无"),
        ]
        for key, title, value in cards:
            layout.addWidget(self._build_metric_card(key, title, value))
        return layout

    def _build_metric_card(self, key: str, title: str, value: str) -> QWidget:
        frame = QFrame()
        frame.setObjectName("metricCard")
        frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("metricTitle")
        value_label = QLabel(value)
        value_label.setObjectName("metricValue")

        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addStretch(1)
        self._summary_labels[key] = value_label
        return frame

    def _build_settings_box(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("settingsBox")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        wrapper = QVBoxLayout(frame)
        wrapper.setContentsMargins(16, 14, 16, 14)
        wrapper.setSpacing(8)

        title = QLabel("全局设置")
        title.setObjectName("sectionTitle")
        subtitle = QLabel("统一维护通知、共享浏览器资料目录。")
        subtitle.setObjectName("sectionSubtitle")
        subtitle.setWordWrap(True)

        wrapper.addWidget(title)
        wrapper.addWidget(subtitle)

        form = QWidget()
        layout = QGridLayout(form)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(12)
        self.webhook_edit = QLineEdit(self.settings.feishu_webhook)
        self.profile_dir_edit = QLineEdit(self.settings.browser_profile_dir)
        self.webhook_edit.setPlaceholderText("填写飞书机器人 Webhook，用于汇总推送")
        self.profile_dir_edit.setPlaceholderText("可选，复用共享浏览器资料目录")

        layout.addWidget(QLabel("飞书 Webhook"), 0, 0)
        layout.addWidget(self.webhook_edit, 0, 1, 1, 3)
        layout.addWidget(QLabel("共享浏览器资料目录"), 1, 0)
        layout.addWidget(self.profile_dir_edit, 1, 1, 1, 3)
        browse_button = QPushButton("选择目录")
        self.browse_profile_button = browse_button
        self.browse_profile_button.setEnabled(False)
        self.browse_profile_button.setProperty("role", "primary")
        self.browse_profile_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        browse_button.clicked.connect(self.choose_profile_dir)
        layout.addWidget(browse_button, 2, 2)
        self.profile_dir_edit.installEventFilter(self)
        self.browse_profile_button.installEventFilter(self)

        save_button = QPushButton("保存设置")
        save_button.setProperty("role", "primary")
        save_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        save_button.clicked.connect(self.save_current_settings)
        layout.addWidget(save_button, 2, 3)
        layout.setColumnStretch(1, 1)
        wrapper.addWidget(form)
        return frame

    def eventFilter(self, watched, event):
        if watched in {self.profile_dir_edit, self.browse_profile_button} and event.type() in {QEvent.Type.FocusIn, QEvent.Type.FocusOut}:
            QTimer.singleShot(0, self._sync_browse_profile_button_state)
        return super().eventFilter(watched, event)

    def _set_browse_profile_button_enabled(self, enabled: bool) -> None:
        if self.browse_profile_button is not None:
            self.browse_profile_button.setEnabled(enabled)

    def _sync_browse_profile_button_state(self) -> None:
        focus_widget = self.focusWidget()
        enabled = focus_widget in {self.profile_dir_edit, self.browse_profile_button}
        self._set_browse_profile_button_enabled(enabled)

    def _build_actions_card(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("actionsCard")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        wrapper = QVBoxLayout(frame)
        wrapper.setContentsMargins(16, 14, 16, 14)
        wrapper.setSpacing(8)

        title = QLabel("快捷操作")
        title.setObjectName("sectionTitle")
        subtitle = QLabel("按常用流程组织动作，先维护账号，再保存或校验登录态，最后执行抓取或发送汇总。")
        subtitle.setObjectName("sectionSubtitle")
        subtitle.setWordWrap(True)

        wrapper.addWidget(title)
        wrapper.addWidget(subtitle)
        wrapper.addLayout(self._build_actions())
        return frame

    def _build_actions(self) -> QGridLayout:
        layout = QGridLayout()
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(12)
        actions = [
            ("新增账号", self.add_account, 0, 0),
            ("编辑账号", self.edit_account, 0, 1),
            ("全选账号", self.select_imported_accounts, 0, 2),
            ("删除账号", self.delete_account, 0, 3),
            ("导入账号", self.import_accounts, 1, 0),
            ("保存登录", self.login_selected, 1, 1),
            ("检测登录", self.validate_selected, 1, 2),
            ("停止抓取", self.stop_fetching, 1, 3),
            ("抓取并推送", self.auto_fetch_and_send, 2, 2),
            ("抓取选中", self.fetch_selected, 2, 0),
            ("发送飞书", self.send_summary, 2, 1),
        ]
        for text, handler, row, col in actions:
            button = QPushButton(text)
            if text == "保存登录":
                self.login_button = button
            if text == "编辑账号":
                self.edit_button = button
            if text == "删除账号":
                self.delete_button = button
                button.setProperty("role", "danger")
            if text == "停止抓取":
                self.stop_fetch_button = button
                button.setProperty("role", "danger")
            if text == "导入账号":
                self.import_button = button
            if text == "检测登录":
                self.validate_button = button
            if text == "抓取选中":
                self.fetch_selected_button = button
            if text == "发送飞书":
                self.send_summary_button = button
                button.setProperty("role", "success")
            if text == "抓取并推送":
                button.setProperty("role", "success")
            elif text not in {"删除账号", "停止抓取"}:
                button.setProperty("role", "primary")
            button.setMinimumWidth(0)
            button.clicked.connect(handler)
            layout.addWidget(button, row, col)
        layout.addWidget(self._build_auto_fetch_push_switch(), 2, 3)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 1)
        layout.setColumnStretch(3, 1)
        self._update_action_buttons()
        return layout

    def _build_auto_fetch_push_switch(self) -> QWidget:
        switch = ToggleActionButton("自动抓取并推送")
        switch.setObjectName("autoFetchPushSwitch")
        switch.setProperty("role", "success")
        switch.setCheckable(True)
        switch.setChecked(self.settings.auto_fetch_push_enabled)
        switch.toggled.connect(self._handle_auto_fetch_push_toggled)
        self.auto_fetch_push_switch = switch
        return switch

    def _wrap_card(self, title: str, subtitle: str, content: QWidget) -> QWidget:
        frame = QFrame()
        frame.setObjectName("panelCard")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title_label = QLabel(title)
        title_label.setObjectName("sectionTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("sectionSubtitle")
        subtitle_label.setWordWrap(True)

        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        layout.addWidget(content, stretch=1)
        return frame

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget#centralWidget {
                background: #eef3f8;
                color: #132238;
                font-size: 13px;
            }
            QFrame#metricCard, QFrame#actionsCard, QFrame#panelCard, QFrame#settingsBox {
                background: #ffffff;
                border: 1px solid #d8e1ec;
                border-radius: 0px;
            }
            QFrame#metricCard:hover, QFrame#actionsCard:hover, QFrame#panelCard:hover, QFrame#settingsBox:hover {
                border-color: #bfd5ee;
            }
            QLabel#metricTitle {
                color: #708299;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#metricValue {
                color: #16324f;
                font-size: 24px;
                font-weight: 800;
            }
            QLabel#sectionTitle {
                color: #16324f;
                font-weight: 700;
            }
            QLabel#sectionTitle {
                font-size: 16px;
            }
            QLabel#sectionSubtitle {
                color: #6e8196;
                line-height: 1.5;
            }
            QLineEdit {
                min-height: 38px;
                padding: 0 12px;
                border: 1px solid #c8d3df;
                border-radius: 0px;
                background: #f9fbfd;
                color: #132238;
            }
            QLineEdit:focus {
                border: 1px solid #2f80ed;
                background: #ffffff;
            }
            QPushButton {
                min-height: 38px;
                padding: 0 14px;
                border-radius: 0px;
                border: 1px solid #d0dae5;
                background: #ffffff;
                color: #24384d;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #f4f8fc;
                border-color: #b8cadf;
            }
            QPushButton[role="primary"] {
                background: #2f80ed;
                border-color: #2f80ed;
                color: #ffffff;
            }
            QPushButton[role="primary"]:hover {
                background: #1d6fd9;
                border-color: #1d6fd9;
            }
            QPushButton[role="danger"] {
                background: #e74c3c;
                border-color: #e74c3c;
                color: #ffffff;
            }
            QPushButton[role="danger"]:hover {
                background: #d93a2a;
                border-color: #d93a2a;
            }
            QPushButton[role="success"] {
                background: #27ae60;
                border-color: #27ae60;
                color: #ffffff;
            }
            QPushButton[role="success"]:hover {
                background: #1f9a54;
                border-color: #1f9a54;
            }
            QPushButton#autoFetchPushSwitch:checked {
                background: #1f9a54;
                border-color: #1f9a54;
                color: #ffffff;
            }
            QPushButton#autoFetchPushSwitch {
                text-align: left;
                padding: 0 58px 0 14px;
            }
            QTableWidget#accountTable {
                border: 1px solid #e0e7ef;
                border-radius: 0px;
                background: #ffffff;
                alternate-background-color: #f7fafe;
                gridline-color: #edf2f7;
            }
            QTableWidget#accountTable::item {
                padding: 6px 4px;
                border: none;
            }
            QHeaderView::section {
                background: #f3f7fb;
                color: #607086;
                padding: 0 10px;
                border: none;
                border-bottom: 1px solid #e0e7ef;
                font-weight: 700;
                text-align: center;
            }
            QPlainTextEdit#logPanel {
                border: 1px solid #e0e7ef;
                border-radius: 0px;
                background: #0f1b2a;
                color: #d8e4f0;
                padding: 10px;
                selection-background-color: #2f80ed;
            }
            QScrollBar:vertical {
                background: #e7edf4;
                width: 12px;
                margin: 6px 2px 6px 2px;
                border-radius: 0px;
            }
            QScrollBar::handle:vertical {
                background: #b5c6d8;
                min-height: 36px;
                border-radius: 0px;
            }
            QScrollBar::handle:vertical:hover {
                background: #8fa8c2;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QStatusBar {
                background: #ffffff;
                color: #5e6f83;
                border-top: 1px solid #d8e1ec;
            }
            """
        )

    def append_log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_edit.appendPlainText(f"[{timestamp}] {message}")
        self._set_status_text(message)

    def refresh_table(self) -> None:
        selected_account_name = self.selected_account().name if self.selected_account() else ""
        self._sort_accounts_for_display()
        self.table.setRowCount(len(self.accounts))
        for row, account in enumerate(self.accounts):
            values = [
                self._display_account_name(account),
                self._display_deadline_text(account),
                account.last_status,
                self._display_result_text(account),
                "是" if account.enabled else "否",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() ^ Qt.ItemIsEditable)
                if col == 0 and account.is_entry_account:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                else:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col in {0, 1, 3} and value:
                    item.setToolTip(self._deadline_tooltip_text(account) if col == 1 else value)
                self.table.setItem(row, col, item)
        target_row = -1
        if selected_account_name:
            for row, account in enumerate(self.accounts):
                if account.name == selected_account_name:
                    target_row = row
                    break
        if target_row < 0:
            for row, account in enumerate(self.accounts):
                if account.is_entry_account:
                    target_row = row
                    break
        if target_row < 0 and self.accounts:
            target_row = 0
        if target_row >= 0:
            self.table.selectRow(target_row)
        else:
            self.table.clearSelection()
        self.table.viewport().update()
        self._refresh_summary_cards()
        self._update_action_buttons()

    def _sort_accounts_for_display(self) -> None:
        self.accounts = sort_accounts_for_display(self.accounts)

    def _parse_deadline_for_sort(self, deadline_text: str) -> datetime | None:
        return parse_deadline_for_sort(deadline_text)

    def _display_deadline_text(self, account: AccountConfig) -> str:
        return display_deadline_text(account)

    def _deadline_tooltip_text(self, account: AccountConfig) -> str:
        return deadline_tooltip_text(account)

    def _is_no_business_page_note(self, note: str) -> bool:
        return is_no_business_page_note(note)

    def _display_result_text(self, account: AccountConfig) -> str:
        return display_result_text(account)

    def _show_info(self, title: str, text: str) -> None:
        MessageDialog.show_info(self, title, text)

    def _show_warning(self, title: str, text: str) -> None:
        MessageDialog.show_warning(self, title, text)

    def _auto_validate_entry_account(self) -> None:
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return
        account = self._entry_account()
        if account is None:
            return
        account.last_status = "检测中"
        account.last_note = ""
        self.refresh_table()
        self._run_thread(
            lambda _log: self._safe_validate_account_state(account),
            on_success=lambda ok: self._mark_validation(account, bool(ok)),
            emit_log=False,
            emit_failure_log=False,
            update_status=False,
        )

    def _safe_validate_account_state(self, account: AccountConfig) -> bool:
        try:
            return bool(validate_account_state(account, None, self.settings.browser_profile_dir))
        except Exception:
            return False

    def _entry_account(self) -> AccountConfig | None:
        return next((item for item in self.accounts if item.is_entry_account), None)

    def _account_for_keep_alive(self, candidates: list[AccountConfig] | None = None) -> AccountConfig | None:
        entry_account = self._entry_account()
        if entry_account is not None:
            return entry_account
        if candidates:
            return candidates[0]
        return None

    def selected_index(self) -> int:
        selected = self.table.selectionModel().selectedRows()
        return selected[0].row() if selected else -1

    def selected_indexes(self) -> list[int]:
        selected = self.table.selectionModel().selectedRows()
        return sorted(item.row() for item in selected)

    def selected_account(self) -> AccountConfig | None:
        index = self.selected_index()
        return self.accounts[index] if 0 <= index < len(self.accounts) else None

    def _handle_selection_changed(self) -> None:
        self.table.viewport().update()
        self._update_action_buttons()

    def _update_action_buttons(self) -> None:
        selected_indexes = self.selected_indexes()
        single_selected = len(selected_indexes) == 1
        account = self.accounts[selected_indexes[0]] if single_selected else None
        if self.login_button is not None:
            self.login_button.setEnabled(bool(account and account.is_entry_account))
        if self.edit_button is not None:
            self.edit_button.setEnabled(bool(account and account.is_entry_account))
        if self.import_button is not None:
            self.import_button.setEnabled(bool(account and account.is_entry_account))
        if self.validate_button is not None:
            self.validate_button.setEnabled(bool(account and account.is_entry_account))
        if self.fetch_selected_button is not None:
            self.fetch_selected_button.setEnabled(bool(account and not account.is_entry_account))
        if self.delete_button is not None:
            self.delete_button.setEnabled(bool(selected_indexes))
        if self.stop_fetch_button is not None:
            self.stop_fetch_button.setEnabled(bool(self._threads))

    def stop_fetching(self) -> None:
        if not self._threads:
            self._show_info("提示", "当前没有正在执行的抓取或推送任务。")
            return
        running_threads = list(self._threads)
        for thread in running_threads:
            try:
                thread.requestInterruption()
                thread.wait(2000)
            except Exception:
                continue
        self._threads.clear()
        self._update_action_buttons()
        self.append_log("已请求停止当前后台抓取任务。")
        self.statusBar().showMessage("已停止后台任务", 4000)
        self._set_status_text("后台任务已停止")

    def _update_current_main_account(self, account_name: str) -> None:
        current_name = account_name.strip()
        if not current_name:
            return
        self.settings.current_main_account_name = current_name
        save_settings(self.settings)

    def _display_account_name(self, account: AccountConfig) -> str:
        return display_account_name(account, self.settings.current_main_account_name)

    def _reset_current_main_account_name(self) -> None:
        if not self.settings.current_main_account_name.strip():
            return
        self.settings.current_main_account_name = ""
        save_settings(self.settings)

    def select_imported_accounts(self) -> None:
        self.table.clearSelection()
        selected_any = False
        for row, account in enumerate(self.accounts):
            if account.is_entry_account:
                continue
            self.table.selectionModel().select(
                self.table.model().index(row, 0),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )
            selected_any = True
        if not selected_any:
            self._show_info("提示", "没有可全选的导入账号。")
        self._update_action_buttons()

    def save_current_settings(self) -> None:
        try:
            browser_profile_dir = validate_shared_browser_profile_dir(self.profile_dir_edit.text().strip())
            self.settings = AppSettings(
                feishu_webhook=self.webhook_edit.text().strip(),
                login_wait_seconds=120,
                headless_fetch=self.settings.headless_fetch,
                browser_profile_dir=browser_profile_dir,
                current_main_account_name=self.settings.current_main_account_name,
                auto_fetch_push_enabled=self.auto_fetch_push_switch.isChecked() if self.auto_fetch_push_switch is not None else False,
            )
            save_settings(self.settings)
        except ValueError as exc:
            self._show_warning("参数错误", str(exc))
            return
        self.profile_dir_edit.setText(browser_profile_dir)
        self._apply_auto_fetch_push_schedule()
        self.append_log("全局设置已保存。")
        self.statusBar().showMessage("设置已保存", 4000)

    def choose_profile_dir(self) -> None:
        target = QFileDialog.getExistingDirectory(self, "选择共享浏览器资料目录", self.profile_dir_edit.text().strip())
        if target:
            self.profile_dir_edit.setText(target)

    def add_account(self) -> None:
        dialog = AccountDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        account = dialog.build_account()
        if not account.name:
            self._show_warning("提示", "账号名称不能为空。")
            return
        if any(item.name == account.name for item in self.accounts):
            self._show_warning("提示", f"账号“{account.name}”已存在。")
            return
        if not account.state_path:
            account.state_path = default_state_path(self.accounts)
        if not account.feedback_url:
            account.feedback_url = next(
                (item.feedback_url for item in self.accounts if item.state_path == account.state_path and item.feedback_url),
                ""
            )
        self.accounts.append(account)
        save_accounts(self.accounts)
        self.refresh_table()
        self.append_log(f"已新增账号：{account.name}，登录态文件：{account.state_path}")

    def edit_account(self) -> None:
        account = self.selected_account()
        if not account:
            self._show_info("提示", "请先选择一个账号。")
            return
        if not account.is_entry_account:
            self._show_info("提示", "导入账号不允许编辑。")
            return
        dialog = AccountDialog(account, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.build_account()
        if not updated.name:
            self._show_warning("提示", "账号名称不能为空。")
            return
        duplicate = any(item.name == updated.name for idx, item in enumerate(self.accounts) if idx != self.selected_index())
        if duplicate:
            self._show_warning("提示", f"账号“{updated.name}”已存在。")
            return
        if not updated.state_path:
            updated.state_path = account.state_path or default_state_path(self.accounts)
        if not updated.feedback_url:
            updated.feedback_url = account.feedback_url
        updated.last_login_at = account.last_login_at
        updated.last_fetch_at = account.last_fetch_at
        updated.last_deadline = account.last_deadline
        updated.last_status = account.last_status
        updated.last_note = account.last_note
        self.accounts[self.selected_index()] = updated
        save_accounts(self.accounts)
        self.refresh_table()
        self.append_log(f"已更新账号：{updated.name}")

    def import_accounts(self) -> None:
        base_account = self.selected_account()
        if not base_account:
            self._show_info("提示", "请先选择一个已登录的账号作为读取入口。")
            return
        if not base_account.is_entry_account:
            self._show_info("提示", "只有主账号可以导入账号列表。")
            return

        self._run_thread(
            lambda log: fetch_switchable_accounts(
                base_account,
                headless=self.settings.headless_fetch,
                logger=log,
                profile_dir=self.settings.browser_profile_dir,
            ),
            on_success=lambda names: self._merge_imported_accounts(base_account, names),
        )

    def _merge_imported_accounts(self, base_account: AccountConfig, names: list[str]) -> None:
        existing = {account.name for account in self.accounts}
        imported = 0
        for name in names:
            if name in BLOCKED_ACCOUNT_NAMES or name in existing:
                continue
            self.accounts.append(
                AccountConfig(
                    name=name,
                    state_path=base_account.state_path,
                    is_entry_account=False,
                    feedback_url=base_account.feedback_url,
                    home_url=base_account.home_url,
                    enabled=True,
                )
            )
            existing.add(name)
            imported += 1

        save_accounts(self.accounts)
        self.refresh_table()
        self.append_log(f"已导入 {imported} 个新账号。")

    def delete_account(self) -> None:
        selected_indexes = self.selected_indexes()
        if not selected_indexes:
            self._show_info("提示", "请先选择一个账号。")
            return
        removed_names = [self.accounts[index].name for index in selected_indexes]
        if not MessageDialog.ask_confirm(
            self,
            "确认删除",
            f"确认删除已选中的 {len(removed_names)} 个账号吗？",
            confirm_text="删除",
            cancel_text="取消",
        ):
            return
        for index in reversed(selected_indexes):
            self.accounts.pop(index)
        save_accounts(self.accounts)
        self.refresh_table()
        self.append_log(f"已删除账号：{'、'.join(removed_names)}")

    def login_selected(self) -> None:
        account = self.selected_account()
        if not account:
            self._show_info("提示", "请先选择一个账号。")
            return
        if not account.is_entry_account:
            self._show_info("提示", "导入账号不能直接保存登录态，请选择入口账号。")
            return
        self.append_log(self._login_start_message(account))
        self.statusBar().showMessage("已打开浏览器，请完成扫码登录。", 8000)
        self._run_thread(
            lambda log, _progress=None, is_cancelled=None: (
                save_login_state_with_profile(account, self.settings.login_wait_seconds, self.settings.browser_profile_dir, log, is_cancelled)
                if self.settings.browser_profile_dir.strip()
                else save_login_state(account, self.settings.login_wait_seconds, log, is_cancelled)
            ),
            on_success=lambda _: self._mark_login(account),
        )

    def _mark_login(self, account: AccountConfig) -> None:
        account.last_login_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        account.last_status = "已保存登录态"
        account.last_note = "可继续导入账号或直接抓取"
        save_accounts(self.accounts)
        self.refresh_table()
        self.append_log(f"账号 {account.name} 的登录态已保存完成。")
        self.statusBar().showMessage("登录态已保存", 5000)

    def _login_start_message(self, account: AccountConfig) -> str:
        if self.settings.browser_profile_dir.strip():
            return (
                f"正在为账号 {account.name} 打开共享浏览器资料目录。"
                f"请在 {self.settings.login_wait_seconds} 秒内完成扫码，登录成功后保持页面打开等待自动保存。"
            )
        return (
            f"正在为账号 {account.name} 打开独立登录窗口。"
            f"请在 {self.settings.login_wait_seconds} 秒内完成扫码，登录成功后保持页面打开等待自动保存。"
        )

    def validate_selected(self) -> None:
        account = self.selected_account()
        if not account:
            self._show_info("提示", "请先选择一个账号。")
            return
        if not account.is_entry_account:
            self._show_info("提示", "导入账号不能校验登录态，请选择主账号。")
            return
        self._run_thread(
            lambda log: validate_account_state(account, log, self.settings.browser_profile_dir),
            on_success=lambda ok: self._mark_validation(account, bool(ok))
        )

    def _mark_validation(self, account: AccountConfig, valid: bool) -> None:
        account.last_status = "登录有效" if valid else "登录失效"
        account.last_note = "可直接抓取" if valid else "请重新保存登录态"
        save_accounts(self.accounts)
        self.refresh_table()

    def fetch_selected(self) -> None:
        account = self.selected_account()
        if not account:
            self._show_info("提示", "请先选择一个账号。")
            return
        if account.is_entry_account:
            self._show_info("提示", "主账号不参与抓取，请选择导入账号。")
            return

        self._run_thread(
            lambda log, _progress=None, is_cancelled=None: fetch_account(
                account,
                0,
                self.settings.headless_fetch,
                log,
                self.settings.browser_profile_dir,
                is_cancelled,
            ),
            on_success=lambda result: self._mark_fetch_result(account, result),
        )

    def fetch_all(self) -> None:
        enabled_accounts = [account for account in self.accounts if account.enabled and not account.is_entry_account]
        if not enabled_accounts:
            self._show_info("提示", "没有可抓取的导入账号。")
            return

        self._run_thread(
            self._build_fetch_job(enabled_accounts),
            on_success=lambda _results: self.append_log("批量抓取已完成。"),
            on_progress=self._mark_fetch_progress,
        )

    def auto_fetch_and_send(self) -> None:
        webhook = self.webhook_edit.text().strip()
        self.settings.feishu_webhook = webhook
        if not webhook:
            self._show_warning("提示", "请先填写飞书 Webhook。")
            return
        enabled_accounts = [account for account in self.accounts if account.enabled and not account.is_entry_account]
        if not enabled_accounts:
            self._show_info("提示", "没有可抓取的导入账号。")
            return
        self._run_thread(
            self._build_fetch_job(enabled_accounts),
            on_success=lambda _results: self._send_summary_with_webhook(webhook, append_batch_log=True),
            on_progress=self._mark_fetch_progress,
        )

    def _handle_auto_fetch_push_toggled(self, checked: bool) -> None:
        self.settings.auto_fetch_push_enabled = checked
        save_settings(self.settings)
        if checked:
            self.append_log("已开启自动抓取推送，每天 09:00 自动执行。")
        else:
            self.append_log("已关闭自动抓取推送。")
        self._apply_auto_fetch_push_schedule()

    def _apply_auto_fetch_push_schedule(self) -> None:
        self._auto_fetch_timer.stop()
        if not self.settings.auto_fetch_push_enabled:
            return
        interval = self._milliseconds_until_next_auto_fetch_push()
        self._auto_fetch_timer.start(interval)

    def _milliseconds_until_next_auto_fetch_push(self, now: datetime | None = None) -> int:
        return next_auto_fetch_push_interval_ms(now)

    def _handle_auto_fetch_push_timeout(self) -> None:
        self._apply_auto_fetch_push_schedule()
        self._run_auto_fetch_push()

    def _apply_keep_alive_schedule(self) -> None:
        self._keep_alive_timer.stop()
        self._keep_alive_timer.start(KEEP_ALIVE_INTERVAL_MS)

    def _handle_keep_alive_timeout(self) -> None:
        self._apply_keep_alive_schedule()
        self._run_keep_alive()

    def _run_keep_alive(self) -> None:
        if self._threads:
            self.append_log("静默保活已跳过：当前存在后台任务。")
            return
        account = self._account_for_keep_alive()
        if account is None:
            self.append_log("静默保活已跳过：未配置主账号。")
            return
        self._run_thread(
            lambda log: keep_alive_account_state(account, log, self.settings.browser_profile_dir),
            on_success=lambda ok: self._mark_keep_alive_result(account, bool(ok)),
            update_status=False,
        )

    def _mark_keep_alive_result(self, account: AccountConfig, valid: bool) -> None:
        account.last_status = "登录有效" if valid else "登录失效"
        account.last_note = "静默保活成功，可直接抓取" if valid else "静默保活失败，请重新保存登录态"
        save_accounts(self.accounts)
        self.refresh_table()

    def _run_auto_fetch_push(self) -> None:
        webhook = self.webhook_edit.text().strip() or self.settings.feishu_webhook.strip()
        if not webhook:
            self.append_log("自动抓取推送已跳过：未配置飞书 Webhook。")
            return
        enabled_accounts = [account for account in self.accounts if account.enabled and not account.is_entry_account]
        if not enabled_accounts:
            self.append_log("自动抓取推送已跳过：没有可抓取的导入账号。")
            return
        self.settings.feishu_webhook = webhook
        self.append_log("开始执行每日自动抓取推送。")
        self._run_thread(
            self._build_fetch_job(enabled_accounts),
            on_success=lambda _results: self._send_summary_with_webhook(webhook, append_batch_log=True),
            on_progress=self._mark_fetch_progress,
        )

    def _build_fetch_job(self, enabled_accounts: list[AccountConfig]):
        def job(log, progress, is_cancelled=None) -> list[FetchResult]:
            return fetch_accounts_batch(
                enabled_accounts,
                headless=self.settings.headless_fetch,
                logger=log,
                progress=progress,
                profile_dir=self.settings.browser_profile_dir,
                is_cancelled=is_cancelled,
            )

        return job

    def _mark_fetch_progress(self, result: FetchResult) -> None:
        account = next((item for item in self.accounts if item.name == result.account_name), None)
        if account is None:
            return
        self._mark_fetch_result(account, result)

    def _mark_fetch_result(self, account: AccountConfig, result: FetchResult) -> None:
        current_main_account_name = apply_fetch_result(account, result)
        save_accounts(self.accounts)
        self._update_current_main_account(current_main_account_name)
        self.refresh_table()

    def _mark_batch_results(self, results: list[FetchResult]) -> None:
        latest_actual_account_name = apply_batch_fetch_results(self.accounts, results)
        save_accounts(self.accounts)
        if latest_actual_account_name:
            self._update_current_main_account(latest_actual_account_name)
        self.refresh_table()
        self.append_log("批量抓取已完成。")

    def send_summary(self) -> None:
        webhook = self.webhook_edit.text().strip()
        self.settings.feishu_webhook = webhook
        if not webhook:
            self._show_warning("提示", "请先填写飞书 Webhook。")
            return
        self._send_summary_with_webhook(webhook)

    def _send_summary_with_webhook(self, webhook: str, append_batch_log: bool = False) -> None:
        if append_batch_log:
            self.append_log("批量抓取已完成。")
        results = [
            FetchResult(
                account_name=account.name,
                ok=account.last_status == "抓取成功",
                actual_account_name=self._actual_account_name_from_note(account.last_note),
                deadline_text=account.last_deadline,
                note=account.last_note,
                page_url=account.home_url,
            )
            for account in self.accounts if account.enabled
        ]
        self._run_thread(
            lambda _log: send_feishu_text(webhook, build_summary(results)),
            on_success=lambda _: self.append_log("飞书汇总已发送。")
        )

    def _actual_account_name_from_note(self, note: str) -> str:
        for part in note.split("；"):
            text = part.strip()
            if text.startswith(ACTUAL_ACCOUNT_PREFIX):
                return text.removeprefix(ACTUAL_ACCOUNT_PREFIX).strip()
        return ""

    def _run_thread(self, job_builder, on_success, emit_log: bool = True, emit_failure_log: bool = True, update_status: bool = True, on_progress=None) -> None:
        self._task_runner.run(
            job_builder,
            on_success,
            emit_log=emit_log,
            emit_failure_log=emit_failure_log,
            update_status=update_status,
            on_progress=on_progress,
        )

    def _handle_thread_finished(self, thread: TaskThread) -> None:
        self._task_runner.handle_finished(thread)

    def _refresh_summary_cards(self) -> None:
        imported_accounts = [account for account in self.accounts if not account.is_entry_account]
        total = len(imported_accounts)
        enabled = sum(1 for account in imported_accounts if account.enabled)
        healthy = sum(
            1
            for account in imported_accounts
            if account.last_status in {"抓取成功", "登录有效", "已保存登录态"}
        )
        recent_times = [account.last_fetch_at for account in imported_accounts if account.last_fetch_at]
        recent = max(recent_times) if recent_times else "暂无"

        self._summary_labels["total"].setText(str(total))
        self._summary_labels["enabled"].setText(str(enabled))
        self._summary_labels["healthy"].setText(str(healthy))
        self._summary_labels["recent"].setText(recent)

    def _set_status_text(self, message: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(f"当前状态：{message}")
