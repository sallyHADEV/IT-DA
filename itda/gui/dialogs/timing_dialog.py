"""타이밍 · 자연스러움 대화상자.

두 탭으로 나뉜다.

* **타이밍 · 허용오차** — "원클릭 전체 적용" 쪽. 여기 값을 바꾸면 상속 중인 모든 노드·액션의
  실제 값이 한꺼번에 바뀐다. 개별 제어는 각 항목의 '상속' 체크를 끄면 된다.
* **사람처럼 움직이기** — 스위치로 켜고 끄며, 옆의 미리보기가 실제 궤적을 바로 보여 준다.
  기계적인 직선·일정 속도는 안티매크로 탐지의 1차 표적이다.
"""

from __future__ import annotations

from dataclasses import replace

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from itda.core.humanize import HumanProfile, describe
from itda.core.timing import TimingProfile
from itda.gui.dialogs import localize
from itda.gui.widgets.path_preview import PathPreview
from itda.gui.widgets.toggle_switch import SwitchRow

#: (속성 이름, 아이콘, 제목, 설명)
HUMAN_SWITCHES = [
    ("curve", "curve", "곡선 궤적",
     "직선 대신 베지에 곡선으로 완만하게 휘어 갑니다. 사람 손의 가장 큰 특징입니다."),
    ("speed_variation", "speed", "가속 · 감속",
     "출발과 도착에서 느리고 중간에서 빠릅니다. 속도 곡선도 매번 조금씩 달라집니다."),
    ("overshoot", "overshoot", "오버슈트",
     "목표를 살짝 지나쳤다가 되돌아옵니다. 빠르게 움직일 때 사람이 자주 하는 실수입니다."),
    ("micro_pause", "pause", "미세 정지",
     "이동 도중 짧게 멈칫합니다."),
    ("typing_rhythm", "keyboard", "타이핑 리듬",
     "글자마다 입력 간격을 다르게 하고, 가끔 생각하듯 멈춥니다."),
    ("click_hold_variation", "cursor", "클릭 시간 변화",
     "누르고 있는 시간을 매번 다르게 합니다."),
    ("idle_drift", "drift", "대기 중 드리프트",
     "기다리는 동안 커서가 아주 조금씩 흔들립니다."),
]


