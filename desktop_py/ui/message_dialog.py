from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class MessageIcon(QWidget):
    def __init__(self, tone: str = "info", parent=None):
        super().__init__(parent)
        self._tone = tone
        self.setFixedSize(34, 34)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)

        color = QColor("#2f80ed") if self._tone == "info" else QColor("#f39c12")
        path = QPainterPath()
        path.moveTo(self.width() / 2, 2)
        path.lineTo(self.width() - 1, self.height() - 4)
        path.lineTo(1, self.height() - 4)
        path.closeSubpath()
        painter.fillPath(path, color)

        painter.setPen(QPen(QColor("#ffffff"), 2.2))
        painter.drawLine(self.width() / 2, 10, self.width() / 2, 20)
        painter.drawPoint(self.width() / 2, 26)
        painter.end()


class MessageDialog(QDialog):
    def __init__(
        self,
        title: str,
        text: str,
        tone: str = "info",
        parent=None,
        confirm_text: str = "知道了",
        cancel_text: str = "",
    ):
        super().__init__(parent)
        self.setObjectName("messageDialog")
        self.setModal(True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setFixedWidth(440)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setObjectName("dialogCard")

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 18, 22, 20)
        card_layout.setSpacing(18)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)

        title_label = QLabel(title)
        title_label.setObjectName("dialogTitle")

        header.addWidget(title_label)
        header.addStretch(1)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(14)

        icon_badge = MessageIcon(tone, self)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)

        message_label = QLabel(text)
        message_label.setObjectName("messageText")
        message_label.setWordWrap(True)
        content_layout.addWidget(message_label)

        body.addWidget(icon_badge, 0, Qt.AlignmentFlag.AlignTop)
        body.addWidget(content, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch(1)
        if cancel_text:
            cancel_button = QPushButton(cancel_text)
            cancel_button.setObjectName("cancelButton")
            cancel_button.clicked.connect(self.reject)
            footer.addWidget(cancel_button)

        confirm_button = QPushButton(confirm_text)
        confirm_button.setObjectName("confirmButton")
        confirm_button.clicked.connect(self.accept)
        footer.addWidget(confirm_button)

        card_layout.addLayout(header)
        card_layout.addLayout(body)
        card_layout.addLayout(footer)
        root.addWidget(card)

        self.setStyleSheet(
            """
            QDialog#messageDialog {
                background: #ffffff;
            }
            QFrame#dialogCard {
                background: #ffffff;
                border: 1px solid #d8e1ec;
                border-radius: 0px;
            }
            QLabel#dialogTitle {
                color: #132238;
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#messageText {
                color: #24384d;
                font-size: 14px;
                line-height: 1.6;
            }
            QPushButton#confirmButton {
                min-width: 72px;
                min-height: 40px;
                padding: 0 10px;
                border: 1px solid #2f80ed;
                border-radius: 0px;
                background: #2f80ed;
                color: #ffffff;
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton#confirmButton:hover {
                background: #1d6fd9;
                border-color: #1d6fd9;
            }
            QPushButton#cancelButton {
                min-width: 72px;
                min-height: 40px;
                padding: 0 10px;
                border: 1px solid #d0dae5;
                border-radius: 0px;
                background: #ffffff;
                color: #24384d;
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton#cancelButton:hover {
                background: #f4f8fc;
                border-color: #b8cadf;
            }
            """
        )

    @classmethod
    def show_info(cls, parent, title: str, text: str) -> int:
        return cls(title, text, "info", parent).exec()

    @classmethod
    def show_warning(cls, parent, title: str, text: str) -> int:
        return cls(title, text, "warning", parent).exec()

    @classmethod
    def ask_confirm(cls, parent, title: str, text: str, confirm_text: str = "确认", cancel_text: str = "取消") -> bool:
        return cls(title, text, "warning", parent, confirm_text=confirm_text, cancel_text=cancel_text).exec() == int(
            QDialog.DialogCode.Accepted
        )
