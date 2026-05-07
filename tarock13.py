#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PyQt6 application – 4-player Tarock tournament recorder.
"""

from __future__ import annotations

import io
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
)
from PyQt6.QtGui import QIntValidator, QKeySequence, QShortcut, QFont, QColor, QPainterPath, QRegion, QPainter
from PyQt6.QtCore import Qt, QTimer, QRectF, QEvent, QObject
from PyQt6.QtWidgets import QStyledItemDelegate

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
    V_PAD  = 5   # gap above and below the card within the cell height

    def paint(self, painter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        table = self.parent()
        col   = index.column()

        # Draw the full-row background once, from the leftmost column
        if col == 0:
            bg_brush = index.data(Qt.ItemDataRole.BackgroundRole)
            bg_color = bg_brush.color() if bg_brush else QColor("#E8E8E8")
            bg_color.setAlpha(195)

            total_w = sum(table.columnWidth(c) for c in range(table.columnCount()))
            card = QRectF(
                option.rect.x(),
                option.rect.y() + self.V_PAD,
                total_w,
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
        painter.setPen(QColor("#111111"))
        painter.drawText(option.rect, Qt.AlignmentFlag.AlignCenter, text)

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
            painter.setBrush(QColor("#FF0000"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(card, self.RADIUS, self.RADIUS)

        # Draw header label centred
        text = self.model().headerData(
            logical_index, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole
        )
        font = QFont()
        font.setBold(True)
        font.setPointSize(22)
        painter.setFont(font)
        painter.setPen(QColor("white"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(text or ""))
        painter.restore()


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
    INTERVAL_MS = 10_000

    # frame 0     → Qt ranking table (proper emoji, fills screen)
    # frame 1..N  → matplotlib winner-vs-player comparison

    _MEDAL  = {0: "👑", 1: "🥈", 2: "🥉"}
    _ROW_BG = {0: QColor("#FFD700"), 1: QColor("#C0C0C0"), 2: QColor("#CD7F32")}
    _ROW_ALT = (QColor("#F2F2F2"), QColor("#E2E2E2"))

    FS_TITLE  = 36
    FS_LABEL  = 28
    FS_TICK   = 22
    FS_LEGEND = 24

    def __init__(self, entries: list[dict], mapping: dict[int, str]) -> None:
        super().__init__()
        self.setWindowTitle("Tournament Results")
        self.resize(960, 700)

        self._mapping = mapping
        self._rounds  = sorted({e["round"] for e in entries})
        self._frame   = 0

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
        self._winner = self._ranked[0]
        self._others = [p for p in self._ranked if p != self._winner]
        self._total_frames = 1 + len(self._others)

        # ---- Pause button (shared across both pages) ----
        self._pause_btn = QPushButton("Pause")
        self._pause_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._pause_btn.clicked.connect(self._toggle_pause)

        # ---- Page 0: Qt ranking table ----
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_ranking_page())

        # ---- Page 1: matplotlib canvas ----
        graph_page = QWidget()
        graph_page.setStyleSheet("background-color: #0d0d1a;")
        self._fig = Figure(tight_layout=True)
        self._canvas = FigureCanvas(self._fig)
        self._ax = self._fig.add_subplot(111)

        btn_style = (
            "font-size: 40px; padding: 12px 40px; color: white;"
            " background-color: black; border-radius: 10px;"
        )
        back_btn = QPushButton("◀")
        back_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        back_btn.setStyleSheet(btn_style)
        back_btn.clicked.connect(self._go_back)

        fwd_btn = QPushButton("▶")
        fwd_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        fwd_btn.setStyleSheet(btn_style)
        fwd_btn.clicked.connect(self._go_forward)

        self._pause_btn.setStyleSheet(btn_style)

        self._graph_fs_btn = QPushButton("⛶ Fullscreen")
        self._graph_fs_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._graph_fs_btn.setStyleSheet(btn_style)
        self._graph_fs_btn.clicked.connect(self._toggle_fullscreen)

        graph_top_bar = QWidget()
        graph_top_bar.setStyleSheet(
            "background-color: #FF0000; border-radius: 16px 16px 0 0;"
        )
        graph_header_lbl = QLabel("Pony Tarock Championship")
        graph_header_lbl.setStyleSheet(
            "color: white; font-size: 36px; font-weight: bold;"
            " background-color: transparent;"
        )

        graph_top_bar_layout = QHBoxLayout(graph_top_bar)
        graph_top_bar_layout.setContentsMargins(24, 8, 12, 8)
        graph_top_bar_layout.addWidget(graph_header_lbl)
        graph_top_bar_layout.addStretch(1)
        graph_top_bar_layout.addWidget(back_btn)
        graph_top_bar_layout.addWidget(fwd_btn)
        graph_top_bar_layout.addWidget(self._pause_btn)
        graph_top_bar_layout.addWidget(self._graph_fs_btn)

        self._canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        canvas_wrapper = QWidget()
        canvas_wrapper.setStyleSheet(
            "border: 2px solid #FF0000; border-top: none;"
            " border-radius: 0 0 16px 16px;"
        )
        canvas_layout = QVBoxLayout(canvas_wrapper)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.addWidget(self._canvas)

        glay = QVBoxLayout(graph_page)
        glay.setContentsMargins(24, 24, 24, 24)
        glay.setSpacing(0)
        glay.addWidget(graph_top_bar, 0)
        glay.addWidget(canvas_wrapper, 1)
        self._stack.addWidget(graph_page)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self._stack)

        self._stack.setCurrentIndex(0)

        QShortcut(QKeySequence(Qt.Key.Key_Left),  self).activated.connect(self._go_back)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self).activated.connect(self._go_forward)
        QShortcut(QKeySequence(Qt.Key.Key_F11),   self).activated.connect(self._toggle_fullscreen)

        self._timer = QTimer(self)
        self._timer.setInterval(self.INTERVAL_MS)
        self._timer.timeout.connect(self._advance)
        self._timer.start()

    # ------------------------------------------------------------------
    def _player_name(self, pnum: str) -> str:
        return self._mapping.get(int(pnum), pnum) if pnum.isdigit() else pnum

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

        bold_font = QFont()
        bold_font.setBold(True)
        bold_font.setPointSize(22)
        normal_font = QFont()
        normal_font.setPointSize(22)

        for i, pnum in enumerate(self._ranked):
            medal    = self._MEDAL.get(i, "")
            rank_str = f"{medal}  {i + 1}." if medal else f"    {i + 1}."
            name     = self._player_name(pnum)
            total    = str(self._cumulative[pnum][-1])

            for col, text in enumerate([rank_str, name, total]):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if i in self._ROW_BG:
                    item.setBackground(self._ROW_BG[i])
                    item.setFont(bold_font)
                else:
                    item.setBackground(self._ROW_ALT[i % 2])
                    item.setFont(normal_font)
                tbl.setItem(i, col, item)

        btn_style = (
            "font-size: 40px; padding: 12px 40px; color: white;"
            " background-color: black; border-radius: 10px;"
        )

        rank_back_btn = QPushButton("◀")
        rank_back_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        rank_back_btn.setStyleSheet(btn_style)
        rank_back_btn.clicked.connect(self._go_back)

        rank_fwd_btn = QPushButton("▶")
        rank_fwd_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        rank_fwd_btn.setStyleSheet(btn_style)
        rank_fwd_btn.clicked.connect(self._go_forward)

        pause_btn = QPushButton("Pause")
        pause_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        pause_btn.clicked.connect(self._toggle_pause)
        pause_btn.setStyleSheet(btn_style)
        self._rank_pause_btn = pause_btn

        self._rank_fs_btn = QPushButton("⛶ Fullscreen")
        self._rank_fs_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._rank_fs_btn.setStyleSheet(btn_style)
        self._rank_fs_btn.clicked.connect(self._toggle_fullscreen)

        top_bar_widget = QWidget()
        top_bar_widget.setStyleSheet(
            "background-color: #FF0000; border-radius: 16px 16px 0 0;"
        )
        header_lbl = QLabel("Pony Tarock Championship")
        header_lbl.setStyleSheet(
            "color: white; font-size: 36px; font-weight: bold;"
            " background-color: transparent;"
        )

        top_bar = QHBoxLayout(top_bar_widget)
        top_bar.setContentsMargins(24, 8, 12, 8)
        top_bar.addWidget(header_lbl)
        top_bar.addStretch(1)
        top_bar.addWidget(rank_back_btn)
        top_bar.addWidget(rank_fwd_btn)
        top_bar.addWidget(pause_btn)
        top_bar.addWidget(self._rank_fs_btn)

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

    # ------------------------------------------------------------------
    def _draw_comparison(self, idx: int) -> None:
        self._ax.clear()
        xs = self._rounds

        winner_name = self._player_name(self._winner)
        winner_ys   = self._cumulative[self._winner]
        other       = self._others[idx]
        other_name  = self._player_name(other)
        other_ys    = self._cumulative[other]

        self._ax.plot(xs, other_ys, marker="o", color="steelblue",
                      linewidth=5, markersize=14, label=other_name)
        self._ax.fill_between(xs, winner_ys, other_ys, alpha=0.12, color="steelblue")
        self._ax.plot(xs, winner_ys, marker="o", color="gold",
                      linewidth=6, markersize=16, label=f"{winner_name} [Winner]")

        self._ax.set_title(
            f"[Winner] {winner_name}  vs  {other_name}"
            f"  ({idx + 1} / {len(self._others)})",
            fontsize=self.FS_TITLE,
        )
        self._ax.set_xlabel("Round", fontsize=self.FS_LABEL)
        self._ax.set_ylabel("Cumulative Points", fontsize=self.FS_LABEL)
        self._ax.legend(loc="upper left", fontsize=self.FS_LEGEND)
        self._ax.grid(True, linestyle="--", alpha=0.5)
        self._ax.set_xticks(xs)
        self._ax.tick_params(axis="both", labelsize=self.FS_TICK)
        self._canvas.draw()

    # ------------------------------------------------------------------
    def _show_frame(self) -> None:
        if self._frame == 0:
            self._stack.setCurrentIndex(0)
        else:
            self._stack.setCurrentIndex(1)
            self._draw_comparison(self._frame - 1)

    def _advance(self) -> None:
        self._frame = (self._frame + 1) % self._total_frames
        self._show_frame()

    def _go_forward(self) -> None:
        self._frame = (self._frame + 1) % self._total_frames
        self._show_frame()

    def _go_back(self) -> None:
        self._frame = (self._frame - 1) % self._total_frames
        self._show_frame()

    def _toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self._graph_fs_btn.setText("⛶ Fullscreen")
            self._rank_fs_btn.setText("⛶ Fullscreen")
        else:
            self.showFullScreen()
            self._graph_fs_btn.setText("⛶ Windowed")
            self._rank_fs_btn.setText("⛶ Windowed")

    def _toggle_pause(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
            self._pause_btn.setText("Resume")
            self._rank_pause_btn.setText("Resume")
        else:
            self._timer.start()
            self._pause_btn.setText("Pause")
            self._rank_pause_btn.setText("Pause")

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)


class MainWindow(QWidget):
    CSV_FILE = Path("result.csv")
    MAP_FILE = Path("player_numbers.csv")

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Tarock Tournament Manager")

        font = QFont()
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
        outer_layout = QHBoxLayout()
        outer_layout.addWidget(self._build_left_panel())
        outer_layout.addWidget(self._build_right_panel())
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
            left_grid.addWidget(num_le, row, 0)

            name_le = QLineEdit()
            name_le.setPlaceholderText(f"Name {row + 1}")
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
        self._graph_window = GraphWindow(self.entries, self.mapping)
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
            with open("ranking.csv", "w", encoding="utf-8") as f:
                f.write(ranking_csv)
        except OSError as exc:
            self._set_status(f"Could not write ranking.csv: {exc}", error=True)
            return

        self.output_display.setPlainText("\n".join(display_lines))
        self._set_status("Ranking generated – also saved to ranking.csv.")


# ----------------------------------------------------------------------
def main() -> None:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1000, 600)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
