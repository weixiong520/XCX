from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from desktop_py.core.models import AccountConfig


class AccountDialog(QDialog):
    def __init__(self, account: AccountConfig | None = None, parent=None):
        super().__init__(parent)
        self._account = account
        self.setWindowTitle("账号配置")
        self.setModal(True)
        self.resize(520, 320)
        self.setObjectName("accountDialog")

        self.name_edit = QLineEdit(account.name if account else "")
        self.state_path_edit = QLineEdit(account.state_path if account else "")
        self.home_url_edit = QLineEdit(account.home_url if account else "https://mp.weixin.qq.com/")
        self.name_edit.setPlaceholderText("例如：主账号、测试账号")
        self.state_path_edit.setPlaceholderText("留空时自动生成共享登录态路径")
        self.home_url_edit.setPlaceholderText("默认使用微信公众平台首页")
        self.enabled_check = QCheckBox("启用该账号")
        self.enabled_check.setChecked(True if account is None else account.enabled)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(16)
        form.addRow("账号名称", self.name_edit)
        form.addRow("登录态文件", self.state_path_edit)
        form.addRow("后台首页", self.home_url_edit)
        form.addRow("", self.enabled_check)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok_button = buttons.button(QDialogButtonBox.Ok)
        cancel_button = buttons.button(QDialogButtonBox.Cancel)
        if ok_button:
            ok_button.setText("保存")
            ok_button.setProperty("role", "primary")
        if cancel_button:
            cancel_button.setText("取消")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("账号信息")
        title.setObjectName("dialogTitle")
        subtitle = QLabel("只需维护基础资料，其余抓取状态仍由主窗口自动更新。")
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)

        card = QFrame()
        card.setObjectName("dialogCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(14)
        card_layout.addLayout(form)

        note = self._build_note()
        card_layout.addWidget(note)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(card)
        layout.addWidget(buttons)

        self.setStyleSheet(
            """
            QDialog#accountDialog {
                background: #f4f7fb;
            }
            QLabel#dialogTitle {
                color: #132238;
                font-size: 22px;
                font-weight: 700;
            }
            QLabel#dialogSubtitle {
                color: #607086;
                font-size: 13px;
                line-height: 1.5;
            }
            QFrame#dialogCard {
                background: #ffffff;
                border: 1px solid #d8e1ec;
                border-radius: 18px;
            }
            QLineEdit {
                min-height: 40px;
                padding: 0 12px;
                border: 1px solid #c8d3df;
                border-radius: 12px;
                background: #f9fbfd;
                color: #132238;
            }
            QLineEdit:focus {
                border: 1px solid #2f80ed;
                background: #ffffff;
            }
            QCheckBox {
                color: #24384d;
                spacing: 8px;
            }
            QPushButton {
                min-height: 40px;
                padding: 0 18px;
                border-radius: 12px;
                border: 1px solid #d0dae5;
                background: #ffffff;
                color: #24384d;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #f4f8fc;
            }
            QPushButton[role="primary"] {
                background: #2f80ed;
                border-color: #2f80ed;
                color: #ffffff;
            }
            QPushButton[role="primary"]:hover {
                background: #1d6fd9;
            }
            """
        )

    def _build_note(self) -> QWidget:
        note = QFrame()
        note.setObjectName("dialogNote")
        layout = QVBoxLayout(note)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(4)

        title = QLabel("填写建议")
        title.setObjectName("noteTitle")
        text = QLabel("账号名称用于列表识别；登录态文件可复用共享路径；后台首页通常保持默认即可。")
        text.setObjectName("noteText")
        text.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(text)
        note.setStyleSheet(
            """
            QFrame#dialogNote {
                background: #f5f9ff;
                border: 1px solid #d9e8ff;
                border-radius: 14px;
            }
            QLabel#noteTitle {
                color: #1d5fbf;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#noteText {
                color: #5d7187;
                font-size: 12px;
                line-height: 1.5;
            }
            """
        )
        return note

    def build_account(self) -> AccountConfig:
        return AccountConfig(
            name=self.name_edit.text().strip(),
            state_path=self.state_path_edit.text().strip(),
            is_entry_account=True if self._account is None else self._account.is_entry_account,
            home_url=self.home_url_edit.text().strip() or "https://mp.weixin.qq.com/",
            enabled=self.enabled_check.isChecked(),
        )
