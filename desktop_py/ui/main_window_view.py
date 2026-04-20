from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QPlainTextEdit,
    QSizePolicy,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


def build_ui(window, hover_table_cls, row_highlight_delegate_cls) -> None:
    central = QWidget(window)
    central.setObjectName("centralWidget")
    window.setCentralWidget(central)
    root = QVBoxLayout(central)
    root.setContentsMargins(20, 20, 20, 20)
    root.setSpacing(14)

    root.addLayout(build_summary_strip(window))

    window.table = hover_table_cls(0, 5)
    window.table.setObjectName("accountTable")
    window.table.setHorizontalHeaderLabels(["账号", "最近截止时间", "最近状态", "结果", "启用"])
    window.table.setSelectionBehavior(QAbstractItemView.SelectRows)
    window.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    window.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    window.table.setAlternatingRowColors(True)
    window.table.setShowGrid(False)
    window.table.setSortingEnabled(False)
    window.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    window.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    window.table.verticalHeader().setVisible(False)
    window.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    window.table.setMinimumHeight(360)
    window.table.setItemDelegate(row_highlight_delegate_cls(window.table))
    header = window.table.horizontalHeader()
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
    window.table.hovered_row_changed.connect(lambda _row: window.table.viewport().update())
    window.table.itemSelectionChanged.connect(window._handle_selection_changed)

    window.log_edit = QPlainTextEdit()
    window.log_edit.setObjectName("logPanel")
    window.log_edit.setReadOnly(True)
    window.log_edit.setPlaceholderText("这里会实时显示登录、校验、抓取和汇总发送日志。")
    window.log_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
    window.log_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    window.log_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    window.log_edit.setMinimumHeight(170)

    body_layout = QGridLayout()
    body_layout.setContentsMargins(0, 0, 0, 0)
    body_layout.setHorizontalSpacing(14)
    body_layout.setVerticalSpacing(14)

    settings_panel = build_settings_box(window)
    actions_panel = build_actions_card(window)
    account_panel = wrap_card("账号概览", "集中查看账号状态、截止时间与最近抓取结果。", window.table)
    log_panel = wrap_card("运行日志", "保留后台任务回传信息，便于排查失败原因。", window.log_edit)

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

    window._status_label = QLabel("当前状态：就绪")
    window.statusBar().setFixedHeight(30)
    window.statusBar().setSizeGripEnabled(False)
    window.statusBar().addPermanentWidget(window._status_label, 1)
    window.statusBar().showMessage("就绪")


def build_summary_strip(window) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(12)
    cards = [
        ("total", "账号总数", "0"),
        ("enabled", "启用账号", "0"),
        ("healthy", "状态正常", "0"),
        ("recent", "最近抓取", "暂无"),
    ]
    for key, title, value in cards:
        layout.addWidget(build_metric_card(window, key, title, value))
    return layout


def build_metric_card(window, key: str, title: str, value: str) -> QWidget:
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
    window._summary_labels[key] = value_label
    return frame


def build_settings_box(window) -> QWidget:
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
    window.webhook_edit = QLineEdit(window.settings.feishu_webhook)
    window.profile_dir_edit = QLineEdit(window.settings.browser_profile_dir)
    window.webhook_edit.setPlaceholderText("填写飞书机器人 Webhook，用于汇总推送")
    window.profile_dir_edit.setPlaceholderText("可选，复用共享浏览器资料目录")

    layout.addWidget(QLabel("飞书 Webhook"), 0, 0)
    layout.addWidget(window.webhook_edit, 0, 1, 1, 3)
    layout.addWidget(QLabel("共享浏览器资料目录"), 1, 0)
    layout.addWidget(window.profile_dir_edit, 1, 1, 1, 3)
    browse_button = QPushButton("选择目录")
    window.browse_profile_button = browse_button
    window.browse_profile_button.setEnabled(False)
    window.browse_profile_button.setProperty("role", "primary")
    window.browse_profile_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    browse_button.clicked.connect(window.choose_profile_dir)
    layout.addWidget(browse_button, 2, 2)
    window.profile_dir_edit.installEventFilter(window)
    window.browse_profile_button.installEventFilter(window)

    save_button = QPushButton("保存设置")
    save_button.setProperty("role", "primary")
    save_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    save_button.clicked.connect(window.save_current_settings)
    layout.addWidget(save_button, 2, 3)
    layout.setColumnStretch(1, 1)
    wrapper.addWidget(form)
    return frame


def event_filter(window, watched, event, super_event_filter) -> bool:
    if watched in {window.profile_dir_edit, window.browse_profile_button} and event.type() in {QEvent.Type.FocusIn, QEvent.Type.FocusOut}:
        QTimer.singleShot(0, window._sync_browse_profile_button_state)
    return super_event_filter(watched, event)


def set_browse_profile_button_enabled(window, enabled: bool) -> None:
    if window.browse_profile_button is not None:
        window.browse_profile_button.setEnabled(enabled)


