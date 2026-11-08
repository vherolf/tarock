"""The four pages of the presentation, one class each, plus the header bar they share.

Pages know how to draw themselves and expose a small API (+ signals for user input).
They do not know about auto mode or navigation - GraphWindow wires that up.
"""
from __future__ import annotations

import io

import qrcode
from PyQt6.QtCore import (
    QEasingCurve, QEvent, QPropertyAnimation, QSequentialAnimationGroup, Qt, pyqtSignal,
)
from PyQt6.QtGui import QColor, QFont, QImage, QPixmap
from PyQt6.QtWidgets import (
    QGraphicsOpacityEffect, QHBoxLayout, QHeaderView, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from tarock_core.paths import RESOURCE_ROOT

from .viewmodel import View
from .widgets import BottomRoundedMask, PixelTrickleOverlay, RoundedHeader, RoundedRowDelegate, TopRoundedMask

try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.figure import Figure
    MATPLOTLIB_OK = True
except ImportError:  # the window refuses to start without it, see presenter.py
    MATPLOTLIB_OK = False

_BTN_STYLE = (
    "font-size: 36px; padding: 12px 40px; color: #FF0000;"
    " background-color: white; border-radius: 10px;"
)
_PAGE_STYLE = "background-color: #0d0d1a;"


def _nav_button(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.setStyleSheet(_BTN_STYLE)
    return btn


class NavBar(QWidget):
    """Red header bar: title + Logo / Compare / Auto / Ranking buttons."""

    logo = pyqtSignal()
    compare = pyqtSignal()
    ranking = pyqtSignal()
    auto = pyqtSignal()

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "background-color: #FF0000;"
            " border-top-left-radius: 16px; border-top-right-radius: 16px;"
        )
        header = QLabel(title)
        header.setStyleSheet(
            "color: white; font-size: 36px; font-weight: bold; background-color: transparent;"
        )

        logo_btn, compare_btn, ranking_btn = _nav_button("Logo"), _nav_button("Compare"), _nav_button("Ranking")
        logo_btn.clicked.connect(self.logo)
        compare_btn.clicked.connect(self.compare)
        ranking_btn.clicked.connect(self.ranking)

        # Auto button with a small "(autoresume)" hint underneath
        self._auto_btn = _nav_button("Auto")
        self._auto_btn.clicked.connect(self.auto)
        self._resume_lbl = QLabel("(autoresume)")
        self._resume_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._resume_lbl.setStyleSheet("color: white; font-size: 20px; background: transparent;")
        self._resume_lbl.setVisible(False)
        auto_box = QWidget()
        auto_box.setStyleSheet("background: transparent;")
        auto_lay = QVBoxLayout(auto_box)
        auto_lay.setContentsMargins(0, 0, 0, 0)
        auto_lay.setSpacing(2)
        auto_lay.addWidget(self._auto_btn)
        auto_lay.addWidget(self._resume_lbl)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 8, 12, 8)
        lay.addWidget(header)
        lay.addStretch(1)
        lay.addWidget(logo_btn)
        lay.addWidget(compare_btn)
        lay.addWidget(auto_box)
        lay.addWidget(ranking_btn)
        TopRoundedMask(self, 16)

    def set_auto_text(self, text: str) -> None:
        self._auto_btn.setText(text)

    def set_resume_visible(self, show: bool) -> None:
        self._resume_lbl.setVisible(show)