class TimingProfileDialog(QDialog):
    def __init__(self, project, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("타이밍 · 자연스러움")
        self.project = project
        self.before_timing = replace(project.settings.timing)
        self.before_human = replace(project.settings.human)
        self.human = replace(project.settings.human)
        self.resize(760, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_timing_tab(), "타이밍 · 허용오차")
        self.tabs.addTab(self._build_human_tab(), "사람처럼 움직이기")
        layout.addWidget(self.tabs, 1)

        buttons = localize(
            QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
        )
        reset = QPushButton("기본값으로")
        reset.clicked.connect(self.reset_defaults)
        buttons.addButton(reset, QDialogButtonBox.ButtonRole.ResetRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ------------------------------------------------------------ 타이밍 탭

    def _build_timing_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        intro = QLabel(
            "상속을 켜 둔 모든 동작에 즉시 적용됩니다.\n"
            "특정 동작만 다르게 하려면 그 동작의 속성에서 '상속'을 끄세요."
        )
        intro.setProperty("role", "hint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(8)
        profile = self.project.settings.timing

        self.delay_scale = QDoubleSpinBox()
        self.delay_scale.setRange(0.1, 10.0)
        self.delay_scale.setSingleStep(0.1)
        self.delay_scale.setValue(profile.delay_scale)
        self.delay_scale.setSuffix(" 배")
        form.addRow("딜레이 배율", self.delay_scale)

        self.jitter = QDoubleSpinBox()
        self.jitter.setRange(0.0, 1.0)
        self.jitter.setSingleStep(0.05)
        self.jitter.setDecimals(2)
        self.jitter.setValue(profile.jitter_pct)
        self.jitter.setToolTip("0.15 면 딜레이를 매번 ±15% 안에서 흔듭니다.")
        form.addRow("시간 변동계수", self.jitter)

        self.click_offset = QSpinBox()
        self.click_offset.setRange(0, 200)
        self.click_offset.setValue(profile.click_offset_px)
        self.click_offset.setSuffix(" px")
        self.click_offset.setToolTip("클릭 좌표를 이 반경 안에서 매번 조금씩 다르게 찍습니다.")
        form.addRow("좌표 허용오차", self.click_offset)

        self.move_duration = QSpinBox()
        self.move_duration.setRange(0, 5000)
        self.move_duration.setValue(profile.move_duration_ms)
        self.move_duration.setSuffix(" ms")
        form.addRow("마우스 이동 시간", self.move_duration)

        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.1, 1.0)
        self.threshold.setSingleStep(0.01)
        self.threshold.setDecimals(2)
        self.threshold.setValue(profile.match_threshold)
        form.addRow("이미지 매칭 임계값", self.threshold)

        self.pre_ms = QSpinBox()
        self.pre_ms.setRange(0, 600000)
        self.pre_ms.setValue(profile.default_pre_ms)
        self.pre_ms.setSuffix(" ms")
        form.addRow("기본 선딜레이", self.pre_ms)

        self.post_ms = QSpinBox()
        self.post_ms.setRange(0, 600000)
        self.post_ms.setValue(profile.default_post_ms)
        self.post_ms.setSuffix(" ms")
        form.addRow("기본 후딜레이", self.post_ms)

        self.timeout_ms = QSpinBox()
        self.timeout_ms.setRange(0, 600000)
        self.timeout_ms.setValue(profile.default_timeout_ms)
        self.timeout_ms.setSuffix(" ms")
        form.addRow("기본 제한시간", self.timeout_ms)

        layout.addLayout(form)
        layout.addStretch(1)
        return page

    # ------------------------------------------------------------ 자연스러움 탭

    def _build_human_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(9)

        intro = QLabel(
            "기계가 만든 입력은 직선으로 움직이고 속도가 일정합니다. 안티매크로 탐지는 그 규칙성을 봅니다."
        )
        intro.setProperty("role", "hint")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.master = SwitchRow(
            "cursor",
            "사람처럼 움직이기",
            "이 스위치를 끄면 아래 설정과 무관하게 직선·일정 속도로 움직입니다.",
            checked=self.human.enabled,
        )
        self.master.toggled.connect(self._on_master_toggled)
        layout.addWidget(self.master)

        body = QHBoxLayout()
        body.setSpacing(10)

        switches = QVBoxLayout()
        switches.setSpacing(5)
        self.switch_rows: dict[str, SwitchRow] = {}
        for attr, icon_name, title, description in HUMAN_SWITCHES:
            row = SwitchRow(icon_name, title, description, checked=getattr(self.human, attr))
            row.toggled.connect(lambda checked, a=attr: self._on_switch(a, checked))
            switches.addWidget(row)
            self.switch_rows[attr] = row
        switches.addStretch(1)
        body.addLayout(switches, 3)

        right = QVBoxLayout()
        right.setSpacing(6)
        preview_title = QLabel("궤적 미리보기")
        preview_title.setProperty("role", "title")
        right.addWidget(preview_title)

        self.preview = PathPreview(self.human)
        right.addWidget(self.preview)

        curve_label = QLabel("휘는 정도")
        curve_label.setProperty("role", "hint")
        right.addWidget(curve_label)

        self.curvature = QSlider(Qt.Orientation.Horizontal)
        self.curvature.setRange(0, 60)
        self.curvature.setValue(int(self.human.curvature * 100))
        self.curvature.valueChanged.connect(self._on_curvature)
        right.addWidget(self.curvature)

        self.summary = QLabel(describe(self.human))
        self.summary.setProperty("role", "hint")
        self.summary.setWordWrap(True)
        right.addWidget(self.summary)

        reroll = QPushButton("다시 그리기")
        reroll.setToolTip("같은 설정이어도 매번 다른 궤적이 나옵니다")
        reroll.clicked.connect(lambda: self.preview.reroll())
        right.addWidget(reroll)
        right.addStretch(1)
        body.addLayout(right, 2)

        layout.addLayout(body, 1)
        self._on_master_toggled(self.human.enabled)
        return page

    # ------------------------------------------------------------ 반응

    def _on_master_toggled(self, checked: bool) -> None:
        self.human.enabled = checked
        for row in self.switch_rows.values():
            row.setSubEnabled(checked)
        self.curvature.setEnabled(checked and self.human.curve)
        self._refresh_preview()

    def _on_switch(self, attr: str, checked: bool) -> None:
        setattr(self.human, attr, checked)
        if attr == "curve":
            self.curvature.setEnabled(self.human.enabled and checked)
        self._refresh_preview()

    def _on_curvature(self, value: int) -> None:
        self.human.curvature = value / 100
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        self.preview.set_profile(self.human)
        self.summary.setText(describe(self.human))

    # ------------------------------------------------------------ 값

    def reset_defaults(self) -> None:
        if self.tabs.currentIndex() == 0:
            self.load(TimingProfile())
        else:
            self.load_human(HumanProfile())

    def load(self, profile: TimingProfile) -> None:
        self.delay_scale.setValue(profile.delay_scale)
        self.jitter.setValue(profile.jitter_pct)
        self.click_offset.setValue(profile.click_offset_px)
        self.move_duration.setValue(profile.move_duration_ms)
        self.threshold.setValue(profile.match_threshold)
        self.pre_ms.setValue(profile.default_pre_ms)
        self.post_ms.setValue(profile.default_post_ms)
        self.timeout_ms.setValue(profile.default_timeout_ms)

    def load_human(self, profile: HumanProfile) -> None:
        self.human = replace(profile)
        self.master.setChecked(profile.enabled)
        for attr, row in self.switch_rows.items():
            row.setChecked(getattr(profile, attr))
        self.curvature.setValue(int(profile.curvature * 100))
        self._on_master_toggled(profile.enabled)

    def result_profile(self) -> TimingProfile:
        return TimingProfile(
            delay_scale=round(self.delay_scale.value(), 2),
            jitter_pct=round(self.jitter.value(), 2),
            click_offset_px=self.click_offset.value(),
            move_duration_ms=self.move_duration.value(),
            match_threshold=round(self.threshold.value(), 2),
            default_pre_ms=self.pre_ms.value(),
            default_post_ms=self.post_ms.value(),
            default_timeout_ms=self.timeout_ms.value(),
        )

    def result_human(self) -> HumanProfile:
        return replace(self.human)

    def accept(self) -> None:
        self.project.settings.timing = self.result_profile()
        self.project.settings.human = self.result_human()
        self.project.mark_dirty()
        super().accept()