def sync_browse_profile_button_state(window) -> None:
    focus_widget = window.focusWidget()
    enabled = focus_widget in {window.profile_dir_edit, window.browse_profile_button}
    set_browse_profile_button_enabled(window, enabled)


def build_actions_card(window) -> QWidget:
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
    wrapper.addLayout(build_actions(window))
    return frame


def build_actions(window) -> QGridLayout:
    layout = QGridLayout()
    layout.setHorizontalSpacing(10)
    layout.setVerticalSpacing(12)
    actions = [
        ("新增账号", window.add_account, 0, 0),
        ("编辑账号", window.edit_account, 0, 1),
        ("全选账号", window.select_imported_accounts, 0, 2),
        ("删除账号", window.delete_account, 0, 3),
        ("导入账号", window.import_accounts, 1, 0),
        ("保存登录", window.login_selected, 1, 1),
        ("检测登录", window.validate_selected, 1, 2),
        ("停止抓取", window.stop_fetching, 1, 3),
        ("抓取并推送", window.auto_fetch_and_send, 2, 2),
        ("抓取选中", window.fetch_selected, 2, 0),
        ("发送飞书", window.send_summary, 2, 1),
    ]
    for text, handler, row, col in actions:
        button = QPushButton(text)
        if text == "保存登录":
            window.login_button = button
        if text == "编辑账号":
            window.edit_button = button
        if text == "删除账号":
            window.delete_button = button
            button.setProperty("role", "danger")
        if text == "停止抓取":
            window.stop_fetch_button = button
            button.setProperty("role", "danger")
        if text == "导入账号":
            window.import_button = button
        if text == "检测登录":
            window.validate_button = button
        if text == "抓取选中":
            window.fetch_selected_button = button
        if text == "发送飞书":
            window.send_summary_button = button
            button.setProperty("role", "success")
        if text == "抓取并推送":
            button.setProperty("role", "success")
        elif text not in {"删除账号", "停止抓取"}:
            button.setProperty("role", "primary")
        button.setMinimumWidth(0)
        button.clicked.connect(handler)
        layout.addWidget(button, row, col)
    layout.addWidget(build_auto_fetch_push_switch(window), 2, 3)
    layout.setColumnStretch(0, 1)
    layout.setColumnStretch(1, 1)
    layout.setColumnStretch(2, 1)
    layout.setColumnStretch(3, 1)
    window._update_action_buttons()
    return layout


def build_auto_fetch_push_switch(window) -> QWidget:
    switch = window._toggle_action_button_cls("自动抓取并推送")
    switch.setObjectName("autoFetchPushSwitch")
    switch.setProperty("role", "success")
    switch.setCheckable(True)
    switch.setChecked(window.settings.auto_fetch_push_enabled)
    switch.toggled.connect(window._handle_auto_fetch_push_toggled)
    window.auto_fetch_push_switch = switch
    return switch


def wrap_card(title: str, subtitle: str, content: QWidget) -> QWidget:
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


def apply_styles(window) -> None:
    window.setStyleSheet(
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


def append_log(window, message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S")
    window.log_edit.appendPlainText(f"[{timestamp}] {message}")
    window._set_status_text(message)


def refresh_table(window) -> None:
    selected_account_name = window.selected_account().name if window.selected_account() else ""
    window._sort_accounts_for_display()
    window.table.setRowCount(len(window.accounts))
    for row, account in enumerate(window.accounts):
        values = [
            window._display_account_name(account),
            window._display_deadline_text(account),
            account.last_status,
            window._display_result_text(account),
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
                item.setToolTip(window._deadline_tooltip_text(account) if col == 1 else value)
            window.table.setItem(row, col, item)
    target_row = -1
    if selected_account_name:
        for row, account in enumerate(window.accounts):
            if account.name == selected_account_name:
                target_row = row
                break
    if target_row < 0:
        for row, account in enumerate(window.accounts):
            if account.is_entry_account:
                target_row = row
                break
    if target_row < 0 and window.accounts:
        target_row = 0
    if target_row >= 0:
        window.table.selectRow(target_row)
    else:
        window.table.clearSelection()
    window.table.viewport().update()
    refresh_summary_cards(window)
    window._update_action_buttons()


def refresh_summary_cards(window) -> None:
    imported_accounts = [account for account in window.accounts if not account.is_entry_account]
    total = len(imported_accounts)
    enabled = sum(1 for account in imported_accounts if account.enabled)
    healthy = sum(
        1
        for account in imported_accounts
        if account.last_status in {"抓取成功", "登录有效", "已保存登录态"}
    )
    recent_times = [account.last_fetch_at for account in imported_accounts if account.last_fetch_at]
    recent = max(recent_times) if recent_times else "暂无"

    window._summary_labels["total"].setText(str(total))
    window._summary_labels["enabled"].setText(str(enabled))
    window._summary_labels["healthy"].setText(str(healthy))
    window._summary_labels["recent"].setText(recent)


def set_status_text(window, message: str) -> None:
    if window._status_label is not None:
        window._status_label.setText(f"当前状态：{message}")
