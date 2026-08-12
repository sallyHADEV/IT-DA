"""객체 저장소 패널.

"타겟을 객체화 하여 손쉽게 이름을 정하고 태깅하여 분류" 하는 곳. 객체 하나는 이름 + 태그 +
이미지 여러 장이고, 액션은 좌표 대신 이 객체를 가리킨다.

여기서의 편집은 플로우 캔버스의 되돌리기 스택에 들어가지 않는다(플로우와 수명이 다르다).
대신 삭제처럼 되돌리기 어려운 동작은 확인을 받는다.
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from itda.core.model import TargetObject
from itda.gui import icons, style

ROLE_ID = Qt.ItemDataRole.UserRole + 1


def _row_label(obj) -> str:
    """목록에 보일 한 줄.

    예외 이미지가 몇 장인지는 매칭 성패를 좌우하는데 이름만 봐서는 알 수 없어서 같이 적는다
    (한 장이면 굳이 적지 않는다 — 대부분이 그렇고, 없는 정보만 눈에 띄게 하려는 것이다).
    """
    if len(obj.images) > 1:
        return f"{obj.name}   ·{len(obj.images)}장"
    if not obj.images:
        return f"{obj.name}   ·이미지 없음"
    return obj.name


#: 목록 썸네일. 객체는 화면 조각이라 **그림이 곧 이름**이다 — 26x20 으로는 무엇을 찍었는지
#: 알아볼 수 없었다.
THUMB = QSize(56, 30)
#: 격자 칸. 폭을 넉넉히 줘서 이름이 두 줄로 접히게 한다.
#:
#: 세로 목록도 만들어 봤지만 한 화면에 2개밖에 안 보였다. 반대로 예전 44x44 격자는 14개가
#: 보이는 대신 이름이 세 글자에서 잘리고 썸네일을 못 알아봤다 — 그 14 는 "읽을 수 없을 만큼
#: 작아서" 나온 숫자다. 이 크기가 둘 사이의 절충이다.
CELL = QSize(104, 74)


class ObjectPanel(QWidget):
    """객체 목록 + 상세 편집."""

    objects_changed = pyqtSignal()
    #: 스크린샷/객체화 도구를 열어 달라는 요청 (메인 윈도우가 처리)
    capture_requested = pyqtSignal()
    capture_exception_requested = pyqtSignal()
    objectify_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.project = None
        self._current: TargetObject | None = None
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("이름 검색")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search, 1)

        self.tag_filter = QComboBox()
        self.tag_filter.setMinimumWidth(96)
        self.tag_filter.currentIndexChanged.connect(self.reload)
        bar.addWidget(self.tag_filter)
        layout.addLayout(bar)

        splitter = QSplitter(Qt.Orientation.Vertical)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(THUMB)
        self.list.setGridSize(CELL)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setUniformItemSizes(True)
        self.list.setWordWrap(True)  # 이름을 두 줄까지 접어 보여 준다
        self.list.setSpacing(2)
        # 아래 편집 폼이 도크의 3분의 2를 먹어서 목록이 두 줄만 보였다. 자리를 잡아 준다.
        self.list.setMinimumHeight(CELL.height() * 3)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        splitter.addWidget(self.list)

        splitter.addWidget(self._build_detail())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)

        actions = QHBoxLayout()
        actions.setSpacing(4)
        # 도크가 좁아지면 글자가 잘린다("화면에서 캡"). 라벨은 짧게, 설명은 툴팁으로.
        self.btn_capture = QPushButton("＋ 캡처")
        self.btn_capture.setToolTip("스크린샷 도구로 화면을 잘라 새 객체로 저장합니다")
        self.btn_capture.clicked.connect(self.capture_requested.emit)
        self.btn_objectify = QPushButton("객체화")
        self.btn_objectify.setToolTip("스크린샷에서 아이콘·버튼·글자를 자동으로 나눠 한꺼번에 저장합니다")
        self.btn_objectify.clicked.connect(self.objectify_requested.emit)
        self.btn_delete = QPushButton("삭제")
        self.btn_delete.setToolTip("선택한 객체를 삭제합니다")
        self.btn_delete.clicked.connect(self.delete_current)
        for b in (self.btn_capture, self.btn_objectify, self.btn_delete):
            actions.addWidget(b)
        layout.addLayout(actions)

    # ------------------------------------------------------------ 상세 편집

    def _build_detail(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)

        form = QFormLayout()
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.edit_name = QLineEdit()
        self.edit_name.editingFinished.connect(self._on_name_changed)
        form.addRow("이름", self.edit_name)

        self.edit_tags = QLineEdit()
        self.edit_tags.setPlaceholderText("예: 설정창, 버튼 (쉼표로 태그 구분)")
        self.edit_tags.setToolTip(
            "객체를 그룹으로 분류하고 검색 필터로 찾기 위한 꼬리표(태그)입니다.\n"
            "여러 개 입력 시 쉼표(,)로 구분합니다.\n"
            "예: '설정창, 버튼' 입력 시 '설정창' 태그와 '버튼' 태그가 동시에 적용됩니다."
        )
        self.edit_tags.editingFinished.connect(self._on_tags_changed)
        form.addRow("태그", self.edit_tags)

        self.spin_threshold = QDoubleSpinBox()
        self.spin_threshold.setRange(0.0, 1.0)
        self.spin_threshold.setSingleStep(0.01)
        self.spin_threshold.setDecimals(2)
        self.spin_threshold.setSpecialValueText("프로파일 상속")
        self.spin_threshold.valueChanged.connect(self._on_threshold_changed)
        form.addRow("임계값", self.spin_threshold)

        self.combo_mode = QComboBox()
        for value, label in (("any", "하나라도"), ("best", "가장 높은 점수"), ("all", "전부")):
            self.combo_mode.addItem(label, value)
        self.combo_mode.currentIndexChanged.connect(self._on_mode_changed)
        form.addRow("다중 이미지", self.combo_mode)

        anchor_row = QHBoxLayout()
        self.spin_dx = QSpinBox()
        self.spin_dy = QSpinBox()
        for spin in (self.spin_dx, self.spin_dy):
            spin.setRange(-4000, 4000)
            spin.valueChanged.connect(self._on_anchor_changed)
        anchor_row.addWidget(QLabel("X"))
        anchor_row.addWidget(self.spin_dx)
        anchor_row.addWidget(QLabel("Y"))
        anchor_row.addWidget(self.spin_dy)
        anchor_row.addStretch(1)
        anchor_box = QWidget()
        anchor_box.setLayout(anchor_row)
        anchor_row.setContentsMargins(0, 0, 0, 0)
        form.addRow("클릭 보정", anchor_box)
        layout.addLayout(form)

        images_head = QHBoxLayout()
        images_head.addWidget(QLabel("예외/다중 이미지"))
        images_head.addStretch(1)
        capture_image = QToolButton()
        capture_image.setIcon(icons.icon("coord", style.TEXT))
        capture_image.setIconSize(QSize(15, 15))
        capture_image.setToolTip("스크린샷 도구로 화면을 캡처하여 예외 이미지 추가")
        capture_image.clicked.connect(self.capture_exception_requested.emit)
        add_image = QToolButton()
        add_image.setIcon(icons.icon("plus", style.TEXT))
        add_image.setIconSize(QSize(15, 15))
        add_image.setToolTip("파일에서 이미지 추가")
        add_image.clicked.connect(self.add_image_from_file)
        remove_image = QToolButton()
        remove_image.setIcon(icons.icon("minus", style.TEXT))
        remove_image.setIconSize(QSize(15, 15))
        remove_image.setToolTip("선택한 이미지 제거")
        remove_image.clicked.connect(self.remove_selected_image)
        images_head.addWidget(capture_image)
        images_head.addWidget(add_image)
        images_head.addWidget(remove_image)
        layout.addLayout(images_head)

        self.image_list = QListWidget()
        self.image_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.image_list.setIconSize(QSize(64, 48))
        self.image_list.setGridSize(QSize(76, 66))
        self.image_list.setMaximumHeight(96)
        layout.addWidget(self.image_list)

        self.hint = QLabel("객체를 선택하면 여기서 편집합니다.")
        self.hint.setProperty("role", "hint")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        return panel

    # ------------------------------------------------------------ 표시

    def set_project(self, project) -> None:
        self.project = project
        self.reload()

    def reload(self) -> None:
        if self.project is None:
            return
        self._loading = True

        selected_tag = self.tag_filter.currentText()
        self.tag_filter.blockSignals(True)
        self.tag_filter.clear()
        self.tag_filter.addItem("모든 태그")
        self.tag_filter.addItems(self.project.objects.all_tags())
        index = self.tag_filter.findText(selected_tag)
        self.tag_filter.setCurrentIndex(index if index > 0 else 0)
        self.tag_filter.blockSignals(False)

        tags = [] if self.tag_filter.currentIndex() <= 0 else [self.tag_filter.currentText()]
        matches = self.project.objects.search(self.search.text(), tags)

        current_id = self._current.id if self._current else None
        self.list.clear()
        for obj in matches:
            item = QListWidgetItem(_row_label(obj))
            item.setData(ROLE_ID, obj.id)
            item.setIcon(QIcon(self._thumbnail(obj)))
            item.setSizeHint(CELL)
            item.setToolTip(
                f"{obj.name}\n태그: {', '.join(obj.tags) or '없음'}\n이미지 {len(obj.images)}장"
            )
            self.list.addItem(item)
            if obj.id == current_id:
                self.list.setCurrentItem(item)

        self._loading = False
        if self.list.currentItem() is None:
            self._show_object(None)

    def _thumbnail(self, obj: TargetObject) -> QPixmap:
        for relative in obj.images:
            path = self.project.image_path(relative)
            if path and path.exists():
                pixmap = QPixmap(str(path))
                if not pixmap.isNull():
                    return pixmap.scaled(
                        THUMB,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
        placeholder = QPixmap(THUMB)
        placeholder.fill(style.SURFACE_ALT)
        return placeholder

    def _show_object(self, obj: TargetObject | None) -> None:
        self._current = obj
        self._loading = True
        enabled = obj is not None
        for widget in (
            self.edit_name,
            self.edit_tags,
            self.spin_threshold,
            self.combo_mode,
            self.spin_dx,
            self.spin_dy,
            self.image_list,
            self.btn_delete,
        ):
            widget.setEnabled(enabled)

        if obj is None:
            self.edit_name.clear()
            self.edit_tags.clear()
            self.image_list.clear()
            self.hint.setText("객체를 선택하면 여기서 편집합니다.")
            self._loading = False
            return

        self.edit_name.setText(obj.name)
        self.edit_tags.setText(", ".join(obj.tags))
        self.spin_threshold.setValue(obj.match.threshold or 0.0)
        mode_index = self.combo_mode.findData(obj.match.mode)
        self.combo_mode.setCurrentIndex(max(0, mode_index))
        self.spin_dx.setValue(obj.anchor_dx)
        self.spin_dy.setValue(obj.anchor_dy)

        self.image_list.clear()
        for relative in obj.images:
            path = self.project.image_path(relative)
            item = QListWidgetItem()
            item.setToolTip(relative)
            if path and path.exists():
                item.setIcon(QIcon(str(path)))
            else:
                item.setText("없음")
            item.setData(ROLE_ID, relative)
            self.image_list.addItem(item)

        self.hint.setText(obj.note or "")
        self._loading = False

    def current_object(self) -> TargetObject | None:
        return self._current

    def object_updated(self, obj: TargetObject | None = None) -> None:
        """바깥에서 객체를 고쳤을 때 화면을 맞춘다.

        더티 표시, 편집 폼, 목록을 한 번에 처리한다. 메인 윈도우가 예외 이미지를 추가하는
        경로가 있어서, 그쪽이 이 패널 내부를 들여다보지 않도록 창구를 열어 둔다.
        """
        self._touch()
        self._show_object(obj if obj is not None else self._current)
        self.reload()

    # ------------------------------------------------------------ 편집

    def _touch(self) -> None:
        if self.project is not None:
            self.project.mark_dirty()
        self.objects_changed.emit()

    def _on_current_changed(self, current, _previous) -> None:
        if self._loading or self.project is None:
            return
        obj = self.project.objects.get(current.data(ROLE_ID)) if current else None
        self._show_object(obj)

    def _on_name_changed(self) -> None:
        if self._loading or self._current is None:
            return
        name = self.edit_name.text().strip()
        if not name or name == self._current.name:
            return
        taken = {o.name for o in self.project.objects.objects if o is not self._current}
        if name in taken:
            QMessageBox.information(self, "이름 중복", "같은 이름의 객체가 이미 있습니다.")
            self.edit_name.setText(self._current.name)
            return
        self._current.name = name
        self._touch()
        self.reload()

    def _on_tags_changed(self) -> None:
        if self._loading or self._current is None:
            return
        tags = [t.strip() for t in self.edit_tags.text().split(",") if t.strip()]
        if tags != self._current.tags:
            self._current.tags = tags
            self._touch()
            self.reload()

    def _on_threshold_changed(self, value: float) -> None:
        if self._loading or self._current is None:
            return
        self._current.match.threshold = None if value <= 0 else round(value, 2)
        self._touch()

    def _on_mode_changed(self) -> None:
        if self._loading or self._current is None:
            return
        self._current.match.mode = self.combo_mode.currentData()
        self._touch()

    def _on_anchor_changed(self) -> None:
        if self._loading or self._current is None:
            return
        self._current.anchor_dx = self.spin_dx.value()
        self._current.anchor_dy = self.spin_dy.value()
        self._touch()

    def add_object(self, obj: TargetObject) -> TargetObject:
        created = self.project.add_object(obj)
        self.reload()
        self.select_object(created.id)
        self.objects_changed.emit()
        return created

    def select_object(self, object_id: str) -> None:
        for i in range(self.list.count()):
            if self.list.item(i).data(ROLE_ID) == object_id:
                self.list.setCurrentRow(i)
                return

    def add_image_from_file(self) -> None:
        if self._current is None or self.project is None:
            return
        if self.project.path is None:
            QMessageBox.information(self, "프로젝트를 먼저 저장하세요",
                                    "이미지를 프로젝트 폴더에 넣으려면 프로젝트를 한 번 저장해야 합니다.")
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "이미지 추가", "", "이미지 (*.png *.jpg *.bmp)")
        from pathlib import Path

        for path in paths:
            relative = self.project.import_image(Path(path), self._current.name)
            self._current.images.append(relative)
        if paths:
            self._touch()
            self._show_object(self._current)
            self.reload()

    def remove_selected_image(self) -> None:
        if self._current is None:
            return
        item = self.image_list.currentItem()
        if item is None:
            return
        relative = item.data(ROLE_ID)
        if relative in self._current.images:
            self._current.images.remove(relative)
            self._touch()
            self._show_object(self._current)
            self.reload()

    def delete_current(self) -> None:
        if self._current is None or self.project is None:
            return
        answer = QMessageBox.question(
            self,
            "객체 삭제",
            f"'{self._current.name}' 객체를 삭제할까요?\n이 객체를 쓰는 액션은 검사에서 경고로 표시됩니다.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.project.objects.objects.remove(self._current)
        self._current = None
        self._touch()
        self.reload()

    def _context_menu(self, pos) -> None:
        item = self.list.itemAt(pos)
        if item is None:
            return
        self.list.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction("이미지 추가", self.add_image_from_file)
        menu.addSeparator()
        menu.addAction("삭제", self.delete_current)
        menu.exec(self.list.mapToGlobal(pos))
