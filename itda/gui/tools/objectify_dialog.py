"""객체화 도구.

스크린샷을 넣으면 아이콘·버튼·글자 후보를 자동으로 구역을 나눠 보여주고, 사용자가 고른
것들을 한꺼번에 개별 이미지 + 객체로 저장한다. 버튼 스무 개를 하나씩 드래그해 잘라내던
일을 없애는 것이 목적이다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from itda.core.model import TargetObject
from itda.gui import style
from itda.vision import capture
from itda.vision.segmenter import Region, SegmentOptions, crop, propose_regions

KIND_COLORS = {
    "icon": QColor("#4fa98a"),
    "text": QColor("#4a6fa5"),
    "button": QColor("#ee7f63"),
}
KIND_LABELS = {"icon": "아이콘", "text": "글자", "button": "버튼"}

ROLE_INDEX = Qt.ItemDataRole.UserRole + 1


@dataclass
class SavedObject:
    name: str
    region: Region


class RegionItem(QGraphicsRectItem):
    """분할된 영역 하나. 클릭으로 선택한다."""

    def __init__(self, region: Region, index: int) -> None:
        super().__init__(QRectF(region.x, region.y, region.w, region.h))
        self.region = region
        self.index = index
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setAcceptHoverEvents(True)
        self.setToolTip(f"{KIND_LABELS.get(region.kind, region.kind)} · {region.w}×{region.h}")
        self._hover = False

    def toggle(self) -> None:
        self.setSelected(not self.isSelected())

    def paint(self, painter: QPainter, option, widget=None) -> None:
        color = KIND_COLORS.get(self.region.kind, QColor("#9aa5b1"))
        selected = self.isSelected()
        pen = QPen(style.ACCENT if selected else color, 2 if selected else 1)
        painter.setPen(pen)
        if selected:
            painter.setBrush(QBrush(QColor(238, 127, 99, 60)))
        elif self._hover:
            painter.setBrush(QBrush(QColor(255, 255, 255, 30)))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self.rect())

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().hoverLeaveEvent(event)


class _ImageView(QGraphicsView):
    """휠 줌 + 드래그로 수동 박스 추가."""

    def __init__(self, dialog: ObjectifyDialog) -> None:
        super().__init__(dialog.scene)
        self.dialog = dialog
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._zoom = 1.0
        self._draw_origin: QPointF | None = None
        self._preview: QGraphicsRectItem | None = None
        self._kept_selection: list = []

    def wheelEvent(self, event) -> None:
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        target = max(0.15, min(8.0, self._zoom * factor))
        factor = target / self._zoom
        self._zoom = target
        self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._draw_origin = self.mapToScene(event.position().toPoint())
            self._preview = self.scene().addRect(
                QRectF(self._draw_origin, self._draw_origin), QPen(style.ACCENT, 1)
            )
            event.accept()
            return

        # 박스를 누르면 선택, 다시 누르면 해제. 여러 개를 이어서 고를 수 있다.
        # 뷰의 기본 동작(고무줄 선택)에 맡기면 누를 때마다 이전 선택이 지워진다.
        item = self.itemAt(event.position().toPoint())
        if isinstance(item, RegionItem) and event.button() == Qt.MouseButton.LeftButton:
            item.toggle()
            event.accept()
            return

        # 빈 곳에서 시작한 고무줄 선택은 기존 선택에 **더한다**
        self._kept_selection = [i for i in self.scene().selectedItems()]
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._draw_origin is not None and self._preview is not None:
            rect = QRectF(self._draw_origin, self.mapToScene(event.position().toPoint())).normalized()
            self._preview.setRect(rect)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._draw_origin is not None:
            rect = self._preview.rect() if self._preview else QRectF()
            if self._preview is not None:
                self.scene().removeItem(self._preview)
            self._preview = None
            self._draw_origin = None
            if rect.width() >= 4 and rect.height() >= 4:
                self.dialog.add_manual_region(
                    Region(int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height()), "button")
                )
            event.accept()
            return

        super().mouseReleaseEvent(event)
        # 고무줄로 새로 고른 것에 이전 선택을 되살려 더한다
        for item in getattr(self, "_kept_selection", []):
            item.setSelected(True)
        self._kept_selection = []


class ObjectifyDialog(QDialog):
    """스크린샷 → 영역 자동 분할 → 골라서 일괄 객체 저장."""

    def __init__(self, image: np.ndarray, project, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("객체화 도구")
        self.resize(1180, 760)
        self.image = image
        self.project = project
        self.regions: list[Region] = []
        self.items: list[RegionItem] = []
        self.saved: list[SavedObject] = []

        self.scene = QGraphicsScene(self)
        self.pixmap_item = self.scene.addPixmap(capture.bgr_to_pixmap(image))
        self.view = _ImageView(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.view)
        splitter.addWidget(self._build_side())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(splitter, 1)

        buttons = QDialogButtonBox()
        self.btn_save = buttons.addButton("선택 항목 저장", QDialogButtonBox.ButtonRole.AcceptRole)
        self.btn_save.setProperty("accent", True)
        self.btn_save.clicked.connect(self.save_selected)
        cancel = buttons.addButton("닫기", QDialogButtonBox.ButtonRole.RejectRole)
        cancel.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self.scene.selectionChanged.connect(self._sync_list_from_scene)
        self.analyze()

    # ------------------------------------------------------------ 우측 패널

    def _build_side(self) -> QWidget:
        side = QWidget()
        layout = QVBoxLayout(side)
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(8)

        options = QGroupBox("분할 설정")
        opt_layout = QVBoxLayout(options)
        opt_layout.setContentsMargins(10, 6, 10, 8)
        opt_layout.setSpacing(5)

        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("최소 크기"))
        self.min_size = QSpinBox()
        self.min_size.setRange(4, 200)
        self.min_size.setValue(10)
        self.min_size.setSuffix(" px")
        size_row.addWidget(self.min_size)
        size_row.addStretch(1)
        opt_layout.addLayout(size_row)

        gap_row = QHBoxLayout()
        gap_row.addWidget(QLabel("글자 묶음 간격"))
        self.line_gap = QSpinBox()
        self.line_gap.setRange(0, 80)
        self.line_gap.setValue(12)
        self.line_gap.setSuffix(" px")
        gap_row.addWidget(self.line_gap)
        gap_row.addStretch(1)
        opt_layout.addLayout(gap_row)

        self.chk_icon = QCheckBox("아이콘")
        self.chk_text = QCheckBox("글자")
        self.chk_button = QCheckBox("버튼")
        for box in (self.chk_icon, self.chk_text, self.chk_button):
            box.setChecked(True)
            box.toggled.connect(self._apply_filter)
            opt_layout.addWidget(box)

        rerun = QPushButton("다시 분석")
        rerun.clicked.connect(self.analyze)
        opt_layout.addWidget(rerun)
        layout.addWidget(options)

        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.itemSelectionChanged.connect(self._sync_scene_from_list)
        layout.addWidget(self.list, 1)

        pick_row = QHBoxLayout()
        for text, slot in (
            ("전체 선택", lambda: self._select_all(True)),
            ("전체 해제", lambda: self._select_all(False)),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            pick_row.addWidget(button)
        layout.addLayout(pick_row)

        save_box = QGroupBox("저장 설정")
        save_layout = QVBoxLayout(save_box)
        save_layout.setContentsMargins(10, 6, 10, 8)
        save_layout.setSpacing(5)

        self.name_prefix = QLineEdit("객체")
        self.name_prefix.setPlaceholderText("이름 앞부분 (예: 설정창_버튼)")
        save_layout.addWidget(QLabel("이름 접두사"))
        save_layout.addWidget(self.name_prefix)

        self.tags = QLineEdit()
        self.tags.setPlaceholderText("예: 설정창, 버튼 (쉼표로 구분)")
        self.tags.setToolTip(
            "객체들을 그룹으로 분류하고 검색 필터로 찾기 위한 태그입니다.\n"
            "여러 태그 입력 시 쉼표(,)로 구분하여 작성합니다."
        )
        save_layout.addWidget(QLabel("태그 (쉼표로 구분)"))
        save_layout.addWidget(self.tags)

        pad_row = QHBoxLayout()
        pad_row.addWidget(QLabel("여백"))
        self.padding = QSpinBox()
        self.padding.setRange(0, 40)
        self.padding.setValue(2)
        self.padding.setSuffix(" px")
        pad_row.addWidget(self.padding)
        pad_row.addStretch(1)
        save_layout.addLayout(pad_row)

        layout.addWidget(save_box)

        self.status = QLabel("Ctrl + 드래그로 직접 영역을 그릴 수 있습니다.")
        self.status.setProperty("role", "hint")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        return side

    # ------------------------------------------------------------ 분석

    def analyze(self) -> None:
        options = SegmentOptions(
            min_width=self.min_size.value(),
            min_height=self.min_size.value(),
            line_gap=self.line_gap.value(),
        )
        self.regions = propose_regions(self.image, options)
        self._rebuild_items()
        self.status.setText(f"{len(self.regions)}개 영역을 찾았습니다. 저장할 것을 고르세요.")

    def add_manual_region(self, region: Region) -> None:
        self.regions.append(region)
        self._rebuild_items()
        if self.items:
            self.items[-1].setSelected(True)
        self.status.setText(f"직접 그린 영역을 추가했습니다 ({region.w}×{region.h}).")

    def _rebuild_items(self) -> None:
        for item in self.items:
            self.scene.removeItem(item)
        self.items.clear()
        self.list.clear()

        for index, region in enumerate(self.regions):
            item = RegionItem(region, index)
            self.scene.addItem(item)
            self.items.append(item)

            entry = QListWidgetItem(
                f"{index + 1:>3}. {KIND_LABELS.get(region.kind, region.kind)}"
                f"  {region.w}×{region.h}  @({region.x},{region.y})"
            )
            entry.setData(ROLE_INDEX, index)
            entry.setForeground(KIND_COLORS.get(region.kind, QColor("#9aa5b1")))
            self.list.addItem(entry)
        self._apply_filter()

    def _apply_filter(self) -> None:
        allowed = {
            "icon": self.chk_icon.isChecked(),
            "text": self.chk_text.isChecked(),
            "button": self.chk_button.isChecked(),
        }
        for index, item in enumerate(self.items):
            visible = allowed.get(item.region.kind, True)
            item.setVisible(visible)
            if not visible:
                item.setSelected(False)
            self.list.item(index).setHidden(not visible)

    # ------------------------------------------------------------ 선택 동기화

    def _select_all(self, selected: bool) -> None:
        for item in self.items:
            if item.isVisible():
                item.setSelected(selected)

    def _sync_list_from_scene(self) -> None:
        self.list.blockSignals(True)
        for index, item in enumerate(self.items):
            self.list.item(index).setSelected(item.isSelected())
        self.list.blockSignals(False)
        self._update_count()

    def _sync_scene_from_list(self) -> None:
        chosen = {item.data(ROLE_INDEX) for item in self.list.selectedItems()}
        self.scene.blockSignals(True)
        for index, item in enumerate(self.items):
            item.setSelected(index in chosen)
        self.scene.blockSignals(False)
        self._update_count()

    def selected_regions(self) -> list[Region]:
        return [item.region for item in self.items if item.isSelected() and item.isVisible()]

    def _update_count(self) -> None:
        count = len(self.selected_regions())
        self.btn_save.setText(f"선택 {count}개 저장" if count else "선택 항목 저장")
        self.btn_save.setEnabled(count > 0)

    # ------------------------------------------------------------ 저장

    def save_selected(self) -> None:
        regions = self.selected_regions()
        if not regions:
            return
        if self.project.path is None:
            QMessageBox.information(
                self,
                "프로젝트를 먼저 저장하세요",
                "이미지를 프로젝트 폴더에 넣어야 하므로, 프로젝트를 한 번 저장한 뒤 사용하세요.",
            )
            return

        prefix = self.name_prefix.text().strip() or "객체"
        tags = [t.strip() for t in self.tags.text().split(",") if t.strip()]
        padding = self.padding.value()

        temp_dir = self.project.path / "objects" / "img"
        temp_dir.mkdir(parents=True, exist_ok=True)

        saved = 0
        for index, region in enumerate(regions, start=1):
            patch = crop(self.image, region, padding)
            if patch.size == 0:
                continue
            temp_path = temp_dir / f".{prefix}_{index}.tmp.png"
            if not capture.save_bgr(patch, temp_path):
                continue
            try:
                relative = self.project.import_image(temp_path, f"{prefix}_{index}")
            finally:
                temp_path.unlink(missing_ok=True)  # 실패해도 찌꺼기를 남기지 않는다

            obj = TargetObject(
                name=f"{prefix}_{index}",
                tags=list(tags),
                images=[relative],
                note=f"객체화 도구로 생성 · 원본 좌표 ({region.x}, {region.y})",
            )
            created = self.project.add_object(obj)
            self.saved.append(SavedObject(created.name, region))
            saved += 1

        # 저장 결과는 메인 윈도우가 로그와 객체 패널로 알린다. 여기서 확인 대화상자를
        # 또 띄우면 대량 저장 흐름만 끊긴다.
        self.status.setText(f"{saved}개를 객체로 저장했습니다.")
        self.accept()
