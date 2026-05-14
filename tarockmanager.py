#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PyQt6 application – 4-player Tarock tournament recorder.
"""

from __future__ import annotations

import argparse
import io
import random
import sys
import csv
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QPushButton,
    QTextEdit,
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
from PyQt6.QtGui import QIntValidator, QKeySequence, QShortcut, QFont, QColor, QPainterPath, QRegion, QPainter
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

    def __init__(self, entries: list[dict], mapping: dict[int, str], title: str = "Pony Tarock Championship", auto_speed: float = 1.0, auto_resume_s: int = 180) -> None:
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

        self._mapping = mapping
        self._rounds  = sorted({e["round"] for e in entries})
        self._frame       = 0
        self._rank_reveal = 0   # how many ranking rows are currently visible

        # Accumulate points per player per round
        per_round: dict[str, dict[int, int]] = {}
        for entry in entries:
            r = entry["round"]
            for person in entry["people"]:
                pnum = person["playernumber"]
                bucket = per_round.setdefault(pnum, {})
                bucket[r] = bucket.get(r, 0) + person["points"]

        players = sorted(per_round.keys())

        # Precompute cumulative totals: _cumulative[player][round_index]
        self._cumulative: dict[str, list[int]] = {}
        for pnum in players:
            cum, row = 0, []
            for r in self._rounds:
                cum += per_round[pnum].get(r, 0)
                row.append(cum)
            self._cumulative[pnum] = row

        self._ranked = sorted(players, key=lambda p: -self._cumulative[p][-1])
        self._total_frames = 2  # frame 0: ranking, frame 1: compare

        self._player_colors: dict[str, str] = {
            pnum: self.PLAYER_COLORS[i % len(self.PLAYER_COLORS)]
            for i, pnum in enumerate(self._ranked)
        }
        self._compare_selected: set[str] = set()

        self._resume_labels: list[QLabel] = []
        self._splash_content: QWidget | None = None
        self._splash_logo_lbl: QLabel | None = None

        # ---- Page 0: Splash ---- Page 1: Ranking ---- Page 2: Compare ----
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_splash_page())        # 0
        self._stack.addWidget(self._build_ranking_page())       # 1
        self._stack.addWidget(self._build_compare_page())       # 2

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

    # ------------------------------------------------------------------
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
        self._auto_state = 1
        self._auto_show_compare()

    # ------------------------------------------------------------------
    def _player_name(self, pnum: str) -> str:
        return self._mapping.get(int(pnum), pnum) if pnum.isdigit() else pnum

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

        last_idx = len(self._ranked) - 1
        for i, pnum in enumerate(self._ranked):
            if i == last_idx:
                medal = self._LAST_MEDAL
            else:
                medal = self._MEDAL.get(i, "")
            rank_str = f"{medal}  {i + 1}." if medal else f"    {i + 1}."
            name     = self._player_name(pnum)
            total    = str(self._cumulative[pnum][-1])

            for col, text in enumerate([rank_str, name, total]):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if i in self._ROW_BG:
                    item.setBackground(self._ROW_BG[i])
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
        for rank, pnum in enumerate(self._ranked, start=1):
            name = self._player_name(pnum)
            color = self._player_colors[pnum]
            btn = QPushButton(f"{rank}. {name}")
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(f"""
                QPushButton {{
                    font-size: 21px;
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
        return self._auto_timer.isActive() or self._logo_anim is not None

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


class MainWindow(QWidget):
    def __init__(self, tournament_dir: Path, auto_speed: float = 1.0, auto_resume_s: int = 180) -> None:
        super().__init__()
        self._auto_speed = auto_speed
        self._auto_resume_s = auto_resume_s
        self.CSV_FILE      = tournament_dir / "result.csv"
        self.MAP_FILE      = tournament_dir / "player_numbers.csv"
        self._ranking_file = tournament_dir / "ranking.csv"
        num = int(tournament_dir.name) if tournament_dir.name.isdigit() else 0
        self._tournament_title = f"{_ordinal(num)} Pony Tarock Championship"
        self.setWindowTitle(f"Tarock Tournament Manager — {tournament_dir.name}")

        font = QFont("Noto Serif")
        font.setPointSize(18)
        self.setFont(font)

        self.entries: list[dict] = []
        self.current_index: int = -1
        self._graph_window: GraphWindow | None = None

        self._build_ui()
        self._load_mapping_from_file()
        self._load_from_file()

        if self.entries:
            self.current_index = 0
            self._populate_form(self.entries[0])
            self._display_current_card()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        header = QLabel(self._tournament_title)
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet(
            "font-size: 28px; font-weight: bold; color: white;"
            " background-color: #CC0000; padding: 10px; border-radius: 8px;"
        )

        panels = QHBoxLayout()
        panels.addWidget(self._build_left_panel())
        panels.addWidget(self._build_right_panel())

        outer_layout = QVBoxLayout()
        outer_layout.setSpacing(8)
        outer_layout.addWidget(header)
        outer_layout.addLayout(panels)
        self.setLayout(outer_layout)

    def _build_left_panel(self) -> QWidget:
        container = QWidget()

        grid_widget = QWidget()
        left_grid = QGridLayout()
        left_grid.setSpacing(4)

        self.mapping_edits: list[tuple[QLineEdit, QLineEdit]] = []
        self.mapping: dict[int, str] = {}

        for row in range(20):
            num_le = QLineEdit()
            num_le.setPlaceholderText(f"Player № {row + 1}")
            num_le.setValidator(QIntValidator(0, 9999))
            num_le.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            left_grid.addWidget(num_le, row, 0)

            name_le = QLineEdit()
            name_le.setPlaceholderText(f"Name {row + 1}")
            name_le.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            left_grid.addWidget(name_le, row, 1)

            self.mapping_edits.append((num_le, name_le))

        grid_widget.setLayout(left_grid)

        scroll = QScrollArea()
        scroll.setWidget(grid_widget)
        scroll.setWidgetResizable(True)

        save_btn = QPushButton("Save Mapping")
        save_btn.clicked.connect(self._save_mapping_to_file)

        load_btn = QPushButton("Load Mapping")
        load_btn.clicked.connect(self._load_mapping_from_file)

        layout = QVBoxLayout()
        layout.addWidget(scroll)
        layout.addWidget(save_btn)
        layout.addWidget(load_btn)
        container.setLayout(layout)
        return container

    def _build_right_panel(self) -> QWidget:
        widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.addLayout(self._build_form())
        main_layout.addSpacing(30)

        self.status_lbl = QLabel()
        main_layout.addWidget(self.status_lbl)
        main_layout.addLayout(self._build_buttons())

        self.output_display = QTextEdit()
        self.output_display.setReadOnly(True)
        self.output_display.setPlaceholderText("Current card will appear here…")
        main_layout.addWidget(self.output_display)

        widget.setLayout(main_layout)
        return widget

    def _build_form(self) -> QGridLayout:
        form_layout = QGridLayout()
        for col in range(4):
            form_layout.setColumnStretch(col, 1)

        self.round_spin = QSpinBox()
        self.round_spin.setRange(1, 1000)
        self.round_spin.setValue(1)
        form_layout.addWidget(QLabel("Round:"), 0, 0)
        form_layout.addWidget(self.round_spin, 0, 1)

        self.table_edit = QLineEdit()
        self.table_edit.setPlaceholderText("e.g. 12")
        self.table_edit.setValidator(QIntValidator(1, 9999))
        form_layout.addWidget(QLabel("Table Number:"), 0, 2)
        form_layout.addWidget(self.table_edit, 0, 3)

        self.player_number_edits: list[QLineEdit] = []
        self.points_spins: list[QSpinBox] = []

        for i in range(4):
            player_num_le = QLineEdit()
            player_num_le.setPlaceholderText(f"Player Number {i + 1}")
            points_sb = QSpinBox()
            points_sb.setRange(-100, 100)
            points_sb.setValue(0)

            self.player_number_edits.append(player_num_le)
            self.points_spins.append(points_sb)

            form_layout.addWidget(player_num_le, 1, i)
            form_layout.addWidget(
                QLabel("Points:"), 2, i, alignment=Qt.AlignmentFlag.AlignCenter
            )
            form_layout.addWidget(points_sb, 3, i)

        return form_layout

    def _build_buttons(self) -> QHBoxLayout:
        submit_btn = QPushButton("Submit")
        change_btn = QPushButton("Change")
        prev_btn = QPushButton("Previous")
        next_btn = QPushButton("Next")
        clear_btn = QPushButton("Clear")
        delete_btn = QPushButton("Delete")
        sum_btn = QPushButton("Sum / Rank")
        graph_btn = QPushButton("Graph")

        submit_btn.clicked.connect(self._on_submit)
        change_btn.clicked.connect(self._on_change)
        prev_btn.clicked.connect(self._show_previous)
        next_btn.clicked.connect(self._show_next)
        clear_btn.clicked.connect(self._clear_fields)
        delete_btn.clicked.connect(self._delete_current)
        sum_btn.clicked.connect(self._on_sum_and_rank)
        graph_btn.clicked.connect(self._on_show_graph)

        for btn in (clear_btn, delete_btn, prev_btn, next_btn):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Ctrl+C intentionally omitted — conflicts with system copy shortcut
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._on_submit)
        QShortcut(QKeySequence("Meta+S"), self).activated.connect(self._on_submit)
        QShortcut(QKeySequence("Ctrl+E"), self).activated.connect(self._on_change)
        QShortcut(QKeySequence("Ctrl+P"), self).activated.connect(self._show_previous)
        QShortcut(QKeySequence("Meta+P"), self).activated.connect(self._show_previous)
        QShortcut(QKeySequence("Ctrl+N"), self).activated.connect(self._show_next)
        QShortcut(QKeySequence("Meta+N"), self).activated.connect(self._show_next)

        layout = QHBoxLayout()
        layout.addWidget(submit_btn)
        layout.addWidget(change_btn)
        layout.addWidget(prev_btn)
        layout.addWidget(next_btn)
        layout.addStretch()
        layout.addWidget(sum_btn)
        layout.addWidget(graph_btn)
        layout.addWidget(clear_btn)
        layout.addWidget(delete_btn)
        return layout

    # ------------------------------------------------------------------
    def _set_status(self, text: str, error: bool = False) -> None:
        color = "red" if error else "green"
        self.status_lbl.setStyleSheet(f"color: {color}")
        self.status_lbl.setText(text)

    def _clear_status(self) -> None:
        self.status_lbl.setStyleSheet("")
        self.status_lbl.clear()

    # ------------------------------------------------------------------
    def _save_mapping_to_file(self) -> None:
        mapping = {}
        for num_le, name_le in self.mapping_edits:
            n_text = num_le.text().strip()
            p_text = name_le.text().strip()
            if not n_text or not p_text:
                continue
            try:
                num = int(n_text)
            except ValueError:
                continue
            mapping[num] = p_text

        self.mapping = mapping
        try:
            with open(self.MAP_FILE, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Player_Number", "Player_Name"])
                for num, name in sorted(mapping.items()):
                    writer.writerow([num, name])
            self._set_status(
                f"Mapping saved – {len(mapping)} pairs written to player_numbers.csv"
            )
        except OSError as exc:
            self._set_status(f"Could not write player_numbers.csv: {exc}", error=True)

    # ------------------------------------------------------------------
    def _load_mapping_from_file(self) -> None:
        if not self.MAP_FILE.exists():
            return

        mapping: dict[int, str] = {}
        slot = 0
        try:
            with open(self.MAP_FILE, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)  # skip header
                for row in reader:
                    if len(row) < 2:
                        continue
                    num_str, name = row[0].strip(), row[1].strip()
                    try:
                        num = int(num_str)
                    except ValueError:
                        continue

                    mapping[num] = name

                    if slot < len(self.mapping_edits):
                        num_le, name_le = self.mapping_edits[slot]
                        num_le.setText(str(num))
                        name_le.setText(name)
                        slot += 1

            self.mapping = mapping
        except Exception as exc:
            self._set_status(f"Could not read player_numbers.csv: {exc}", error=True)

    # ------------------------------------------------------------------
    def _build_entry(self) -> dict | None:
        """Validate form inputs and return an entry dict, or None on failure."""
        table_text = self.table_edit.text().strip()
        if not table_text.isdigit():
            self._set_status("Table number must be an integer.", error=True)
            return None

        player_numbers = [le.text().strip() for le in self.player_number_edits]
        if any(not n for n in player_numbers):
            self._set_status("All four player number fields must be filled.", error=True)
            return None

        if len(set(player_numbers)) != 4:
            self._set_status("All four player numbers must be unique.", error=True)
            return None

        points_total = sum(sb.value() for sb in self.points_spins)
        if points_total != 0:
            self._set_status(
                f"Points must sum to 0 (current sum: {points_total:+d}).", error=True
            )
            return None

        return {
            "table": int(table_text),
            "round": self.round_spin.value(),
            "people": [
                {"playernumber": num, "points": sb.value()}
                for num, sb in zip(player_numbers, self.points_spins)
            ],
        }

    # ------------------------------------------------------------------
    def _clear_fields(self) -> None:
        self.table_edit.clear()
        self.round_spin.setValue(1)
        for le, sb in zip(self.player_number_edits, self.points_spins):
            le.clear()
            sb.setValue(0)
        self.output_display.clear()
        self._clear_status()

    # ------------------------------------------------------------------
    def _on_submit(self) -> None:
        entry = self._build_entry()
        if entry is None:
            return
        for existing in self.entries:
            if existing["table"] == entry["table"] and existing["round"] == entry["round"]:
                self._set_status(
                    f"Table {entry['table']} already submitted for round {entry['round']} — use Change to update it.",
                    error=True,
                )
                return
        self.entries.append(entry)
        self.current_index = len(self.entries) - 1
        self._populate_form(entry)
        self._display_current_card()
        self._save_to_file()

    # ------------------------------------------------------------------
    def _on_change(self) -> None:
        if self.current_index == -1:
            self._set_status("No entry selected to change.", error=True)
            return
        entry = self._build_entry()
        if entry is None:
            return
        self.entries[self.current_index] = entry
        self._display_current_card()
        self._save_to_file()

    # ------------------------------------------------------------------
    def _show_previous(self) -> None:
        if not self.entries:
            self._set_status("No entries stored yet.", error=True)
            return
        if self.current_index <= 0:
            self._set_status("Already at the first entry.", error=True)
            return
        self.current_index -= 1
        self._populate_form(self.entries[self.current_index])
        self._display_current_card()

    # ------------------------------------------------------------------
    def _show_next(self) -> None:
        if not self.entries:
            self._set_status("No entries stored yet.", error=True)
            return
        if self.current_index >= len(self.entries) - 1:
            self._set_status("Already at the last entry.", error=True)
            return
        self.current_index += 1
        self._populate_form(self.entries[self.current_index])
        self._display_current_card()

    # ------------------------------------------------------------------
    def _delete_current(self) -> None:
        if not self.entries:
            self._set_status("No entries to delete.", error=True)
            return

        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Delete entry #{self.current_index + 1}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        del self.entries[self.current_index]

        if not self.entries:
            self.current_index = -1
            self._clear_fields()
            self._set_status("All entries deleted.")
        else:
            if self.current_index >= len(self.entries):
                self.current_index = len(self.entries) - 1
            self._populate_form(self.entries[self.current_index])
            self._display_current_card()

        self._save_to_file()

    # ------------------------------------------------------------------
    def _display_current_card(self) -> None:
        if self.current_index == -1 or not self.entries:
            self.output_display.clear()
            return

        entry = self.entries[self.current_index]
        lines = [
            f"Entry {self.current_index + 1} of {len(self.entries)}",
            f"Table: {entry['table']}",
            f"Round: {entry['round']}",
        ]
        for person in entry["people"]:
            pnum = person["playernumber"]
            name = self.mapping.get(int(pnum), pnum) if pnum.isdigit() else pnum
            lines.append(f"{name} – Points: {person['points']}")
        self.output_display.setPlainText("\n".join(lines))
        self._clear_status()

    # ------------------------------------------------------------------
    def _populate_form(self, entry: dict) -> None:
        self.table_edit.setText(str(entry["table"]))
        self.round_spin.setValue(entry["round"])
        for le, sb, person in zip(
            self.player_number_edits, self.points_spins, entry["people"]
        ):
            le.setText(person["playernumber"])
            sb.setValue(person["points"])

    # ------------------------------------------------------------------
    def _entries_to_csv(self) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(
            ["Table", "Round"]
            + [col for i in range(4) for col in (f"Player_Number{i+1}", f"Points{i+1}")]
        )
        for entry in self.entries:
            row = [entry["table"], entry["round"]]
            for person in entry["people"]:
                row.extend([person["playernumber"], person["points"]])
            writer.writerow(row)
        return buf.getvalue()

    # ------------------------------------------------------------------
    def _save_to_file(self) -> None:
        csv_text = self._entries_to_csv()
        if csv_text:
            print(csv_text, flush=True)
            try:
                with open(self.CSV_FILE, "w", newline="", encoding="utf-8") as f:
                    f.write(csv_text)
            except OSError as exc:
                self._set_status(f"Failed to write {self.CSV_FILE}: {exc}", error=True)

    # ------------------------------------------------------------------
    def _load_from_file(self) -> None:
        if not self.CSV_FILE.exists():
            return
        try:
            with open(self.CSV_FILE, newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
            if len(rows) < 2:
                return

            for row in rows[1:]:
                table = int(row[0])
                round_ = int(row[1])
                people = []
                for i in range(4):
                    name = row[2 + 2 * i]
                    points = int(row[3 + 2 * i])
                    people.append({"playernumber": name, "points": points})
                self.entries.append({"table": table, "round": round_, "people": people})
        except Exception as exc:
            self._set_status(f"Could not read {self.CSV_FILE}: {exc}", error=True)

    # ------------------------------------------------------------------
    def _on_show_graph(self) -> None:
        if not _MATPLOTLIB_OK:
            QMessageBox.warning(
                self,
                "Missing dependency",
                "matplotlib is required for the graph.\n\nInstall it with:\n  pip install matplotlib",
            )
            return
        if not self.entries:
            self._set_status("No entries to graph.", error=True)
            return
        self._graph_window = GraphWindow(self.entries, self.mapping, title=self._tournament_title, auto_speed=self._auto_speed, auto_resume_s=self._auto_resume_s)
        self._graph_window.show()

    # ------------------------------------------------------------------
    def _on_sum_and_rank(self) -> None:
        if not self.entries:
            self._set_status("No entries to rank.", error=True)
            return

        totals: dict[str, int] = {}
        for entry in self.entries:
            for person in entry["people"]:
                pnum = person["playernumber"]
                totals[pnum] = totals.get(pnum, 0) + person["points"]

        sorted_totals = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))

        csv_lines = ["Rank,Player_Number,Player_Name,Total_Points"]
        display_lines = [
            "=== Ranking ===",
            f"{'Rank':<6}{'Number':<10}{'Name':<20}Points",
            "-" * 44,
        ]
        for rank, (pnum, total) in enumerate(sorted_totals, start=1):
            name = self.mapping.get(int(pnum), pnum) if pnum.isdigit() else pnum
            csv_lines.append(f"{rank},{pnum},{name},{total}")
            display_lines.append(f"{rank:<6}{pnum:<10}{name:<20}{total}")

        ranking_csv = "\n".join(csv_lines)
        print(ranking_csv, flush=True)

        try:
            with open(self._ranking_file, "w", encoding="utf-8") as f:
                f.write(ranking_csv)
        except OSError as exc:
            self._set_status(f"Could not write {self._ranking_file}: {exc}", error=True)
            return

        self.output_display.setPlainText("\n".join(display_lines))
        self._set_status(f"Ranking generated – also saved to {self._ranking_file}.")


# ----------------------------------------------------------------------
def _ordinal(n: int) -> str:
    suffix = "th" if 11 <= (n % 100) <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _resolve_tournament_dir(num: int | None) -> Path:
    base = Path("tournaments")
    base.mkdir(exist_ok=True)
    if num is not None:
        d = base / str(num)
        d.mkdir(exist_ok=True)
        return d
    candidates = [
        int(p.name) for p in base.iterdir()
        if p.is_dir() and p.name.isdigit()
    ]
    d = base / str(max(candidates)) if candidates else base / "1"
    d.mkdir(exist_ok=True)
    return d


def main() -> None:
    parser = argparse.ArgumentParser(description="Tarock Tournament Manager")
    parser.add_argument(
        "--tournament", "-t", type=int, default=None, metavar="N",
        help="Tournament number to open (e.g. 23). Opens the latest if omitted.",
    )
    parser.add_argument(
        "--speed-auto-mode", "-s", type=float, default=1.0, metavar="X",
        dest="auto_speed",
        help="Auto-mode speed multiplier (2.0 = twice as slow, 0.5 = twice as fast, default 1.0).",
    )
    parser.add_argument(
        "--auto-resume", "-r", type=int, default=180, metavar="SEC",
        dest="auto_resume_s",
        help="Seconds of inactivity on the compare page before auto mode resumes (default 120).",
    )
    args, qt_args = parser.parse_known_args()

    tournament_dir = _resolve_tournament_dir(args.tournament)

    app = QApplication([sys.argv[0]] + qt_args)
    app.setFont(QFont("Noto Serif"))
    win = MainWindow(tournament_dir=tournament_dir, auto_speed=args.auto_speed, auto_resume_s=args.auto_resume_s)
    win.resize(1000, 600)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