class _Page(QWidget):
    """Common frame: dark page with the nav bar on top."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_PAGE_STYLE)
        self.nav = NavBar(title)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(24, 24, 24, 24)
        self._lay.setSpacing(0)
        self._lay.addWidget(self.nav)


# ----------------------------------------------------------------------------- splash
class SplashPage(_Page):
    """The red "Café Pony" logo page with a fade in / hold / fade out animation."""

    pressed = pyqtSignal()

    def __init__(self, title: str) -> None:
        super().__init__(title)
        content = QWidget()
        content.setObjectName("splashContent")
        content.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        content.setStyleSheet("QWidget#splashContent { background-color: #FF0000; }")

        self._logo = QLabel("Café Pony")
        self._logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._logo.setStyleSheet(
            "color: white; font-size: 280px; font-weight: bold; background: transparent; border: none;"
        )
        self._effect = QGraphicsOpacityEffect(self._logo)
        self._effect.setOpacity(1.0)
        self._logo.setGraphicsEffect(self._effect)
        QVBoxLayout(content).addWidget(self._logo)
        BottomRoundedMask(content, 16)

        self._content = content
        content.installEventFilter(self)
        self._logo.installEventFilter(self)
        self._anim: QSequentialAnimationGroup | None = None

        self._lay.addWidget(content, 1)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress and obj in (self._content, self._logo):
            self.pressed.emit()
        return False

    def play_fade(self, fade_in_ms: int, hold_ms: int, fade_out_ms: int, on_finished) -> None:
        self.stop_fade()
        self._effect.setOpacity(0.0)

        fade_in = QPropertyAnimation(self._effect, b"opacity", self)
        fade_in.setDuration(fade_in_ms)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.InOutQuad)

        fade_out = QPropertyAnimation(self._effect, b"opacity", self)
        fade_out.setDuration(fade_out_ms)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.InOutQuad)

        self._anim = QSequentialAnimationGroup(self)
        self._anim.addAnimation(fade_in)
        self._anim.addPause(hold_ms)
        self._anim.addAnimation(fade_out)
        self._anim.finished.connect(on_finished)
        self._anim.start()

    def stop_fade(self) -> None:
        """Stop the animation (without calling its finish callback) and show the logo fully."""
        if self._anim is not None:
            try:
                self._anim.finished.disconnect()
            except TypeError:
                pass
            self._anim.stop()
            self._anim.deleteLater()   # otherwise one finished animation piles up per auto-mode cycle
            self._anim = None
        self._effect.setOpacity(1.0)


# --------------------------------------------------------------------------- ranking
class RankingPage(_Page):
    """Ranking table whose rows are revealed one by one, last place first."""

    MEDAL = {0: "👑", 1: "🥈", 2: "🥉", 4: "🍈"}   # by rank - 1
    LAST_MEDAL = "🌭"
    ROW_BG = {0: QColor("#FFD700"), 1: QColor("#C0C0C0"), 2: QColor("#CD7F32")}

    def __init__(self, title: str, view: View) -> None:
        super().__init__(title)
        players = view.players
        tbl = QTableWidget(len(players), 3)
        tbl.setHorizontalHeader(RoundedHeader(tbl))
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
        tbl.setItemDelegate(RoundedRowDelegate(tbl))

        item_font = QFont("Noto Serif")
        item_font.setBold(True)
        item_font.setPointSize(30)

        ranks = [p.rank for p in players]
        last_rank = max(ranks, default=0)
        for i, p in enumerate(players):
            tie = "=" if ranks.count(p.rank) > 1 else ""
            if p.rank == last_rank and last_rank > 1:
                medal = self.LAST_MEDAL
            else:
                medal = self.MEDAL.get(p.rank - 1, "")
            rank_str = f"{medal}  {p.rank}.{tie}" if medal else f"    {p.rank}.{tie}"
            for col, text in enumerate([rank_str, p.name, str(p.total)]):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setBackground(self.ROW_BG.get(p.rank - 1, QColor("#FF0000")))
                item.setFont(item_font)
                tbl.setItem(i, col, item)

        self._tbl = tbl
        self._revealed = 0
        self.hide_all()

        # Wrapper provides the rounded bottom corners:
        # its dark background shows through the 16 px bottom margin and curved border.
        frame = QWidget()
        frame.setObjectName("tableFrame")
        frame.setStyleSheet("""
            QWidget#tableFrame {
                background-color: #0d0d1a;
                border: 2px solid black;
                border-top: none;
                border-radius: 0 0 16px 16px;
            }
        """)
        frame_lay = QVBoxLayout(frame)
        frame_lay.setContentsMargins(2, 0, 2, 16)
        frame_lay.setSpacing(0)
        frame_lay.addWidget(tbl)
        # Clip the viewport (cell area) to rounded bottom corners so cells don't bleed into the frame corners.
        BottomRoundedMask(tbl.viewport(), 16)
        self._lay.addWidget(frame)

    # -- reveal state: rows appear from the bottom of the table upwards --
    @property
    def count(self) -> int:
        return self._tbl.rowCount()

    @property
    def revealed(self) -> int:
        return self._revealed

    @property
    def all_revealed(self) -> bool:
        return self._revealed >= self.count

    def set_revealed(self, n: int) -> None:
        n = max(0, min(n, self.count))
        for i in range(self.count):
            self._tbl.setRowHidden(i, i < self.count - n)
        self._revealed = n

    def reveal_next(self) -> None:
        if not self.all_revealed:
            self.set_revealed(self._revealed + 1)

    def reveal_all(self) -> None:
        self.set_revealed(self.count)

    def hide_all(self) -> None:
        self.set_revealed(0)

    def update_font_size(self) -> None:
        """Scale the cell font to the row height (call after resize / when shown)."""
        n = self._tbl.rowCount()
        if n == 0:
            return
        row_px = max(1, self._tbl.viewport().height() // n)
        font = QFont("Noto Serif")
        font.setBold(True)
        font.setPointSize(max(14, int(row_px * 0.75)))
        for i in range(n):
            for col in range(self._tbl.columnCount()):
                item = self._tbl.item(i, col)
                if item:
                    item.setFont(font)


# ---------------------------------------------------------------------------- compare
class ComparePage(_Page):
    """Player toggle buttons on the left, cumulative-points chart on the right."""

    FS_TITLE = 36
    FS_LABEL = 28
    FS_TICK = 22

    playerToggled = pyqtSignal(str)   # a sidebar button was clicked (arg: player number)
    chartPressed = pyqtSignal()

    def __init__(self, title: str, view: View) -> None:
        super().__init__(title)
        self._view = view
        self._selected: set[str] = set()

        panel = QWidget()
        panel.setStyleSheet(_PAGE_STYLE)
        panel_lay = QVBoxLayout(panel)
        panel_lay.setContentsMargins(8, 8, 8, 8)
        panel_lay.setSpacing(6)

        self._buttons: dict[str, QPushButton] = {}
        for p in view.players:
            btn = QPushButton(f"{p.rank}. {p.name}")
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setStyleSheet(f"""
                QPushButton {{
                    font-size: 18px;
                    font-weight: bold;
                    padding: 10px 14px;
                    color: {p.color};
                    background-color: #1a1a2e;
                    border: 2px solid {p.color};
                    border-radius: 8px;
                    text-align: left;
                }}
                QPushButton:checked {{
                    background-color: {p.color};
                    color: black;
                    font-weight: bold;
                }}
            """)
            btn.clicked.connect(lambda _checked, n=p.pnum: self._on_button(n))
            self._buttons[p.pnum] = btn
            panel_lay.addWidget(btn)
        panel_lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(230)
        scroll.setStyleSheet("background-color: #0d0d1a; border: none;")

        self._fig = Figure(tight_layout=True, facecolor="black")
        self._canvas = FigureCanvas(self._fig)
        self._ax = self._fig.add_subplot(111)
        self._canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._canvas.installEventFilter(self)

        body = QWidget()
        body_lay = QHBoxLayout(body)
        body_lay.setContentsMargins(0, 8, 0, 0)
        body_lay.setSpacing(8)
        body_lay.addWidget(scroll, 0)
        body_lay.addWidget(self._canvas, 1)
        self._lay.addWidget(body, 1)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._canvas and event.type() == QEvent.Type.MouseButtonPress:
            self.chartPressed.emit()
        return False

    # -- selection --
    @property
    def selected(self) -> set[str]:
        return set(self._selected)

    def set_selected(self, selected: set[str]) -> None:
        self._selected = {p for p in selected if p in self._buttons}
        for pnum, btn in self._buttons.items():
            btn.setChecked(pnum in self._selected)

    def _on_button(self, pnum: str) -> None:
        self._selected ^= {pnum}
        self.redraw()
        self.playerToggled.emit(pnum)

    # -- chart --
    def redraw(self) -> None:
        ax = self._ax
        ax.clear()
        ax.set_facecolor("black")
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(axis="both", labelsize=self.FS_TICK, colors="white")

        if not self._selected:
            ax.set_title("Select a player to compare", fontsize=self.FS_TITLE, color="white")
            self._canvas.draw()
            return

        xs = list(self._view.rounds)
        for p in self._view.players:
            if p.pnum not in self._selected:
                continue
            ys = list(p.cumulative)
            ax.plot(xs, ys, marker="o", linewidth=4, markersize=10, color=p.color, label=p.name)
            ax.annotate(
                f"{p.name}  {ys[-1]}",
                xy=(xs[-1], ys[-1]),
                xytext=(8, 0), textcoords="offset points",
                va="center", ha="left",
                fontsize=self.FS_TICK, color=p.color, fontweight="bold",
            )

        ax.set_title("Pizinieren", fontsize=self.FS_TITLE, color="white")
        ax.set_xlabel("Round", fontsize=self.FS_LABEL, color="white")
        ax.set_ylabel("Cumulative Points", fontsize=self.FS_LABEL, color="white")
        ax.grid(True, linestyle="--", alpha=0.5, color="white")
        ax.set_xticks(xs)
        self._canvas.draw()


# ---------------------------------------------------------------------------- Walter
class WalterPage(_Page):
    """The "WALTER !" advert page with a pixel-trickle wipe."""

    pressed = pyqtSignal()

    def __init__(self, title: str) -> None:
        super().__init__(title)
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

        qr = qrcode.QRCode(box_size=6, border=2)
        qr.add_data("WE LOVE WALTER")
        qr.make(fit=True)
        buf = io.BytesIO()
        qr.make_image(fill_color="#FF0000", back_color="white").save(buf, format="PNG")
        qr_lbl = QLabel()
        qr_lbl.setPixmap(QPixmap.fromImage(QImage.fromData(buf.getvalue())))
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

        img_path = RESOURCE_ROOT / "images" / "walter2.png"
        if img_path.exists():
            img_lbl = QLabel()
            img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_lbl.setStyleSheet("background: transparent; border: none;")
            img_lbl.setPixmap(
                QPixmap(str(img_path)).scaledToHeight(400, Qt.TransformationMode.SmoothTransformation)
            )
            content_lay.addStretch(1)
            content_lay.addWidget(img_lbl)
            content_lay.addStretch(1)
        else:
            content_lay.addStretch(1)
        content_lay.addWidget(tagline_lbl)
        BottomRoundedMask(content, 16)

        self._content = content
        self._overlay = PixelTrickleOverlay(content)
        content.installEventFilter(self)
        self._lay.addWidget(content, 1)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._content and event.type() == QEvent.Type.MouseButtonPress:
            self.pressed.emit()
        return False

    def start_pixelout(self, on_done) -> None:
        self._overlay.start_pixelout(on_done)

    def stop_pixelout(self) -> None:
        self._overlay.stop()
