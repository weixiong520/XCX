from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QStyle, QStyledItemDelegate, QTableWidget, QWidget


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
        selected_rows = (
            {item.row() for item in table.selectionModel().selectedRows()} if table.selectionModel() else set()
        )

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
