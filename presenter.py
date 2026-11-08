#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Tarock presentation window (read-only).

Shows the animated results of a tournament straight from the SQLite database
written by the data-entry tool (tarockmanager.py). This program never writes
to the database: it opens it read-only, so SQLite itself rejects any write.
"""

from __future__ import annotations

import argparse
import io
import random
import sys
from pathlib import Path

import qrcode

from tarock_core import db, ranking
from tarock_core.paths import DEFAULT_DB, REPO_ROOT, ordinal

from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QMessageBox,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QSizePolicy,
    QGraphicsOpacityEffect,
    QStyledItemDelegate,
)
from PyQt6.QtGui import QKeySequence, QShortcut, QFont, QColor, QPainterPath, QRegion, QPainter, QPixmap, QImage
from PyQt6.QtCore import (
    Qt, QTimer, QRectF, QEvent, QObject,
    QPropertyAnimation, QSequentialAnimationGroup, QEasingCurve,
)

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
    from matplotlib.figure import Figure
    _MATPLOTLIB_OK = True
except ImportError:
    _MATPLOTLIB_OK = False


class _RoundedRowDelegate(QStyledItemDelegate):
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


class _RoundedHeader(QHeaderView):
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


class _TopRoundedMask(QObject):
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


class _BottomRoundedMask(QObject):
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


class _PixelTrickleOverlay(QWidget):
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


class GraphWindow(QWidget):
    # frame 0 → ranking table   frame 1 → compare graph
    AUTO_RANKING_MS = 5_000
    AUTO_COMPARE_MS = 10_000

    _MEDAL      = {0: "👑", 1: "🥈", 2: "🥉", 4: "🍈"}
    _LAST_MEDAL = "🌭"
    _ROW_BG = {0: QColor("#FFD700"), 1: QColor("#C0C0C0"), 2: QColor("#CD7F32")}
    _ROW_ALT = (QColor("#F2F2F2"), QColor("#E2E2E2"))

    FS_TITLE  = 36
    FS_LABEL  = 28
    FS_TICK   = 22
    FS_LEGEND = 24

    PLAYER_COLORS = [
        "gold", "silver", "#CD7F32", "steelblue", "tomato", "limegreen",
        "orchid", "cyan", "orange", "hotpink", "yellowgreen", "aquamarine",
        "cornflowerblue", "salmon",
    ]

    def __init__(self, standings: ranking.Standings, title: str = "Pony Tarock Championship", auto_speed: float = 1.0, auto_resume_s: int = 180) -> None:
        super().__init__()
        self._title = title
        self.setWindowTitle(title)
        self.resize(960, 700)

        # Scale all auto-mode durations by auto_speed (2.0 = twice as slow)
        def _ms(base: int) -> int:
            return max(100, int(base * auto_speed))

        self._logo_fade_in_ms  = _ms(2_000)
        self._logo_hold_ms     = _ms(2_000)
        self._logo_fade_out_ms = _ms(1_000)
        self._compare_ms       = _ms(self.AUTO_COMPARE_MS)
        self._walter_hold_ms   = _ms(3_000)

        # All numbers come from tarock_core.ranking - nothing is recomputed here.
        self._frame       = 0
        self._rank_reveal = 0   # how many ranking rows are currently visible
        self._total_frames = 2  # frame 0: ranking, frame 1: compare
        self._player_colors: dict[str, str] = {}
        self._compare_selected: set[str] = set()
        self._set_data(standings)

        self._resume_labels: list[QLabel] = []
        self._splash_content: QWidget | None = None
        self._splash_logo_lbl: QLabel | None = None

        # ---- Page 0: Splash ---- Page 1: Ranking ---- Page 2: Compare ---- Page 3: Walter advert ----
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_splash_page())        # 0
        self._stack.addWidget(self._build_ranking_page())       # 1
        self._stack.addWidget(self._build_compare_page())       # 2
        self._stack.addWidget(self._build_walter_advert_page()) # 3

        self._advert_prev_index = 0

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self._stack)

        self._stack.setCurrentIndex(0)  # start on splash

        QShortcut(QKeySequence(Qt.Key.Key_Left),   self).activated.connect(self._user_back)
        QShortcut(QKeySequence(Qt.Key.Key_Right),  self).activated.connect(self._user_forward)
        QShortcut(QKeySequence(Qt.Key.Key_F11),    self).activated.connect(self._toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key.Key_F),      self).activated.connect(self._toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self._exit_fullscreen)
        QShortcut(QKeySequence(Qt.Key.Key_Space),  self).activated.connect(self._reveal_next)
        QShortcut(QKeySequence(Qt.Key.Key_A),      self).activated.connect(self._toggle_auto)
        QShortcut(QKeySequence(Qt.Key.Key_W),      self).activated.connect(self._toggle_walter_advert)

        self._auto_state = 0  # 0 = logo, 1 = compare
        self._auto_ever_started = False
        self._logo_anim: QSequentialAnimationGroup | None = None
        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._auto_next)
        self._resume_timer = QTimer(self)
        self._resume_timer.setSingleShot(True)
        self._resume_timer.setInterval(auto_resume_s * 1_000)
        self._resume_timer.timeout.connect(self._resume_auto)
        self._walter_hold_timer = QTimer(self)
        self._walter_hold_timer.setSingleShot(True)
        self._walter_hold_timer.timeout.connect(self._start_walter_pixelout)

    # ------------------------------------------------------------------
    def _set_data(self, standings: ranking.Standings) -> None:
        """Derive all display data from `standings` (initial load and live updates)."""
        self._standings = standings
        self._rounds = list(standings.rounds)
        self._ranked = [str(s.player) for s in standings.rows]
        self._names = {str(s.player): s.name for s in standings.rows}
        self._rank_of = {str(s.player): s.rank for s in standings.rows}
        self._cumulative = {
            str(s.player): standings.cumulative(s.player) for s in standings.rows
        }
        # Known players keep their colour across updates; new players get an unused one.
        colors = {p: c for p, c in self._player_colors.items() if p in self._names}
        free = [c for c in self.PLAYER_COLORS if c not in colors.values()]
        for pnum in self._ranked:
            if pnum not in colors:
                colors[pnum] = free.pop(0) if free else self.PLAYER_COLORS[len(colors) % len(self.PLAYER_COLORS)]
        self._player_colors = colors

    def update_standings(self, standings: ranking.Standings) -> None:
        """Live refresh: rebuild the data-dependent pages, keeping the view state."""
        if standings == self._standings:
            return
        was_all_revealed = self._rank_reveal >= len(self._ranked)
        selected = set(self._compare_selected)
        current = self._stack.currentIndex()
        auto_text = self._splash_auto_btn.text()

        self._set_data(standings)
        self._compare_selected = {p for p in selected if p in self._names}
        n = len(self._ranked)
        self._rank_reveal = n if was_all_revealed else min(self._rank_reveal, n)

        old_pages = [self._stack.widget(1), self._stack.widget(2)]
        new_pages = [self._build_ranking_page(), self._build_compare_page()]
        self._resume_labels = [
            lbl for lbl in self._resume_labels
            if not any(page.isAncestorOf(lbl) for page in old_pages)
        ]
        for page in old_pages:
            self._stack.removeWidget(page)
            page.deleteLater()
        self._stack.insertWidget(1, new_pages[0])
        self._stack.insertWidget(2, new_pages[1])
        self._stack.setCurrentIndex(current)

        for i in range(self._rank_reveal):                 # rows are revealed last place first
            self._rank_tbl.setRowHidden(n - 1 - i, False)
        for pnum, btn in self._compare_btns.items():
            btn.setChecked(pnum in self._compare_selected)
        self._set_auto_btn_text(auto_text)
        self._set_resume_visible(self._resume_timer.isActive())
        self._update_rank_font_size()
        self._redraw_compare()

    def _make_auto_btn_widget(self) -> tuple[QWidget, QPushButton]:
        """Return (container, button) — container includes the auto button and a hidden autoresume label."""
        btn_style = (
            "font-size: 36px; padding: 12px 40px; color: #FF0000;"
            " background-color: white; border-radius: 10px;"
        )
        btn = QPushButton("Auto")
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setStyleSheet(btn_style)
        btn.clicked.connect(self._toggle_auto)

        resume_lbl = QLabel("(autoresume)")
        resume_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        resume_lbl.setStyleSheet("color: white; font-size: 20px; background: transparent;")
        resume_lbl.setVisible(False)
        self._resume_labels.append(resume_lbl)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(btn)
        lay.addWidget(resume_lbl)

        return container, btn

    def _set_resume_visible(self, show: bool) -> None:
        for lbl in self._resume_labels:
            lbl.setVisible(show)

    # ------------------------------------------------------------------
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress:
            if obj is self._splash_content or obj is self._splash_logo_lbl:
                self._on_logo_click()
            elif obj is self._walter_content:
                self._on_walter_click()
            elif obj is self._compare_canvas:
                self._on_compare_click()
        return False

    def _on_compare_click(self) -> None:
        if self._auto_ever_started and not self._is_auto_running():
            self._cancel_resume()
            self._resume_timer.start()
            self._set_resume_visible(True)

    def _on_logo_click(self) -> None:
        if not self._is_auto_running():
            return
        if self._logo_anim is not None:
            try:
                self._logo_anim.finished.disconnect()
            except Exception:
                pass
            self._logo_anim.stop()
            self._logo_anim = None
        self._logo_effect.setOpacity(1.0)
        self._auto_state = 2
        self._auto_show_compare()

    def _on_walter_click(self) -> None:
        if not self._is_auto_running():
            return
        self._walter_hold_timer.stop()
        self._walter_overlay.stop()
        self._auto_state = 2
        self._auto_show_compare()

    # ------------------------------------------------------------------
    def _player_name(self, pnum: str) -> str:
        return self._names[pnum]

    def _build_splash_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background-color: #0d0d1a;")

        btn_style = (
            "font-size: 36px; padding: 12px 40px; color: #FF0000;"
            " background-color: white; border-radius: 10px;"
        )

        splash_logo_btn = QPushButton("Logo")
        splash_logo_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        splash_logo_btn.setStyleSheet(btn_style)
        splash_logo_btn.clicked.connect(self._jump_to_logo)

        splash_ranking_btn = QPushButton("Ranking")
        splash_ranking_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        splash_ranking_btn.setStyleSheet(btn_style)
        splash_ranking_btn.clicked.connect(self._jump_to_ranking)

        splash_compare_btn = QPushButton("Compare")
        splash_compare_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        splash_compare_btn.setStyleSheet(btn_style)
        splash_compare_btn.clicked.connect(self._jump_to_compare)

        splash_auto_container, self._splash_auto_btn = self._make_auto_btn_widget()

        top_bar = QWidget()
        top_bar.setStyleSheet(
            "background-color: #FF0000;"
            " border-top-left-radius: 16px; border-top-right-radius: 16px;"
        )
        header_lbl = QLabel(self._title)
        header_lbl.setStyleSheet(
            "color: white; font-size: 36px; font-weight: bold; background-color: transparent;"
        )
        top_bar_lay = QHBoxLayout(top_bar)
        top_bar_lay.setContentsMargins(24, 8, 12, 8)
        top_bar_lay.addWidget(header_lbl)
        top_bar_lay.addStretch(1)
        top_bar_lay.addWidget(splash_logo_btn)
        top_bar_lay.addWidget(splash_compare_btn)
        top_bar_lay.addWidget(splash_auto_container)
        top_bar_lay.addWidget(splash_ranking_btn)
        _TopRoundedMask(top_bar, 16)

        content = QWidget()
        content.setObjectName("splashContent")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        content.setStyleSheet("QWidget#splashContent { background-color: #FF0000; }")

        lbl = QLabel("Café Pony")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            "color: white; font-size: 280px; font-weight: bold; background: transparent; border: none;"
        )
        self._logo_effect = QGraphicsOpacityEffect(lbl)
        self._logo_effect.setOpacity(1.0)
        lbl.setGraphicsEffect(self._logo_effect)

        content_lay = QVBoxLayout(content)
        content_lay.addWidget(lbl)

        _BottomRoundedMask(content, 16)

        self._splash_content = content
        self._splash_logo_lbl = lbl
        content.installEventFilter(self)
        lbl.installEventFilter(self)

        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(0)
        lay.addWidget(top_bar)
        lay.addWidget(content, 1)

        return page

    def _skip_splash(self) -> bool:
        if self._stack.currentIndex() != 0:
            return False
        self._stop_auto()
        self._stack.setCurrentIndex(1)
        return True

    def _build_ranking_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background-color: #0d0d1a;")

        tbl = QTableWidget(len(self._ranked), 3)
        rounded_header = _RoundedHeader(tbl)
        tbl.setHorizontalHeader(rounded_header)
        tbl.setHorizontalHeaderLabels(["Rank", "Player", "Points"])
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tbl.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tbl.verticalHeader().setVisible(False)
        tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tbl.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        tbl.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        tbl.setShowGrid(False)
        tbl.setStyleSheet("""
            QTableWidget {
                gridline-color: transparent;
                border: none;
                background-color: #0d0d1a;
            }
        """)
        tbl.setItemDelegate(_RoundedRowDelegate(tbl))

        item_font = QFont("Noto Serif")
        item_font.setBold(True)
        item_font.setPointSize(30)

        last_rank = max(self._rank_of.values(), default=0)
        for i, pnum in enumerate(self._ranked):
            rank = self._rank_of[pnum]
            tie = "=" if sum(1 for r in self._rank_of.values() if r == rank) > 1 else ""
            if rank == last_rank and last_rank > 1:
                medal = self._LAST_MEDAL
            else:
                medal = self._MEDAL.get(rank - 1, "")
            rank_str = f"{medal}  {rank}.{tie}" if medal else f"    {rank}.{tie}"
            name     = self._player_name(pnum)
            total    = str(self._cumulative[pnum][-1])

            for col, text in enumerate([rank_str, name, total]):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if rank - 1 in self._ROW_BG:
                    item.setBackground(self._ROW_BG[rank - 1])
                else:
                    item.setBackground(QColor("#FF0000"))
                item.setFont(item_font)
                tbl.setItem(i, col, item)

        # All rows start hidden; revealed one-by-one via navigation
        for i in range(tbl.rowCount()):
            tbl.setRowHidden(i, True)
        self._rank_tbl = tbl

        btn_style = (
            "font-size: 36px; padding: 12px 40px; color: #FF0000;"
            " background-color: white; border-radius: 10px;"
        )

        rank_logo_btn = QPushButton("Logo")
        rank_logo_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        rank_logo_btn.setStyleSheet(btn_style)
        rank_logo_btn.clicked.connect(self._jump_to_logo)

        rank_ranking_btn = QPushButton("Ranking")
        rank_ranking_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        rank_ranking_btn.setStyleSheet(btn_style)
        rank_ranking_btn.clicked.connect(self._jump_to_ranking)

        rank_compare_btn = QPushButton("Compare")
        rank_compare_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        rank_compare_btn.setStyleSheet(btn_style)
        rank_compare_btn.clicked.connect(self._jump_to_compare)

        rank_auto_container, self._rank_auto_btn = self._make_auto_btn_widget()

        top_bar_widget = QWidget()
        top_bar_widget.setStyleSheet(
            "background-color: #FF0000;"
            " border-top-left-radius: 16px; border-top-right-radius: 16px;"
        )
        header_lbl = QLabel(self._title)
        header_lbl.setStyleSheet(
            "color: white; font-size: 36px; font-weight: bold;"
            " background-color: transparent;"
        )

        top_bar = QHBoxLayout(top_bar_widget)
        top_bar.setContentsMargins(24, 8, 12, 8)
        top_bar.addWidget(header_lbl)
        top_bar.addStretch(1)
        top_bar.addWidget(rank_logo_btn)
        top_bar.addWidget(rank_compare_btn)
        top_bar.addWidget(rank_auto_container)
        top_bar.addWidget(rank_ranking_btn)
        _TopRoundedMask(top_bar_widget, 16)

        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(0)
        # Wrapper provides the rounded bottom corners:
        # its dark background shows through the 16 px bottom margin and curved border.
        table_frame = QWidget()
        table_frame.setObjectName("tableFrame")
        table_frame.setStyleSheet("""
            QWidget#tableFrame {
                background-color: #0d0d1a;
                border: 2px solid black;
                border-top: none;
                border-radius: 0 0 16px 16px;
            }
        """)
        frame_lay = QVBoxLayout(table_frame)
        frame_lay.setContentsMargins(2, 0, 2, 16)
        frame_lay.setSpacing(0)
        frame_lay.addWidget(tbl)

        # Clip the viewport (cell area) to rounded bottom corners so cells
        # don't bleed into the corners of the frame.
        _BottomRoundedMask(tbl.viewport(), 16)

        lay.addWidget(top_bar_widget)
        lay.addWidget(table_frame)
        return page

    def _update_rank_font_size(self) -> None:
        if not hasattr(self, "_rank_tbl"):
            return
        tbl = self._rank_tbl
        n = tbl.rowCount()
        if n == 0:
            return
        row_px = max(1, tbl.viewport().height() // n)
        pt = max(14, int(row_px * 0.75))
        font = QFont("Noto Serif")
        font.setBold(True)
        font.setPointSize(pt)
        for i in range(n):
            for col in range(tbl.columnCount()):
                item = tbl.item(i, col)
                if item:
                    item.setFont(font)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_rank_font_size()

    # ------------------------------------------------------------------
    def _build_compare_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background-color: #0d0d1a;")

        btn_style = (
            "font-size: 36px; padding: 12px 40px; color: #FF0000;"
            " background-color: white; border-radius: 10px;"
        )

        compare_logo_btn = QPushButton("Logo")
        compare_logo_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        compare_logo_btn.setStyleSheet(btn_style)
        compare_logo_btn.clicked.connect(self._jump_to_logo)

        compare_ranking_btn = QPushButton("Ranking")
        compare_ranking_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        compare_ranking_btn.setStyleSheet(btn_style)
        compare_ranking_btn.clicked.connect(self._jump_to_ranking)

        compare_nav_btn = QPushButton("Compare")
        compare_nav_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        compare_nav_btn.setStyleSheet(btn_style)
        compare_nav_btn.clicked.connect(self._jump_to_compare)

        compare_auto_container, self._compare_auto_btn = self._make_auto_btn_widget()

        top_bar = QWidget()
        top_bar.setStyleSheet(
            "background-color: #FF0000;"
            " border-top-left-radius: 16px; border-top-right-radius: 16px;"
        )
        header_lbl = QLabel(self._title)
        header_lbl.setStyleSheet(
            "color: white; font-size: 36px; font-weight: bold; background-color: transparent;"
        )
        top_bar_lay = QHBoxLayout(top_bar)
        top_bar_lay.setContentsMargins(24, 8, 12, 8)
        top_bar_lay.addWidget(header_lbl)
        top_bar_lay.addStretch(1)
        top_bar_lay.addWidget(compare_logo_btn)
        top_bar_lay.addWidget(compare_nav_btn)
        top_bar_lay.addWidget(compare_auto_container)
        top_bar_lay.addWidget(compare_ranking_btn)
        _TopRoundedMask(top_bar, 16)

        # --- Left sidebar: one toggle button per player ---
        player_panel = QWidget()
        player_panel.setStyleSheet("background-color: #0d0d1a;")
        player_layout = QVBoxLayout(player_panel)
        player_layout.setContentsMargins(8, 8, 8, 8)
        player_layout.setSpacing(6)

        self._compare_btns: dict[str, QPushButton] = {}
        for pnum in self._ranked:
            rank = self._rank_of[pnum]
            name = self._player_name(pnum)
            color = self._player_colors[pnum]
            btn = QPushButton(f"{rank}. {name}")
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(f"""
                QPushButton {{
                    font-size: 18px;
                    font-weight: bold;
                    padding: 10px 14px;
                    color: {color};
                    background-color: #1a1a2e;
                    border: 2px solid {color};
                    border-radius: 8px;
                    text-align: left;
                }}
                QPushButton:checked {{
                    background-color: {color};
                    color: black;
                    font-weight: bold;
                }}
            """)
            btn.clicked.connect(lambda _checked, p=pnum: self._toggle_compare_player(p))
            self._compare_btns[pnum] = btn
            player_layout.addWidget(btn)

        player_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(player_panel)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(230)
        scroll.setStyleSheet("background-color: #0d0d1a; border: none;")

        # --- Right: dedicated matplotlib canvas ---
        self._compare_fig = Figure(tight_layout=True, facecolor="black")
        self._compare_canvas = FigureCanvas(self._compare_fig)
        self._compare_ax = self._compare_fig.add_subplot(111)
        self._compare_canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self._compare_canvas.installEventFilter(self)

        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 8, 0, 0)
        body_lay.setSpacing(8)
        body_lay.addWidget(scroll, 0)
        body_lay.addWidget(self._compare_canvas, 1)

        page_lay = QVBoxLayout(page)
        page_lay.setContentsMargins(24, 24, 24, 24)
        page_lay.setSpacing(0)
        page_lay.addWidget(top_bar, 0)
        page_lay.addWidget(body, 1)

        return page

    # ------------------------------------------------------------------
    def _build_walter_advert_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background-color: #0d0d1a;")

        btn_style = (
            "font-size: 36px; padding: 12px 40px; color: #FF0000;"
            " background-color: white; border-radius: 10px;"
        )

        logo_btn = QPushButton("Logo")
        logo_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        logo_btn.setStyleSheet(btn_style)
        logo_btn.clicked.connect(self._jump_to_logo)

        ranking_btn = QPushButton("Ranking")
        ranking_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        ranking_btn.setStyleSheet(btn_style)
        ranking_btn.clicked.connect(self._jump_to_ranking)

        compare_btn = QPushButton("Compare")
        compare_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        compare_btn.setStyleSheet(btn_style)
        compare_btn.clicked.connect(self._jump_to_compare)

        auto_container, _ = self._make_auto_btn_widget()

        top_bar = QWidget()
        top_bar.setStyleSheet(
            "background-color: #FF0000;"
            " border-top-left-radius: 16px; border-top-right-radius: 16px;"
        )
        header_lbl = QLabel(self._title)
        header_lbl.setStyleSheet(
            "color: white; font-size: 36px; font-weight: bold; background-color: transparent;"
        )
        top_bar_lay = QHBoxLayout(top_bar)
        top_bar_lay.setContentsMargins(24, 8, 12, 8)
        top_bar_lay.addWidget(header_lbl)
        top_bar_lay.addStretch(1)
        top_bar_lay.addWidget(logo_btn)
        top_bar_lay.addWidget(compare_btn)
        top_bar_lay.addWidget(auto_container)
        top_bar_lay.addWidget(ranking_btn)
        _TopRoundedMask(top_bar, 16)

        content = QWidget()
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        content.setStyleSheet("background-color: white;")

        name_lbl = QLabel("WALTER !")
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        name_lbl.setStyleSheet(
            "color: #FF0000; font-size: 160px; font-weight: bold;"
            " background: transparent; border: none;"
            " margin-left: 40px; margin-top: 30px;"
        )

        tagline_lbl = QLabel("best MALER <s>in town</s> ever")
        tagline_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        tagline_lbl.setStyleSheet(
            "color: #FF0000; font-size: 80px; font-weight: bold; font-style: italic;"
            " background: transparent; border: none;"
            " margin-right: 40px; margin-bottom: 30px;"
        )
        tagline_lbl.setWordWrap(True)

        _qr = qrcode.QRCode(box_size=6, border=2)
        _qr.add_data("WE LOVE WALTER")
        _qr.make(fit=True)
        _qr_img = _qr.make_image(fill_color="#FF0000", back_color="white")
        _buf = io.BytesIO()
        _qr_img.save(_buf, format="PNG")
        _qr_pixmap = QPixmap.fromImage(QImage.fromData(_buf.getvalue()))

        qr_lbl = QLabel()
        qr_lbl.setPixmap(_qr_pixmap)
        qr_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        qr_lbl.setStyleSheet("background: transparent; border: none; margin-right: 40px; margin-top: 20px;")

        content_lay = QVBoxLayout(content)

        top_row = QWidget()
        top_row.setStyleSheet("background: transparent;")
        top_lay = QHBoxLayout(top_row)
        top_lay.setContentsMargins(0, 0, 0, 0)
        top_lay.addWidget(name_lbl)
        top_lay.addStretch(1)
        top_lay.addWidget(qr_lbl)

        content_lay.addWidget(top_row)

        walter_img_path = REPO_ROOT / "images" / "walter2.png"
        if walter_img_path.exists():
            walter_pixmap = QPixmap(str(walter_img_path))
            walter_img_lbl = QLabel()
            walter_img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            walter_img_lbl.setStyleSheet("background: transparent; border: none;")
            walter_img_lbl.setPixmap(
                walter_pixmap.scaledToHeight(400, Qt.TransformationMode.SmoothTransformation)
            )
            content_lay.addStretch(1)
            content_lay.addWidget(walter_img_lbl)
            content_lay.addStretch(1)
        else:
            content_lay.addStretch(1)

        content_lay.addWidget(tagline_lbl)
        _BottomRoundedMask(content, 16)

        self._walter_content = content
        self._walter_overlay = _PixelTrickleOverlay(content)
        content.installEventFilter(self)

        lay = QVBoxLayout(page)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(0)
        lay.addWidget(top_bar)
        lay.addWidget(content, 1)

        return page

    def _toggle_walter_advert(self) -> None:
        if self._stack.currentIndex() == 3:
            self._stack.setCurrentIndex(self._advert_prev_index)
        else:
            self._advert_prev_index = self._stack.currentIndex()
            self._stop_auto()
            self._cancel_resume()
            self._stack.setCurrentIndex(3)

    # ------------------------------------------------------------------
    def _toggle_compare_player(self, pnum: str) -> None:
        self._stop_auto()
        self._cancel_resume()
        if pnum in self._compare_selected:
            self._compare_selected.discard(pnum)
        else:
            self._compare_selected.add(pnum)
        self._redraw_compare()
        if self._auto_ever_started:
            self._resume_timer.start()
            self._set_resume_visible(True)

    def _redraw_compare(self) -> None:
        ax = self._compare_ax
        ax.clear()
        ax.set_facecolor("black")
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(axis="both", labelsize=self.FS_TICK, colors="white")

        if not self._compare_selected:
            ax.set_title("Select a player to compare", fontsize=self.FS_TITLE, color="white")
            self._compare_canvas.draw()
            return

        xs = self._rounds
        for pnum in self._ranked:
            if pnum not in self._compare_selected:
                continue
            name = self._player_name(pnum)
            ys = self._cumulative[pnum]
            color = self._player_colors[pnum]
            ax.plot(xs, ys, marker="o", linewidth=4, markersize=10, color=color, label=name)
            ax.annotate(
                f"{name}  {ys[-1]}",
                xy=(xs[-1], ys[-1]),
                xytext=(8, 0), textcoords="offset points",
                va="center", ha="left",
                fontsize=self.FS_TICK, color=color, fontweight="bold",
            )

        ax.set_title("Pizinieren", fontsize=self.FS_TITLE, color="white")
        ax.set_xlabel("Round", fontsize=self.FS_LABEL, color="white")
        ax.set_ylabel("Cumulative Points", fontsize=self.FS_LABEL, color="white")
        # ax.legend(loc="upper left", fontsize=self.FS_LEGEND)
        ax.grid(True, linestyle="--", alpha=0.5, color="white")
        ax.set_xticks(xs)
        self._compare_canvas.draw()

    def _show_frame(self) -> None:
        if self._frame == 0:
            self._stack.setCurrentIndex(1)  # ranking
            self._update_rank_font_size()
        else:
            self._stack.setCurrentIndex(2)  # compare slide
            self._redraw_compare()

    def _reveal_next(self) -> None:
        """Manually reveal the next hidden ranking row (Space key)."""
        if self._stack.currentIndex() != 1:
            return
        if self._rank_reveal < len(self._ranked):
            row = len(self._ranked) - 1 - self._rank_reveal
            self._rank_tbl.setRowHidden(row, False)
            self._rank_reveal += 1

    def _is_auto_running(self) -> bool:
        return (self._auto_timer.isActive() or self._logo_anim is not None
                or self._walter_hold_timer.isActive() or self._walter_overlay.isVisible())

    def _cancel_resume(self) -> None:
        self._resume_timer.stop()
        self._set_resume_visible(False)

    def _resume_auto(self) -> None:
        self._set_resume_visible(False)
        if self._auto_ever_started:
            self._auto_state = 0
            self._auto_show_logo()

    def _toggle_auto(self) -> None:
        if self._is_auto_running():
            self._stop_auto()
            self._cancel_resume()
        else:
            self._cancel_resume()
            self._auto_ever_started = True
            self._auto_state = 0
            self._auto_show_logo()

    def _stop_auto(self) -> None:
        self._auto_timer.stop()
        if self._logo_anim is not None:
            try:
                self._logo_anim.finished.disconnect()
            except Exception:
                pass
            self._logo_anim.stop()
            self._logo_anim = None
        self._logo_effect.setOpacity(1.0)
        self._walter_hold_timer.stop()
        self._walter_overlay.stop()
        self._set_auto_btn_text("Auto")

    def _set_auto_btn_text(self, text: str) -> None:
        self._splash_auto_btn.setText(text)
        self._rank_auto_btn.setText(text)
        self._compare_auto_btn.setText(text)

    def _auto_show_logo(self) -> None:
        self._set_auto_btn_text("Pause")
        self._logo_effect.setOpacity(0.0)
        self._stack.setCurrentIndex(0)

        fade_in = QPropertyAnimation(self._logo_effect, b"opacity", self)
        fade_in.setDuration(self._logo_fade_in_ms)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.InOutQuad)

        fade_out = QPropertyAnimation(self._logo_effect, b"opacity", self)
        fade_out.setDuration(self._logo_fade_out_ms)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self._logo_anim = QSequentialAnimationGroup(self)
        self._logo_anim.addAnimation(fade_in)
        self._logo_anim.addPause(self._logo_hold_ms)
        self._logo_anim.addAnimation(fade_out)
        self._logo_anim.finished.connect(self._auto_next)
        self._logo_anim.start()

    def _auto_show_ranking(self) -> None:
        self._set_auto_btn_text("Pause")
        self._frame = 0
        self._rank_reveal = len(self._ranked)
        for i in range(len(self._ranked)):
            self._rank_tbl.setRowHidden(i, False)
        self._stack.setCurrentIndex(1)
        self._auto_timer.start(self.AUTO_RANKING_MS)

    def _auto_show_compare(self) -> None:
        self._set_auto_btn_text("Pause")
        selected = random.sample(self._ranked, min(2, len(self._ranked)))
        self._compare_selected = set(selected)
        for pnum, btn in self._compare_btns.items():
            btn.setChecked(pnum in self._compare_selected)
        self._frame = self._total_frames - 1
        self._show_frame()
        self._auto_timer.start(self._compare_ms)

    def _auto_show_walter(self) -> None:
        self._set_auto_btn_text("Pause")
        self._walter_overlay.stop()
        self._stack.setCurrentIndex(3)
        self._walter_hold_timer.start(self._walter_hold_ms)

    def _start_walter_pixelout(self) -> None:
        def _after_pixelout() -> None:
            self._auto_timer.start(1000)
        self._walter_overlay.start_pixelout(_after_pixelout)

    def _auto_next(self) -> None:
        self._auto_state = (self._auto_state + 1) % 2
        if self._auto_state == 0:
            self._auto_show_logo()
        else:
            self._auto_show_compare()

    def _user_forward(self) -> None:
        self._stop_auto()
        self._cancel_resume()
        self._go_forward()

    def _user_back(self) -> None:
        self._stop_auto()
        self._cancel_resume()
        self._go_back()

    def _jump_to_logo(self) -> None:
        self._stop_auto()
        self._cancel_resume()
        self._stack.setCurrentIndex(0)

    def _jump_to_ranking(self) -> None:
        self._stop_auto()
        self._cancel_resume()
        if self._stack.currentIndex() == 1:
            self._reveal_next()
        else:
            self._frame = 0
            self._rank_reveal = 0
            for i in range(len(self._ranked)):
                self._rank_tbl.setRowHidden(i, True)
            self._stack.setCurrentIndex(1)

    def _jump_to_compare(self) -> None:
        self._stop_auto()
        self._cancel_resume()
        self._frame = self._total_frames - 1
        self._show_frame()

    def _go_forward(self) -> None:
        if self._skip_splash():
            return
        if self._frame == 0:
            self._frame = 1
            self._show_frame()
        else:
            self._frame += 1
            if self._frame >= self._total_frames:
                self._frame = 0
                self._stack.setCurrentIndex(0)
            else:
                self._show_frame()

    def _go_back(self) -> None:
        if self._skip_splash():
            return
        if self._frame == 0:
            self._frame = self._total_frames - 1
            self._show_frame()
        else:
            self._frame -= 1
            self._show_frame()

    def _exit_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def closeEvent(self, event) -> None:
        self._auto_timer.stop()
        self._resume_timer.stop()
        super().closeEvent(event)



# ----------------------------------------------------------------------
def read_standings(conn, tournament: int) -> tuple[ranking.Standings, list[str]]:
    names = db.players(conn, tournament)
    games = db.games(conn, tournament)
    return ranking.compute(games, names), db.check(conn, tournament)


def open_source(db_path: Path, tournament: int | None):
    """Open the database read-only. Returns (connection, tournament number)."""
    conn = db.open_ro(db_path)
    if tournament is None:
        tournament = db.latest_tournament(conn)
        if tournament is None:
            raise SystemExit(f"No tournaments in {db_path}. Use the data-entry tool first.")
    elif tournament not in db.tournaments(conn):
        raise SystemExit(f"Tournament {tournament} not found in {db_path}.")
    return conn, tournament


class LiveUpdater:
    """Polls the database and pushes new standings into the window.

    SQLite's data_version changes whenever another connection (the data-entry
    tool) commits, so an idle poll is one trivial query. The connection is
    read-only; this class never writes.
    """

    def __init__(self, conn, tournament: int, window: "GraphWindow", interval_ms: int = 1000) -> None:
        self._conn, self._tournament, self._window = conn, tournament, window
        self._version = self._data_version()
        self._base_title = window.windowTitle()
        self._timer = QTimer(window)
        self._timer.timeout.connect(self.poll)
        self._timer.start(interval_ms)

    def _data_version(self) -> int:
        return self._conn.execute("PRAGMA data_version").fetchone()[0]

    def poll(self) -> None:
        try:
            version = self._data_version()
            if version == self._version:
                return
            standings, problems = read_standings(self._conn, self._tournament)
        except Exception as exc:  # e.g. database briefly locked or file replaced - retry next tick
            print(f"live update skipped: {exc}", file=sys.stderr)
            return
        self._version = version
        self._window.setWindowTitle(
            self._base_title + (" - DATA PROBLEMS, ranking may be wrong" if problems else "")
        )
        if problems:
            print("data problems:\n  " + "\n  ".join(problems), file=sys.stderr)
        self._window.update_standings(standings)


def main() -> None:
    parser = argparse.ArgumentParser(description="Tarock presentation window (read-only)")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database (default: %(default)s)")
    parser.add_argument(
        "--tournament", "-t", type=int, default=None, metavar="N",
        help="Tournament number to show. Shows the latest if omitted.",
    )
    parser.add_argument(
        "--speed-auto-mode", "-s", type=float, default=1.0, metavar="X",
        dest="auto_speed",
        help="Auto-mode speed multiplier (2.0 = twice as slow, 0.5 = twice as fast, default 1.0).",
    )
    parser.add_argument(
        "--auto-resume", "-r", type=int, default=180, metavar="SEC",
        dest="auto_resume_s",
        help="Seconds of inactivity on the compare page before auto mode resumes (default 180).",
    )
    args, qt_args = parser.parse_known_args()

    if not _MATPLOTLIB_OK:
        raise SystemExit("matplotlib is required:  pip install matplotlib")

    conn, tournament = open_source(args.db, args.tournament)
    standings, problems = read_standings(conn, tournament)
    if not standings.rows:
        print(f"Tournament {tournament} has no results yet - showing an empty presentation.")

    app = QApplication([sys.argv[0]] + qt_args)
    app.setFont(QFont("Noto Serif"))
    if problems:
        QMessageBox.warning(
            None, "Data problems found",
            "The database has inconsistencies; the shown ranking may be wrong:\n\n" + "\n".join(problems),
        )
    win = GraphWindow(
        standings,
        title=f"{ordinal(tournament)} Pony Tarock Championship",
        auto_speed=args.auto_speed,
        auto_resume_s=args.auto_resume_s,
    )
    win.show()
    updater = LiveUpdater(conn, tournament, win)  # noqa: F841 - kept alive for the timer
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
