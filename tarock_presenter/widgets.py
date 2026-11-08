"""Low-level Qt painting helpers: rounded table rows/header, rounded-corner masks, pixel wipe."""
from __future__ import annotations

import random

from PyQt6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QRegion
from PyQt6.QtWidgets import QHeaderView, QStyledItemDelegate, QWidget


class RoundedRowDelegate(QStyledItemDelegate):
    """Draws each table row as a rounded card spanning all columns, text centred."""
    RADIUS = 12
    V_PAD  = 8   # gap above and below the card within the cell height

    def paint(self, painter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        table = self.parent()
        col   = index.column()

        # Draw the full-row background once, from the leftmost column
        if col == 0:
            bg_color = QColor("#0d0d1a")
            bg_color.setAlpha(220)

            total_w = sum(table.columnWidth(c) for c in range(table.columnCount()))
            card = QRectF(
                option.rect.x() + self.V_PAD,
                option.rect.y() + self.V_PAD,
                total_w - self.V_PAD * 2,
                option.rect.height() - self.V_PAD * 2,
            )
            painter.setBrush(bg_color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(card, self.RADIUS, self.RADIUS)

        # Draw text centred in each cell
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        font_data = index.data(Qt.ItemDataRole.FontRole)
        if font_data:
            painter.setFont(font_data)
        if col == 0:
            align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        elif col == 2:
            align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        else:
            align = Qt.AlignmentFlag.AlignCenter
        painter.setPen(QColor("white"))
        painter.drawText(option.rect, align, text)

        painter.restore()


class RoundedHeader(QHeaderView):
    """Horizontal header that paints one rounded card spanning all sections."""
    RADIUS = 12
    V_PAD  = 5

    def __init__(self, parent=None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setMinimumHeight(80)

    def paintSection(self, painter, rect, logical_index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw full-width background card once from the first section
        if logical_index == 0:
            total_w = sum(self.sectionSize(i) for i in range(self.count()))
            card = QRectF(
                rect.x(),
                rect.y() + self.V_PAD,
                total_w,
                rect.height() - self.V_PAD * 2,
            )
            rad = float(self.RADIUS)
            path = QPainterPath()
            path.moveTo(card.left(), card.top())
            path.lineTo(card.right(), card.top())
            path.lineTo(card.right(), card.bottom() - rad)
            path.arcTo(card.right() - rad * 2, card.bottom() - rad * 2, rad * 2, rad * 2, 0, -90)
            path.lineTo(card.left() + rad, card.bottom())
            path.arcTo(card.left(), card.bottom() - rad * 2, rad * 2, rad * 2, 270, -90)
            path.closeSubpath()
            painter.setBrush(QColor("#FF0000"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(path)

        # Draw header label centred
        text = self.model().headerData(
            logical_index, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole
        )
        font = QFont("Noto Serif")
        font.setBold(True)
        font.setPointSize(30)
        if logical_index == 0:
            align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        elif logical_index == 2:
            align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        else:
            align = Qt.AlignmentFlag.AlignCenter
        painter.setFont(font)
        painter.setPen(QColor("white"))
        painter.drawText(rect, align, str(text or ""))
        painter.restore()


class TopRoundedMask(QObject):
    """Keeps a widget's painted area clipped to a shape with rounded top corners."""
    def __init__(self, widget: QWidget, radius: int) -> None:
        super().__init__(widget)
        self._radius = radius
        widget.installEventFilter(self)
        self._apply(widget)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize:
            self._apply(obj)
        return False

    def _apply(self, widget: QWidget) -> None:
        r = QRectF(widget.rect())
        rad = float(self._radius)
        path = QPainterPath()
        path.moveTo(r.left(), r.bottom())
        path.lineTo(r.left(), r.top() + rad)
        path.arcTo(r.left(), r.top(), rad * 2, rad * 2, 180, -90)
        path.lineTo(r.right() - rad, r.top())
        path.arcTo(r.right() - rad * 2, r.top(), rad * 2, rad * 2, 90, -90)
        path.lineTo(r.right(), r.bottom())
        path.closeSubpath()
        widget.setMask(QRegion(path.toFillPolygon().toPolygon(), Qt.FillRule.WindingFill))


class BottomRoundedMask(QObject):
    """Keeps a widget's painted area clipped to a shape with rounded bottom corners."""
    def __init__(self, widget: QWidget, radius: int) -> None:
        super().__init__(widget)
        self._radius = radius
        widget.installEventFilter(self)
        self._apply(widget)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Resize:
            self._apply(obj)
        return False

    def _apply(self, widget: QWidget) -> None:
        r = QRectF(widget.rect())
        rad = float(self._radius)
        path = QPainterPath()
        path.moveTo(r.left(), r.top())
        path.lineTo(r.right(), r.top())
        path.lineTo(r.right(), r.bottom() - rad)
        path.arcTo(r.right() - rad * 2, r.bottom() - rad * 2, rad * 2, rad * 2, 0, -90)
        path.lineTo(r.left() + rad, r.bottom())
        path.arcTo(r.left(), r.bottom() - rad * 2, rad * 2, rad * 2, 270, -90)
        path.closeSubpath()
        widget.setMask(QRegion(path.toFillPolygon().toPolygon(), Qt.FillRule.WindingFill))


class PixelTrickleOverlay(QWidget):
    """White block overlay for pixel transitions.
    pixel-out: content fully visible → random white blocks cover it.
    """
    _BLOCK = 20
    _INTERVAL_MS = 25

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._on_done = None
        self._pending: list[tuple[int, int]] = []
        self._masked: set[tuple[int, int]] = set()
        self._per_tick = 1
        self._pixelout = True
        self._timer = QTimer(self)
        self._timer.setInterval(self._INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def _build_blocks(self) -> list[tuple[int, int]]:
        cols = max(1, (self.width()  + self._BLOCK - 1) // self._BLOCK)
        rows = max(1, (self.height() + self._BLOCK - 1) // self._BLOCK)
        blocks = [(c, r) for c in range(cols) for r in range(rows)]
        random.shuffle(blocks)
        return blocks

    def start_pixelout(self, on_done) -> None:
        """Content visible → random white blocks fill in until all covered."""
        self._on_done = on_done
        self._pixelout = True
        self.resize(self.parent().size())
        self.raise_()
        self._pending = self._build_blocks()
        self._masked = set()
        self._per_tick = max(1, len(self._pending) // 40)
        self.setMask(QRegion())
        self.show()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self.clearMask()
        self.hide()

    def _apply_mask(self) -> None:
        region = QRegion()
        for col, row in self._masked:
            region = region.united(
                QRegion(col * self._BLOCK, row * self._BLOCK, self._BLOCK, self._BLOCK)
            )
        self.setMask(region)
        self.update()

    def _tick(self) -> None:
        for _ in range(self._per_tick):
            if self._pending:
                self._masked.add(self._pending.pop())
        self._apply_mask()
        if not self._pending:
            self._timer.stop()
            if self._on_done:
                self._on_done()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("white"))
        painter.end()
