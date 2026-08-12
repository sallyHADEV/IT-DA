"""스키마 → 폼 자동 생성.

액션이 :class:`~itda.core.schema.Field` 목록만 선언하면 여기서 위젯을 만들어 준다.
액션을 추가할 때 UI 코드를 쓰지 않아도 되는 이유가 이 파일이다.

폼은 값이 바뀔 때 :attr:`SchemaForm.value_changed` 를 쏘고, 실제 모델 반영과 되돌리기는
속성 패널이 커맨드로 처리한다. 즉 이 위젯은 모델을 모른다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from itda.core.schema import Field
from itda.gui import icons, style

INT_RANGE = (-1_000_000, 1_000_000)


def _empty() -> list[str]:
    return []


@dataclass
class FormContext:
    """폼이 바깥 세계에 물어봐야 하는 것들.

    작업 도구(좌표/영역 선택)와 프로젝트 목록(객체·플로우·상황·노드)을 여기로 주입한다.
    None 이면 해당 버튼이 비활성화될 뿐 폼은 정상 동작한다.
    """

    objects: Callable[[], list[str]] = _empty
    flows: Callable[[], list[str]] = _empty
    states: Callable[[], list[str]] = _empty
    variables: Callable[[], list[str]] = _empty
    #: 노드는 이름이 겹칠 수 있어 (id, 표시이름) 쌍으로 다룬다.
    nodes: Callable[[], list[tuple[str, str]]] = _empty
    pick_point: Callable[[], tuple[int, int] | None] | None = None
    pick_rect: Callable[[], tuple[int, int, int, int] | None] | None = None
    #: (제목, x, y, width, height) — 창 맞추기 속성 폼의 "창 선택" 버튼이 쓴다.
    pick_window: Callable[[], tuple[str, int, int, int, int] | None] | None = None
    #: 프로젝트 프로파일의 이미지 일치 임계값. "기본값 사용" 라벨에 실제 값을 적기 위해.
    match_default: Callable[[], float] | None = None

    def default_threshold(self) -> float:
        """상속했을 때 실제로 쓰일 임계값. 못 물어보면 프로파일 기본값."""
        from itda.core.timing import TimingProfile

        try:
            if self.match_default is not None:
                return float(self.match_default())
        except Exception:
            pass
        return TimingProfile.match_threshold

    def list_of(self, kind: str) -> list[str]:
        getter = {
            "object": self.objects,
            "flow": self.flows,
            "state": self.states,
            "var": self.variables,
        }.get(kind)
        try:
            return list(getter()) if getter else []
        except Exception:
            return []

    def node_choices(self) -> list[tuple[str, str]]:
        try:
            return list(self.nodes())
        except Exception:
            return []


# ---------------------------------------------------------------- 개별 편집기


class FieldEditor(QWidget):
    """필드 하나를 편집하는 위젯의 공통 인터페이스."""

    edited = pyqtSignal(object)

    def __init__(self, field: Field, context: FormContext, parent=None) -> None:
        super().__init__(parent)
        self.field = field
        self.context = context
        self._loading = False
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        if field.help:
            self.setToolTip(field.help)

    def set_value(self, value: Any) -> None:  # pragma: no cover - 하위 클래스가 구현
        raise NotImplementedError

    def value(self) -> Any:  # pragma: no cover
        raise NotImplementedError

    def _emit(self) -> None:
        if not self._loading:
            self.edited.emit(self.value())

    def load(self, value: Any) -> None:
        self._loading = True
        try:
            self.set_value(value)
        finally:
            self._loading = False


def _row(*widgets: QWidget) -> QWidget:
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    for w in widgets:
        layout.addWidget(w)
    return box


def _tool_button(icon_name: str, tip: str, slot=None) -> QToolButton:
    """아이콘 도구 버튼.

    글리프 문자(⊹, ⧉ 같은)는 한글 폰트에 없는 경우가 많아 네모로 나온다. 벡터 아이콘을 쓴다.
    """
    button = QToolButton()
    button.setIcon(icons.icon(icon_name, style.TEXT))
    button.setIconSize(QSize(15, 15))
    button.setToolTip(tip)
    if slot is not None:
        button.clicked.connect(slot)
    return button


class IntEditor(FieldEditor):
    def __init__(self, field: Field, context: FormContext, parent=None) -> None:
        super().__init__(field, context, parent)
        self.spin = QSpinBox()
        lo = int(field.minimum) if field.minimum is not None else INT_RANGE[0]
        hi = int(field.maximum) if field.maximum is not None else INT_RANGE[1]
        self.spin.setRange(lo, hi)
        self.spin.setSingleStep(max(1, int(field.step)))
        if field.suffix:
            self.spin.setSuffix(field.suffix)
        self.spin.valueChanged.connect(lambda _: self._emit())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.spin)

    def set_value(self, value: Any) -> None:
        try:
            self.spin.setValue(int(value))
        except (TypeError, ValueError):
            self.spin.setValue(0)

    def value(self) -> int:
        return self.spin.value()


class FloatEditor(FieldEditor):
    def __init__(self, field: Field, context: FormContext, parent=None) -> None:
        super().__init__(field, context, parent)
        self.spin = QDoubleSpinBox()
        self.spin.setDecimals(2)
        self.spin.setRange(
            field.minimum if field.minimum is not None else -1e6,
            field.maximum if field.maximum is not None else 1e6,
        )
        self.spin.setSingleStep(field.step if field.step else 0.1)
        if field.suffix:
            self.spin.setSuffix(field.suffix)
        self.spin.valueChanged.connect(lambda _: self._emit())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.spin)

    def set_value(self, value: Any) -> None:
        try:
            self.spin.setValue(float(value))
        except (TypeError, ValueError):
            self.spin.setValue(0.0)

    def value(self) -> float:
        return round(self.spin.value(), 4)


class MatchThresholdEditor(FieldEditor):
    """이미지 일치 임계값 — 슬라이더 + "기본값 사용" 체크박스.

    저장값 0 은 "상속"(프로젝트 기본 임계값을 그대로 따름)이라는 특별한 의미다. 숫자 하나로는
    이 두 가지 뜻(직접 정한 값 vs 상속)이 잘 구분되지 않아서, 상속 여부를 체크박스로 따로
    떼어 냈다. 체크돼 있으면 슬라이더를 잠그고 0 을 저장하고, 풀면 슬라이더가 가리키는
    값(1~100%)을 저장한다. 양 끝을 숫자 대신 "불일치 허용 ↔ 정확히 일치" 로 읽어, 이 값이
    화면과 등록 이미지가 얼마나 닮아야 '찾음' 으로 볼지의 기준이라는 걸 바로 알 수 있게 한다.

    체크박스에 적는 퍼센트는 **프로젝트 프로파일에서 읽어 온다**. 숫자를 코드에 박아 두면
    타이밍 대화상자에서 프로파일을 바꿨을 때 라벨만 옛 값을 가리켜 거짓말을 하게 된다.
    (객체마다 따로 정한 임계값이 있으면 그쪽이 우선한다 — 툴팁으로 알린다.)
    """

    TOOLTIP = (
        "켜 두면 이 동작은 임계값을 직접 정하지 않고 물려받습니다.\n"
        "객체에 임계값이 지정돼 있으면 그 값이, 없으면 프로젝트 프로파일의 값이 쓰입니다."
    )

    def __init__(self, field: Field, context: FormContext, parent=None) -> None:
        super().__init__(field, context, parent)
        self._custom_pct = self._default_pct()

        self.checkbox = QCheckBox()
        self.checkbox.setToolTip(self.TOOLTIP)
        self.checkbox.toggled.connect(self._on_checkbox_toggled)
        self._refresh_checkbox_text()

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(1, 100)
        self.slider.setValue(self._custom_pct)
        self.slider.valueChanged.connect(self._on_slider_changed)

        left = QLabel("불일치 허용")
        left.setProperty("role", "hint")
        right = QLabel("정확히 일치")
        right.setProperty("role", "hint")
        self.value_label = QLabel(f"{self._custom_pct}%")
        self.value_label.setMinimumWidth(34)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        slider_row = QWidget()
        row_layout = QHBoxLayout(slider_row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        row_layout.addWidget(left)
        row_layout.addWidget(self.slider, 1)
        row_layout.addWidget(right)
        row_layout.addWidget(self.value_label)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(self.checkbox)
        layout.addWidget(slider_row)

    def _default_pct(self) -> int:
        """상속했을 때 실제로 쓰일 값(%). 프로파일이 바뀌면 이것도 따라 바뀐다."""
        return max(1, min(100, round(self.context.default_threshold() * 100)))

    def _refresh_checkbox_text(self) -> None:
        self.checkbox.setText(f"기본값 사용 ({self._default_pct()}%)")

    def _on_checkbox_toggled(self, checked: bool) -> None:
        self.slider.setEnabled(not checked)
        if not checked:
            self.slider.setValue(self._custom_pct)
        self._emit()

    def _on_slider_changed(self, pct: int) -> None:
        self._custom_pct = pct
        self.value_label.setText(f"{pct}%")
        if not self.checkbox.isChecked():
            self._emit()

    def set_value(self, value: Any) -> None:
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = 0.0
        use_default = v <= 0.0
        if not use_default:
            self._custom_pct = max(1, min(100, round(v * 100)))
        self._refresh_checkbox_text()  # 그 사이 프로파일이 바뀌었을 수 있다

        # 신호를 막고 직접 맞춘다 — 체크박스를 건드리면 토글 핸들러가 슬라이더까지
        # 연쇄로 건드리는데, 로딩 중엔 결과가 뻔한데도 굳이 두 번 계산할 이유가 없다.
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(use_default)
        self.checkbox.blockSignals(False)

        self.slider.blockSignals(True)
        self.slider.setValue(self._custom_pct)
        self.slider.setEnabled(not use_default)
        self.slider.blockSignals(False)

        self.value_label.setText(f"{self._custom_pct}%")

    def value(self) -> float:
        if self.checkbox.isChecked():
            return 0.0
        return round(self.slider.value() / 100, 2)


class StrEditor(FieldEditor):
    def __init__(self, field: Field, context: FormContext, parent=None) -> None:
        super().__init__(field, context, parent)
        self.edit = QLineEdit()
        self.edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit.setMinimumWidth(160)
        self.edit.setPlaceholderText(field.help[:40] if field.help else "")
        self.edit.textEdited.connect(lambda _: self._emit())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit)

    def set_value(self, value: Any) -> None:
        self.edit.setText("" if value is None else str(value))

    def value(self) -> str:
        return self.edit.text()


class TextEditor(FieldEditor):
    def __init__(self, field: Field, context: FormContext, parent=None) -> None:
        super().__init__(field, context, parent)
        self.edit = QPlainTextEdit()
        self.edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.edit.setMinimumWidth(160)
        self.edit.setMinimumHeight(64)
        self.edit.setMaximumHeight(140)
        self.edit.textChanged.connect(self._emit)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit)

    def set_value(self, value: Any) -> None:
        if self.edit.toPlainText() != (value or ""):
            self.edit.setPlainText("" if value is None else str(value))

    def value(self) -> str:
        return self.edit.toPlainText()


class BoolEditor(FieldEditor):
    def __init__(self, field: Field, context: FormContext, parent=None) -> None:
        super().__init__(field, context, parent)
        self.check = QCheckBox(field.label)
        self.check.toggled.connect(lambda _: self._emit())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.check)

    def set_value(self, value: Any) -> None:
        self.check.setChecked(bool(value))

    def value(self) -> bool:
        return self.check.isChecked()


class EnumEditor(FieldEditor):
    def __init__(self, field: Field, context: FormContext, parent=None) -> None:
        super().__init__(field, context, parent)
        self.combo = QComboBox()
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.combo.setMinimumWidth(160)
        for value, label in field.options:
            self.combo.addItem(label, value)
        self.combo.currentIndexChanged.connect(lambda _: self._emit())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo)

    def set_value(self, value: Any) -> None:
        index = self.combo.findData(value)
        self.combo.setCurrentIndex(index if index >= 0 else 0)

    def value(self) -> Any:
        return self.combo.currentData()


class PointEditor(FieldEditor):
    """좌표 + 좌표 도구 버튼."""

    def __init__(self, field: Field, context: FormContext, parent=None) -> None:
        super().__init__(field, context, parent)
        self.x = QSpinBox()
        self.y = QSpinBox()
        for spin in (self.x, self.y):
            spin.setRange(-32000, 32000)
            spin.setMinimumWidth(56)
            spin.valueChanged.connect(lambda _: self._emit())
        self.pick = _tool_button("coord", "좌표 도구로 화면에서 찍기", self._pick)
        self.pick.setEnabled(context.pick_point is not None)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_row(QLabel("X"), self.x, QLabel("Y"), self.y, self.pick))

    def _pick(self) -> None:
        if self.context.pick_point is None:
            return
        result = self.context.pick_point()
        if result:
            self.x.setValue(int(result[0]))
            self.y.setValue(int(result[1]))

    def set_value(self, value: Any) -> None:
        pair = list(value or [0, 0])
        while len(pair) < 2:
            pair.append(0)
        self.x.setValue(int(pair[0]))
        self.y.setValue(int(pair[1]))

    def value(self) -> list[int]:
        return [self.x.value(), self.y.value()]


class RectEditor(FieldEditor):
    """영역 + 화면에서 영역 지정 버튼."""

    def __init__(self, field: Field, context: FormContext, parent=None) -> None:
        super().__init__(field, context, parent)
        self.spins = []
        for _ in range(4):
            spin = QSpinBox()
            spin.setRange(-32000, 32000)
            spin.setMinimumWidth(56)
            spin.valueChanged.connect(lambda _: self._emit())
            self.spins.append(spin)
        self.pick = _tool_button("region", "화면에서 영역 끌어서 지정", self._pick)
        self.pick.setEnabled(context.pick_rect is not None)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(_row(QLabel("X"), self.spins[0], QLabel("Y"), self.spins[1]))
        layout.addWidget(_row(QLabel("W"), self.spins[2], QLabel("H"), self.spins[3], self.pick))

    def _pick(self) -> None:
        if self.context.pick_rect is None:
            return
        result = self.context.pick_rect()
        if result:
            for spin, v in zip(self.spins, result):
                spin.setValue(int(v))

    def set_value(self, value: Any) -> None:
        rect = list(value or [0, 0, 0, 0])
        while len(rect) < 4:
            rect.append(0)
        for spin, v in zip(self.spins, rect):
            spin.setValue(int(v))

    def value(self) -> list[int]:
        return [s.value() for s in self.spins]


class ColorEditor(FieldEditor):
    def __init__(self, field: Field, context: FormContext, parent=None) -> None:
        super().__init__(field, context, parent)
        self._color = "#ffffff"
        self.button = QPushButton()
        self.button.setFixedWidth(64)
        self.button.clicked.connect(self._choose)
        self.text = QLineEdit()
        self.text.textEdited.connect(self._on_text)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_row(self.button, self.text))

    def _choose(self) -> None:
        color = QColorDialog.getColor(QColor(self._color), self, "색 선택")
        if color.isValid():
            self._color = color.name()
            self.text.setText(self._color)
            self._paint()
            self._emit()

    def _on_text(self, text: str) -> None:
        if QColor(text).isValid():
            self._color = text
            self._paint()
            self._emit()

    def _paint(self) -> None:
        self.button.setStyleSheet(f"background: {self._color}; border-radius: 6px;")

    def set_value(self, value: Any) -> None:
        self._color = str(value or "#ffffff")
        self.text.setText(self._color)
        self._paint()

    def value(self) -> str:
        return self._color


class KeyEditor(FieldEditor):
    def __init__(self, field: Field, context: FormContext, parent=None) -> None:
        super().__init__(field, context, parent)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("예: enter, ctrl+s, alt+f4")
        self.edit.textEdited.connect(lambda _: self._emit())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.edit)

    def set_value(self, value: Any) -> None:
        self.edit.setText("" if value is None else str(value))

    def value(self) -> str:
        return self.edit.text().strip()


class FileEditor(FieldEditor):
    def __init__(self, field: Field, context: FormContext, parent=None) -> None:
        super().__init__(field, context, parent)
        self.edit = QLineEdit()
        self.edit.textEdited.connect(lambda _: self._emit())
        browse = _tool_button("ellipsis", "파일 찾아보기", self._browse)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(_row(self.edit, browse))

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.field.label)
        if path:
            self.edit.setText(path)
            self._emit()

    def set_value(self, value: Any) -> None:
        self.edit.setText("" if value is None else str(value))

    def value(self) -> str:
        return self.edit.text()


class RefEditor(FieldEditor):
    """객체 / 플로우 / 상황 / 변수 하나를 고른다. 직접 입력도 허용한다."""

    def __init__(self, field: Field, context: FormContext, kind: str, parent=None) -> None:
        super().__init__(field, context, parent)
        self.kind = kind
        self.combo = QComboBox()
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.combo.setMinimumWidth(160)
        self.combo.setEditable(True)
        placeholder = {
            "var": "변수 이름 입력 또는 선택...",
            "object": "객체 이름 입력 또는 선택...",
            "flow": "플로우 선택...",
            "state": "상황 선택...",
        }.get(kind, "입력 또는 선택...")
        if self.combo.lineEdit():
            self.combo.lineEdit().setPlaceholderText(placeholder)
        self.combo.currentTextChanged.connect(lambda _: self._emit())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo)

    def refresh_choices(self) -> None:
        current = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("")
        self.combo.addItems(self.context.list_of(self.kind))
        self.combo.setCurrentText(current)
        self.combo.blockSignals(False)

    def set_value(self, value: Any) -> None:
        self.refresh_choices()
        self.combo.setCurrentText("" if value is None else str(value))

    def value(self) -> str:
        return self.combo.currentText().strip()


class NodeRefEditor(FieldEditor):
    """같은 플로우의 노드 하나를 고른다. 표시는 제목, 저장은 id."""

    def __init__(self, field: Field, context: FormContext, parent=None) -> None:
        super().__init__(field, context, parent)
        self.combo = QComboBox()
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.combo.setMinimumWidth(160)
        self.combo.currentIndexChanged.connect(lambda _: self._emit())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo)

    def _populate(self, keep: str) -> None:
        """목록을 다시 채우고 ``keep`` 을 고른 상태로 둔다.

        가리키던 노드가 지워졌어도 **선택을 버리지 않는다.** 목록을 새로 고칠 때마다
        "(없음)" 으로 되돌리면, 사용자가 손대지도 않은 이동 대상이 조용히 사라진다.
        """
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("(없음)", "")
        for node_id, label in self.context.node_choices():
            self.combo.addItem(label, node_id)
        index = self.combo.findData(keep)
        if index < 0 and keep:
            # 지워진 노드를 가리키고 있으면 그 사실이 보이도록 남겨 둔다
            self.combo.addItem(f"(없는 노드: {keep})", keep)
            index = self.combo.count() - 1
        self.combo.setCurrentIndex(max(0, index))
        self.combo.blockSignals(False)

    def refresh_choices(self) -> None:
        self._populate(self.value())

    def set_value(self, value: Any) -> None:
        self._pending = "" if value is None else str(value)
        self._populate(self._pending)

    def value(self) -> str:
        return self.combo.currentData() or ""


class RefListEditor(FieldEditor):
    """객체 여러 개 — 예외 상황 대비 다중 이미지 지정에 쓴다."""

    def __init__(self, field: Field, context: FormContext, kind: str, parent=None) -> None:
        super().__init__(field, context, parent)
        self.kind = kind
        self.list = QListWidget()
        self.list.setMaximumHeight(110)
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

        self.combo = QComboBox()
        self.combo.setEditable(True)
        add = _tool_button("plus", "추가", self._add)
        remove = _tool_button("minus", "선택 삭제", self._remove)
        up = _tool_button("up", "위로", lambda: self._move(-1))
        down = _tool_button("down", "아래로", lambda: self._move(1))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(self.list)
        layout.addWidget(_row(self.combo, add, remove, up, down))

    def refresh_choices(self) -> None:
        current = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(self.context.list_of(self.kind))
        self.combo.setCurrentText(current)
        self.combo.blockSignals(False)

    def _add(self) -> None:
        text = self.combo.currentText().strip()
        if text and text not in self._items():
            self.list.addItem(QListWidgetItem(text))
            self._emit()

    def _remove(self) -> None:
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self._emit()

    def _move(self, delta: int) -> None:
        row = self.list.currentRow()
        target = row + delta
        if row < 0 or not (0 <= target < self.list.count()):
            return
        item = self.list.takeItem(row)
        self.list.insertItem(target, item)
        self.list.setCurrentRow(target)
        self._emit()

    def _items(self) -> list[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]

    def set_value(self, value: Any) -> None:
        self.refresh_choices()
        self.list.clear()
        for entry in value or []:
            self.list.addItem(QListWidgetItem(str(entry)))

    def value(self) -> list[str]:
        return self._items()


def parse_point(text: str) -> list[int] | None:
    """``"120, 340"`` → ``[120, 340]``. 형식이 아니면 None."""
    parts = text.replace(" ", "").split(",")
    if len(parts) != 2:
        return None
    try:
        return [int(float(parts[0])), int(float(parts[1]))]
    except ValueError:
        return None


class PointListEditor(FieldEditor):
    """멀티터치 접점이나 드래그 경로처럼 좌표 여러 개.

    각 줄은 직접 고칠 수 있다. **고치는 중간 상태 때문에 좌표가 사라지면 안 된다** —
    "120, 340" 을 지우고 다시 치는 동안 "1" 만 남는 순간이 있는데, 그때 그 줄을 버리면
    사용자는 손대지 않은 좌표를 잃는다. 그래서 마지막으로 성립했던 좌표를 줄마다 들고
    있다가, 글자가 형식에 안 맞으면 빨갛게 표시만 하고 값은 지킨다.
    """

    #: 줄마다 보관하는 '마지막으로 성립한 좌표'
    POINT_ROLE = Qt.ItemDataRole.UserRole

    def __init__(self, field: Field, context: FormContext, parent=None) -> None:
        super().__init__(field, context, parent)
        self._syncing = False
        self.list = QListWidget()
        self.list.setMaximumHeight(110)

        add = _tool_button("coord", "좌표 도구로 찍어서 추가", self._pick_add)
        add.setEnabled(context.pick_point is not None)
        manual = _tool_button("plus", "0,0 추가 후 직접 수정", lambda: self._append((0, 0)))
        remove = _tool_button("minus", "선택 삭제", self._remove)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        layout.addWidget(self.list)
        layout.addWidget(_row(add, manual, remove))
        self.list.itemChanged.connect(self._on_item_changed)

    def _pick_add(self) -> None:
        if self.context.pick_point is None:
            return
        result = self.context.pick_point()
        if result:
            self._append(result)

    def _make_item(self, point) -> QListWidgetItem:
        x, y = int(point[0]), int(point[1])
        item = QListWidgetItem(f"{x}, {y}")
        item.setData(self.POINT_ROLE, [x, y])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        return item

    def _append(self, point) -> None:
        self._syncing = True
        try:
            self.list.addItem(self._make_item(point))
        finally:
            self._syncing = False
        self._emit()

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        """직접 고친 줄을 확인한다. 형식이 안 맞으면 표시만 하고 값은 지킨다."""
        if self._syncing:
            return
        point = parse_point(item.text())
        self._syncing = True
        try:
            if point is None:
                item.setForeground(style.status_color("fail"))
                item.setToolTip("x, y 형식으로 적어 주세요 (예: 120, 340). 고치기 전까지는 이전 좌표를 씁니다.")
            else:
                item.setData(self.POINT_ROLE, point)
                item.setForeground(style.TEXT)
                item.setToolTip("")
        finally:
            self._syncing = False
        self._emit()

    def _remove(self) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)
            self._emit()

    def set_value(self, value: Any) -> None:
        self._syncing = True
        try:
            self.list.clear()
            for point in value or []:
                try:
                    self.list.addItem(self._make_item(point))
                except (TypeError, ValueError, IndexError):
                    continue
        finally:
            self._syncing = False

    def value(self) -> list[list[int]]:
        """줄마다 보관해 둔 좌표를 읽는다 — 글자가 아니라."""
        out = []
        for i in range(self.list.count()):
            stored = self.list.item(i).data(self.POINT_ROLE)
            if stored:
                out.append([int(stored[0]), int(stored[1])])
        return out


def create_editor(field: Field, context: FormContext) -> FieldEditor:
    """필드 타입에 맞는 편집기를 만든다."""
    match field.type:
        case "int":
            return IntEditor(field, context)
        case "float":
            return FloatEditor(field, context)
        case "bool":
            return BoolEditor(field, context)
        case "enum":
            return EnumEditor(field, context)
        case "text":
            return TextEditor(field, context)
        case "point":
            return PointEditor(field, context)
        case "rect":
            return RectEditor(field, context)
        case "color":
            return ColorEditor(field, context)
        case "key":
            return KeyEditor(field, context)
        case "file":
            return FileEditor(field, context)
        case "object_ref":
            return RefEditor(field, context, "object")
        case "flow_ref":
            return RefEditor(field, context, "flow")
        case "state_ref":
            return RefEditor(field, context, "state")
        case "var":
            return RefEditor(field, context, "var")
        case "node_ref":
            return NodeRefEditor(field, context)
        case "object_ref_list":
            return RefListEditor(field, context, "object")
        case "point_list":
            return PointListEditor(field, context)
        case "match_threshold":
            return MatchThresholdEditor(field, context)
        case _:  # str, expr 그 외
            return StrEditor(field, context)


# ---------------------------------------------------------------- 폼


class SchemaForm(QWidget):
    """필드 목록으로 만든 폼.

    ``depends_on`` 이 걸린 필드는 조건이 맞을 때만 보인다. 값이 바뀔 때마다 다시 계산하므로
    "반복 방식: 지정 횟수" 를 고르면 횟수 칸이 나타나는 식으로 동작한다.
    """

    value_changed = pyqtSignal(str, object)

    def __init__(self, fields: list[Field], context: FormContext, parent=None) -> None:
        super().__init__(parent)
        self.fields = list(fields)
        self.context = context
        self.editors: dict[str, FieldEditor] = {}
        self._labels: dict[str, QWidget] = {}
        self._hints: dict[str, QWidget] = {}
        self._values: dict[str, Any] = {}

        self.form = QFormLayout(self)
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setSpacing(7)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        # 도크가 좁아지면 라벨을 위로 접어 가로 스크롤이 생기지 않게 한다
        self.form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)

        current_group = ""
        for f in self.fields:
            if f.group and f.group != current_group:
                current_group = f.group
                header = QLabel(f.group)
                header.setProperty("role", "hint")
                self.form.addRow(header)
            editor = create_editor(f, context)
            editor.edited.connect(lambda value, name=f.name: self._on_edited(name, value))
            label = QLabel("" if f.type == "bool" else f.label)
            label_cell = label
            if f.help:
                hint = QToolButton()
                hint.setIcon(icons.icon("info", style.TEXT_DIM, 16))
                hint.setIconSize(QSize(14, 14))
                hint.setAutoRaise(True)
                hint.setFixedSize(18, 18)
                hint.setToolTip(f.help)
                label_cell = _row(label, hint)
                self._hints[f.name] = label_cell
            self.form.addRow(label_cell, editor)
            self.editors[f.name] = editor
            self._labels[f.name] = label

    # ------------------------------------------------------------

    def load(self, params: dict[str, Any]) -> None:
        """모델 값을 폼에 채운다. 신호는 나가지 않는다."""
        self._values = dict(params or {})
        for f in self.fields:
            self.editors[f.name].load(self._values.get(f.name, f.default))
        self._update_visibility()

    def _on_edited(self, name: str, value: Any) -> None:
        self._values[name] = value
        self._update_visibility()
        self.value_changed.emit(name, value)

    def _update_visibility(self) -> None:
        for f in self.fields:
            visible = f.is_visible(self._values)
            self.editors[f.name].setVisible(visible)
            self._labels[f.name].setVisible(visible)
            if f.name in self._hints:
                self._hints[f.name].setVisible(visible)

    def refresh_choices(self) -> None:
        """객체/플로우/상황 목록이 바뀌었을 때 콤보를 다시 채운다."""
        for editor in self.editors.values():
            if isinstance(editor, (RefEditor, RefListEditor, NodeRefEditor)):
                editor.refresh_choices()


def section_label(text: str) -> QLabel:
    """패널 안에서 구획을 나누는 작은 제목."""
    label = QLabel(text)
    label.setProperty("role", "title")
    label.setStyleSheet(f"color: {style.TEXT_DIM.name()}; padding-top: 4px;")
    return label
