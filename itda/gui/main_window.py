"""메인 윈도우 — 도크 배치, 메뉴, 플로우 탭."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings, QSize, Qt, QThread, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QUndoGroup
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QWidget,
)

from itda import APP_NAME, APP_NAME_EN
from itda.core.events import BUS
from itda.core.model import TargetObject
from itda.core.project import Project, ProjectError
from itda.gui import icons, style
from itda.vision import capture
from itda.gui.canvas.scene import FlowScene
from itda.gui.canvas.view import FlowView
from itda.gui.panels.action_list import ActionListPanel
from itda.gui.panels.log_panel import LogPanel
from itda.gui.panels.object_panel import ObjectPanel
from itda.gui.panels.palette import PalettePanel
from itda.gui.panels.project_panel import ProjectPanel
from itda.gui.panels.property_panel import PropertyPanel
from itda.gui.panels.var_panel import VarPanel
from itda.gui.widgets.schema_form import FormContext


#: 최근 프로젝트 경로를 기억하는 곳
SETTINGS_ORG = "IT-DA"
SETTINGS_APP = "MacroEngine"
RECENT_KEY = "recent_project"


class MainWindow(QMainWindow):
    """편집기 본체.

    Args:
        restore_recent: 시작할 때 마지막으로 쓰던 프로젝트를 다시 여는지.
            테스트는 끄고 쓴다 — 개발자 PC 의 실제 프로젝트를 열면 안 되니까.
    """

    def __init__(self, restore_recent: bool = True) -> None:
        super().__init__()
        self.project = Project.create_default()
        self.undo_group = QUndoGroup(self)
        self.views: dict[str, FlowView] = {}
        self.demo = None
        self.editing_locked = False

        from itda.gui.run_controller import RunController

        self.runner = RunController(self)
        self.runner.started.connect(self._on_run_started)
        self.runner.finished.connect(self._on_run_finished)

        self.resize(1500, 950)
        self._build_center()
        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self._connect_runtime_signals()

        # 최근 프로젝트는 **시작할 때 한 번, 곧바로** 연다.
        # 지연시키면 사용자가 이미 뭔가 하고 있는 중에 프로젝트가 통째로 바뀐다.
        self.load_project(self._startup_project() if restore_recent else self.project)

        # 도크 크기만 창이 실제로 배치된 뒤에 정한다
        QTimer.singleShot(0, self._apply_dock_sizes)
        BUS.log(f"{APP_NAME}({APP_NAME_EN}) 시작", level="info")

    # ------------------------------------------------------------ 최근 프로젝트

    @staticmethod
    def _settings() -> QSettings:
        return QSettings(SETTINGS_ORG, SETTINGS_APP)

    def _startup_project(self) -> Project:
        """마지막으로 쓰던 프로젝트. 없거나 못 열면 새 프로젝트."""
        recent = self._settings().value(RECENT_KEY, type=str)
        if not recent or not Path(recent).exists():
            return self.project
        try:
            project = Project.load(recent)
        except Exception as e:
            BUS.log(f"최근 프로젝트를 열지 못했습니다 ({e}) — 새 프로젝트로 시작합니다",
                    level="warn")
            self._settings().remove(RECENT_KEY)  # 깨진 경로는 지운다
            return self.project
        BUS.log(f"최근 프로젝트를 열었습니다: {recent}", level="info")
        return project

    def _remember_recent(self) -> None:
        if self.project.path is not None:
            self._settings().setValue(RECENT_KEY, str(self.project.path))

    def _apply_dock_sizes(self) -> None:
        width, height = self.width(), self.height()
        side = max(230, min(300, int(width * 0.17)))
        right = max(320, min(400, int(width * 0.23)))
        self.resizeDocks(
            [self.dock_project, self.dock_palette, self.dock_objects],
            [side, side, side],
            Qt.Orientation.Horizontal,
        )
        self.resizeDocks(
            [self.dock_actions, self.dock_property], [right, right], Qt.Orientation.Horizontal
        )
        self.resizeDocks(
            [self.dock_project, self.dock_palette],
            [int(height * 0.3), int(height * 0.45)],
            Qt.Orientation.Vertical,
        )
        self.resizeDocks(
            [self.dock_actions, self.dock_property],
            [int(height * 0.25), int(height * 0.55)],
            Qt.Orientation.Vertical,
        )
        self.resizeDocks([self.dock_log], [int(height * 0.2)], Qt.Orientation.Vertical)
        self.resizeDocks(
            [self.dock_log, self.dock_vars],
            [int(width * 0.62), int(width * 0.28)],
            Qt.Orientation.Horizontal,
        )

    # ------------------------------------------------------------ 구성

    def _build_center(self) -> None:
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

    def _dock(self, title: str, widget: QWidget, area: Qt.DockWidgetArea, name: str) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.addDockWidget(area, dock)
        return dock

    def _build_docks(self) -> None:
        self.project_panel = ProjectPanel()
        self.project_panel.flow_activated.connect(self.open_flow)
        self.project_panel.project_changed.connect(self._on_project_changed)
        self.dock_project = self._dock(
            "프로젝트", self.project_panel, Qt.DockWidgetArea.LeftDockWidgetArea, "dock_project"
        )

        self.palette_panel = PalettePanel()
        self.dock_palette = self._dock(
            "팔레트", self.palette_panel, Qt.DockWidgetArea.LeftDockWidgetArea, "dock_palette"
        )

        self.object_panel = ObjectPanel()
        self.object_panel.objects_changed.connect(self._on_objects_changed)
        self.object_panel.capture_requested.connect(self.capture_object)
        self.object_panel.capture_exception_requested.connect(self.capture_exception_image)
        self.object_panel.objectify_requested.connect(self.open_objectify)
        self.dock_objects = self._dock(
            "객체", self.object_panel, Qt.DockWidgetArea.LeftDockWidgetArea, "dock_objects"
        )
        self.tabifyDockWidget(self.dock_palette, self.dock_objects)
        self.dock_palette.raise_()

        self.action_panel = ActionListPanel()
        self.action_panel.action_selected.connect(self._on_action_selected)
        self.dock_actions = self._dock(
            "노드 액션", self.action_panel, Qt.DockWidgetArea.RightDockWidgetArea, "dock_actions"
        )

        self.property_panel = PropertyPanel()
        self.property_panel.edited.connect(self._on_property_edited)
        self.dock_property = self._dock(
            "속성", self.property_panel, Qt.DockWidgetArea.RightDockWidgetArea, "dock_property"
        )

        self.log_panel = LogPanel()
        self.dock_log = self._dock(
            "로그", self.log_panel, Qt.DockWidgetArea.BottomDockWidgetArea, "dock_log"
        )
        self.log_panel.setMinimumHeight(120)

        self.var_panel = VarPanel()
        self.dock_vars = self._dock(
            "실행 상태", self.var_panel, Qt.DockWidgetArea.BottomDockWidgetArea, "dock_vars"
        )
        self.splitDockWidget(self.dock_log, self.dock_vars, Qt.Orientation.Horizontal)
        self.resizeDocks([self.dock_log, self.dock_vars], [900, 380], Qt.Orientation.Horizontal)

        for panel in (self.project_panel, self.palette_panel, self.object_panel):
            panel.setMinimumWidth(190)
        self.property_panel.setMinimumWidth(300)
        self.action_panel.setMinimumWidth(300)
        self.resizeDocks([self.dock_log], [190], Qt.Orientation.Vertical)

    def form_context(self) -> FormContext:
        """폼이 참조할 프로젝트 목록들. 항상 최신 상태를 읽도록 함수로 넘긴다."""
        return FormContext(
            objects=lambda: [o.name for o in self.project.objects.objects],
            flows=lambda: self.project.flow_keys(),
            states=lambda: [s.name for s in self.project.states.states],
            variables=self._known_variables,
            nodes=self._node_choices,
            pick_point=self.pick_point,
            pick_rect=self.pick_rect,
            pick_window=self.pick_window,
            match_default=lambda: self.project.settings.timing.match_threshold,
        )

    def _known_variables(self) -> list[str]:
        names = {v.name for v in self.project.settings.globals if v.name}
        for flow in self.project.flows.values():
            names.update(v.name for v in flow.variables if v.name)
            for node in flow.nodes:
                for action in node.actions:
                    if action.out_var:
                        names.add(action.out_var)
                    if action.type in ("set_var", "calc") and action.params.get("name"):
                        names.add(action.params["name"])
        return sorted(names)

    def _node_choices(self) -> list[tuple[str, str]]:
        scene = self.current_scene()
        if scene is None:
            return []
        return [(n.id, n.title or n.type) for n in scene.flow.nodes]

    def _build_actions(self) -> None:
        def act(text: str, shortcut, slot, tip: str = "", icon_name: str = "",
                color=None) -> QAction:
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(shortcut)
            a.setStatusTip(tip or text)
            if icon_name:
                a.setIcon(icons.icon(icon_name, color or style.TEXT))
            a.triggered.connect(slot)
            return a

        self.act_new = act("새 프로젝트", QKeySequence.StandardKey.New, self.new_project,
                           icon_name="new")
        self.act_open = act("프로젝트 열기…", QKeySequence.StandardKey.Open, self.open_project,
                            icon_name="open")
        self.act_save = act("저장", QKeySequence.StandardKey.Save, self.save_project,
                            icon_name="save")
        self.act_save_as = act("다른 이름으로 저장…", "Ctrl+Shift+S", self.save_project_as)
        self.act_quit = act("끝내기", "Ctrl+Q", self.close)

        self.act_undo = self.undo_group.createUndoAction(self, "되돌리기")
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.act_undo.setIcon(icons.icon("undo", style.TEXT))
        self.act_redo = self.undo_group.createRedoAction(self, "다시 실행")
        self.act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.act_redo.setIcon(icons.icon("redo", style.TEXT))
        # 메뉴에는 "되돌리기 연결" 처럼 대상이 붙지만, 도구모음 글자는 짧게 고정한다
        self.act_undo.setIconText("되돌리기")
        self.act_redo.setIconText("다시 실행")

        self.act_coord = act("좌표 도구", "F2", self.run_coord_tool,
                             "화면에서 좌표를 찍어 클립보드와 로그에 남깁니다",
                             icon_name="coord")
        self.act_snip = act("스크린샷 도구", "F3", self.capture_object,
                            "화면 영역을 잘라 객체로 저장합니다", icon_name="snip")
        self.act_objectify = act("객체화 도구", "F4", self.open_objectify,
                                 "스크린샷에서 아이콘·버튼·글자를 자동으로 나눠 한꺼번에 저장합니다",
                                 icon_name="objectify")

        self.act_states = act("상황 관리…", "F6", self.open_states,
                              "타겟 프로그램의 화면을 정의하고, 화면 사이 이동 방법을 등록합니다",
                              icon_name="states", color=style.ACCENT)
        self.act_timing = act("타이밍 · 자연스러움…", "F7", self.open_timing,
                              "딜레이·변동계수·좌표 허용오차와 '사람처럼 움직이기'를 설정합니다",
                              icon_name="timing")
        self.act_entries = act("멀티 플로우 설정…", "", self.open_flow_entries,
                               "동시에 실행할 플로우와 우선순위를 정합니다")

        self.act_fit = act("전체 보기", "Ctrl+0", lambda: self._with_view(lambda v: v.fit_all()),
                           icon_name="fit")
        self.act_zoom_in = act("확대", "Ctrl+=", lambda: self._with_view(lambda v: v.zoom_by(1.15)))
        self.act_zoom_out = act("축소", "Ctrl+-", lambda: self._with_view(lambda v: v.zoom_by(1 / 1.15)))
        self.act_layout = act("자동 정렬", "Ctrl+L", lambda: self._with_scene(lambda s: s.auto_layout()),
                              icon_name="layout")
        self.act_validate = act("검사", "F8", self.validate_project, icon_name="check")

        self.act_run = act("실제 실행", "F9", self.run_for_real,
                           "진짜 마우스·키보드로 실행합니다. 멈추려면 F12",
                           icon_name="play", color=style.ACCENT)
        self.act_run_multi = act("멀티 플로우 실행", "F10", self.run_multi,
                                 "자동 시작으로 표시된 플로우들을 동시에 실행합니다",
                                 icon_name="layers", color=style.ACCENT)
        self.act_watch = act("상황 감시", "F11", self.toggle_watching,
                             "지금 화면이 어떤 상황으로 판별되는지 실시간으로 표시합니다",
                             icon_name="states", color=style.STATUS_COLORS["ok"])
        self.act_watch.setCheckable(True)

        self.act_run_stop = act("실행 정지", "F12", self.stop_run,
                                "실행을 즉시 멈춥니다", icon_name="stop",
                                color=style.STATUS_COLORS["fail"])
        self.act_run_stop.setEnabled(False)

        self.act_demo = act("데모 재생", "F5", self.start_demo,
                            "실제 입력 없이 플로우 진행을 시각적으로 확인합니다",
                            icon_name="play", color=style.STATUS_COLORS["ok"])
        self.act_demo_pause = act("일시정지 / 계속", "Ctrl+F5", self.pause_demo,
                                  icon_name="pause", color=style.ACCENT)
        self.act_demo_stop = act("정지", "Shift+F5", self.stop_demo,
                                 icon_name="stop", color=style.STATUS_COLORS["fail"])
        self.act_demo_pause.setEnabled(False)
        self.act_demo_stop.setEnabled(False)

    def _build_menus(self) -> None:
        bar = self.menuBar()

        m_file = bar.addMenu("파일")
        m_file.addAction(self.act_new)
        m_file.addAction(self.act_open)
        m_file.addSeparator()
        m_file.addAction(self.act_save)
        m_file.addAction(self.act_save_as)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)

        m_edit = bar.addMenu("편집")
        m_edit.addAction(self.act_undo)
        m_edit.addAction(self.act_redo)

        m_view = bar.addMenu("보기")
        m_view.addAction(self.act_zoom_in)
        m_view.addAction(self.act_zoom_out)
        m_view.addAction(self.act_fit)
        m_view.addSeparator()
        m_view.addAction(self.act_layout)
        m_view.addSeparator()
        for dock in (
            self.dock_project,
            self.dock_palette,
            self.dock_objects,
            self.dock_actions,
            self.dock_property,
            self.dock_log,
            self.dock_vars,
        ):
            m_view.addAction(dock.toggleViewAction())

        m_tools = bar.addMenu("도구")
        m_tools.addAction(self.act_coord)
        m_tools.addAction(self.act_snip)
        m_tools.addAction(self.act_objectify)
        m_tools.addSeparator()
        m_tools.addAction(self.act_states)
        m_tools.addAction(self.act_timing)
        m_tools.addAction(self.act_entries)

        m_run = bar.addMenu("실행")
        m_run.addAction(self.act_run)
        m_run.addAction(self.act_run_multi)
        m_run.addAction(self.act_run_stop)
        m_run.addSeparator()
        m_run.addAction(self.act_watch)
        m_run.addSeparator()
        m_run.addAction(self.act_demo)
        m_run.addAction(self.act_demo_pause)
        m_run.addAction(self.act_demo_stop)
        m_run.addSeparator()
        m_run.addAction(self.act_validate)

        m_help = bar.addMenu("도움말")
        # 실행 중에 모달 대화상자를 띄우면 매크로가 그 자리에서 멈춘다 — 같이 잠근다
        self.act_about = m_help.addAction("잇다 정보", self._about)

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("주 도구모음")
        tb.setObjectName("main_toolbar")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tb.setIconSize(QSize(17, 17))
        tb.addAction(self.act_new)
        tb.addAction(self.act_open)
        tb.addAction(self.act_save)
        tb.addSeparator()
        tb.addAction(self.act_undo)
        tb.addAction(self.act_redo)
        tb.addSeparator()
        tb.addAction(self.act_layout)
        tb.addAction(self.act_fit)
        tb.addSeparator()
        tb.addAction(self.act_coord)
        tb.addAction(self.act_snip)
        tb.addAction(self.act_objectify)
        tb.addSeparator()
        tb.addAction(self.act_states)
        tb.addAction(self.act_timing)
        tb.addSeparator()
        tb.addAction(self.act_run)
        tb.addAction(self.act_run_multi)
        tb.addAction(self.act_run_stop)
        tb.addAction(self.act_watch)
        tb.addSeparator()
        tb.addAction(self.act_demo)
        tb.addAction(self.act_demo_pause)
        tb.addAction(self.act_demo_stop)
        tb.addAction(self.act_validate)

        # 긴 이름은 줄인다. 도구모음이 넘치면 뒤쪽 버튼이 넘침 메뉴로 숨는데, 하필 그
        # 뒤쪽에 **실행 정지**가 있어서 좁은 창에서 비상 정지 버튼이 사라졌다(실측).
        self.act_run_multi.setIconText("멀티 실행")

        # 자주 쓰지 않는 항목은 아이콘만 두어 도구모음이 잘리지 않게 한다 (이름은 툴팁에)
        for action in (
            self.act_undo, self.act_redo, self.act_layout, self.act_fit,
            self.act_coord, self.act_snip, self.act_objectify,
            self.act_states, self.act_timing, self.act_watch,
            self.act_demo_pause, self.act_demo_stop, self.act_validate,
        ):
            button = tb.widgetForAction(action)
            if button is not None:
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)

    def _build_statusbar(self) -> None:
        self.status_zoom = QLabel("100%")
        self.status_dirty = QLabel("")
        self.statusBar().addPermanentWidget(self.status_dirty)
        self.statusBar().addPermanentWidget(self.status_zoom)
        self.statusBar().showMessage("준비됨")

    # ------------------------------------------------------------ 프로젝트

    def load_project(self, project: Project) -> None:
        self.stop_demo()
        self.project = project
        for view in self.views.values():
            self.undo_group.removeStack(view.flow_scene.undo_stack)
        self.views.clear()
        self.tabs.clear()

        self.project_panel.set_project(project)
        self.object_panel.set_project(project)
        first = next(iter(project.flow_keys()), None)
        if first:
            self.open_flow(first)
        self._update_title()

    def new_project(self) -> None:
        if not self._confirm_discard():
            return
        self.load_project(Project.create_default())
        BUS.log("새 프로젝트를 만들었습니다", level="info")

    def open_project(self) -> None:
        if not self._confirm_discard():
            return
        folder = QFileDialog.getExistingDirectory(self, "프로젝트 폴더 열기")
        if folder:
            self.open_project_path(folder)

    def open_project_path(self, folder: str | Path) -> None:
        try:
            project = Project.load(folder)
        except ProjectError as e:
            QMessageBox.critical(self, "열 수 없음", str(e))
            return
        self.load_project(project)
        self._remember_recent()
        BUS.log(f"프로젝트를 열었습니다: {project.path}", level="info")

    def save_project(self) -> bool:
        if self.project.path is None:
            return self.save_project_as()
        try:
            self.project.save()
        except OSError as e:
            QMessageBox.critical(self, "저장 실패", str(e))
            return False
        self._remember_recent()
        self._update_title()
        BUS.log(f"저장했습니다: {self.project.path}", level="info")
        self.statusBar().showMessage("저장했습니다", 3000)
        return True

    def save_project_as(self) -> bool:
        folder = QFileDialog.getSaveFileName(self, "프로젝트 폴더로 저장", self.project.settings.name)[0]
        if not folder:
            return False
        try:
            self.project.save(Path(folder))
        except OSError as e:
            QMessageBox.critical(self, "저장 실패", str(e))
            return False
        self._remember_recent()
        self._update_title()
        BUS.log(f"저장했습니다: {self.project.path}", level="info")
        return True

    def validate_project(self) -> None:
        issues = self.project.validate()
        if not issues:
            BUS.log("검사 통과 — 문제 없음", level="info")
            self.statusBar().showMessage("검사 통과", 4000)
            return
        for issue in issues:
            BUS.log(issue.message, level="error" if issue.level == "error" else "warn",
                    flow=issue.flow, node=issue.node)
        errors = sum(1 for i in issues if i.level == "error")
        self.statusBar().showMessage(f"검사 결과: 오류 {errors}건 / 경고 {len(issues) - errors}건", 6000)
        self.dock_log.raise_()

    # ------------------------------------------------------------ 실행 시각화

    def _connect_runtime_signals(self) -> None:
        """이벤트 버스 → 캔버스 하이라이트.

        2차 실행 엔진도 같은 신호만 쏘면 되도록, GUI 쪽 수신부를 여기 한 곳에 모아 둔다.
        """
        BUS.node_status.connect(self._on_node_status)
        BUS.edge_fired.connect(self._on_edge_fired)

    def _scene_of(self, flow_key: str):
        view = self.views.get(flow_key)
        return view.flow_scene if view else None

    def _on_node_status(self, flow_key: str, node_id: str, status: str) -> None:
        scene = self._scene_of(flow_key)
        if scene is not None:
            scene.set_node_status(node_id, status)

    def _on_edge_fired(self, flow_key: str, edge_id: str) -> None:
        scene = self._scene_of(flow_key)
        if scene is not None:
            scene.fire_edge(edge_id)

    def run_for_real(self) -> None:
        """진짜 마우스·키보드로 실행한다. 되돌릴 수 없는 동작이므로 한 번 확인을 받는다."""
        scene = self.current_scene()
        if scene is None or self.runner.running:
            return

        issues = [i for i in self.project.validate() if i.level == "error"]
        if issues:
            QMessageBox.warning(
                self, "먼저 오류를 고치세요",
                "검사에서 오류가 있습니다:\n\n" + "\n".join(f"· {i.message}" for i in issues[:5]),
            )
            self.validate_project()
            return

        hotkey = self.runner.install_hotkey()
        stop_hint = "F12" if hotkey else "정지 버튼(F12 전역 등록 실패 — 잇다 창에서만 동작)"
        answer = QMessageBox.question(
            self,
            "실제 실행",
            f"'{scene.flow_key}' 플로우를 <b>진짜 마우스·키보드로</b> 실행합니다.<br><br>"
            f"실행 중에는 조작이 자동으로 이루어집니다.<br>"
            f"멈추려면 <b>{stop_hint}</b> 를 누르세요.<br><br>계속할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.runner.release_hotkey()
            return

        self.stop_demo()
        scene.clear_statuses()
        self.var_panel.clear()
        self.dock_log.raise_()

        try:
            self.runner.run(self.project, scene.flow_key)
        finally:
            self.runner.release_hotkey()

    def run_multi(self) -> None:
        """여러 플로우를 동시에 실행한다. 입력 장치는 우선순위대로 나눠 쓴다."""
        if self.runner.running:
            return

        entries = [e for e in self.project.settings.entries if e.enabled and e.autostart]
        if not entries:
            QMessageBox.information(
                self, "자동 시작 플로우가 없습니다",
                "도구 → 멀티 플로우 설정에서 동시에 실행할 플로우에 '자동 시작' 을 켜세요.",
            )
            return

        hotkey = self.runner.install_hotkey()
        stop_hint = "F12" if hotkey else "정지 버튼"
        listing = "\n".join(f"· {e.flow} (우선순위 {e.priority})" for e in entries)
        answer = QMessageBox.question(
            self,
            "멀티 플로우 실행",
            f"다음 플로우를 <b>동시에, 진짜 마우스·키보드로</b> 실행합니다.<br><br>"
            f"<pre>{listing}</pre>"
            f"우선순위가 높은 쪽이 입력 장치를 먼저 씁니다.<br>"
            f"멈추려면 <b>{stop_hint}</b>.<br><br>계속할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.runner.release_hotkey()
            return

        self.stop_demo()
        self.var_panel.clear()
        self.dock_log.raise_()
        self.runner.run_multi(self.project)

    def toggle_watching(self) -> None:
        """상황 감시를 켜고 끈다.

        상황 정의가 제대로 됐는지 확인하는 데 쓴다 — 대상 프로그램의 화면을 옮겨 다니면
        아래 '실행 상태' 의 배지가 따라 바뀐다.
        """
        if self.runner.watching:
            self.runner.stop_watching()
        else:
            self.runner.start_watching(self.project)
        self.act_watch.setChecked(self.runner.watching)

    def stop_run(self) -> None:
        self.runner.stop()

    def _on_run_started(self, flow_key: str) -> None:
        self.act_run.setEnabled(False)
        self.act_run_multi.setEnabled(False)
        self.act_run_stop.setEnabled(True)
        self.set_editing_locked(True)
        self.statusBar().showMessage(f"실행 중 — 편집 잠금. 멈추려면 F12  ({flow_key})")

    def _on_run_finished(self, flow_key: str, ok: bool) -> None:
        self.act_run.setEnabled(True)
        self.act_run_multi.setEnabled(True)
        self.act_run_stop.setEnabled(False)
        self.set_editing_locked(False)
        self.runner.release_hotkey()
        self.statusBar().showMessage(
            f"실행 {'완료' if ok else '중단/실패'} — {flow_key}", 8000
        )

    # ------------------------------------------------------------ 실행 중 잠금

    #: 실행 중에 잠그는 동작들 — 모델을 바꾸거나, 화면/입력을 매크로와 다투는 것들
    LOCKED_ACTIONS = (
        "act_new", "act_open", "act_save", "act_save_as",
        "act_undo", "act_redo", "act_layout",
        "act_coord", "act_snip", "act_objectify",
        "act_states", "act_timing", "act_entries",
        "act_demo", "act_about",
    )

    def set_editing_locked(self, locked: bool) -> None:
        """실행 중에는 편집을 잠근다.

        실행은 GUI 스레드에서 돌면서 정지 버튼이 살아 있도록 중간중간 이벤트를 처리한다
        (:meth:`RunController._tick`). 그 틈에 노드를 지우거나 프로젝트를 새로 열면, 엔진이
        들고 있던 모델과 화면이 어긋나 조용히 잘못 동작하거나 죽는다. 그래서 실행하는 동안은
        **읽기 전용**으로 만든다 — 실행 상황은 그대로 보이고, 로그·변수 패널도 살아 있다.
        """
        self.editing_locked = locked
        for name in self.LOCKED_ACTIONS:
            action = getattr(self, name, None)
            if action is not None:
                action.setEnabled(not locked)

        for dock in (self.dock_project, self.dock_palette, self.dock_objects,
                     self.dock_actions, self.dock_property):
            dock.widget().setEnabled(not locked)

        for view in self.views.values():
            view.set_read_only(locked)

        # 탭을 닫으면 씬이 통째로 사라진다. 실행 중에는 닫지 못하게 한다.
        self.tabs.setTabsClosable(not locked)

    def start_demo(self) -> None:
        from itda.engine.demo import DemoRunner

        scene = self.current_scene()
        if scene is None:
            return
        if self.demo is not None and self.demo.is_running:
            self.demo.pause()
            return

        self.stop_demo()
        scene.clear_statuses()
        self.var_panel.clear()

        self.demo = DemoRunner(self.project, scene.flow, scene.flow_key, self)
        self.demo.running_changed.connect(self._on_demo_running)
        self.demo.finished.connect(self._on_demo_finished)
        if not self.demo.start():
            self.demo = None
            self.dock_log.raise_()
            return
        self.dock_vars.raise_()

    def pause_demo(self) -> None:
        if self.demo is not None:
            self.demo.pause()

    def stop_demo(self) -> None:
        if self.demo is not None:
            self.demo.stop()
            self.demo = None
        scene = self.current_scene()
        if scene is not None:
            scene.clear_statuses()

    def _on_demo_running(self, running: bool) -> None:
        self.act_demo.setText("계속" if not running and self.demo else "데모 재생")
        self.act_demo_pause.setEnabled(self.demo is not None)
        self.act_demo_stop.setEnabled(self.demo is not None)

    def _on_demo_finished(self) -> None:
        self.act_demo.setText("데모 재생")
        self.act_demo_pause.setEnabled(False)
        self.act_demo_stop.setEnabled(False)

    # ------------------------------------------------------------ 작업 도구

    def _hidden_during(self, fn):
        """도구가 화면을 얼리는 동안 잇다 창을 **전부** 화면에서 치운다.

        메인 창만 치우면 노드 편집 창 같은 대화상자가 얼어붙은 배경에 그대로 찍혀, 정작
        찍으려던 대상 프로그램을 가린다. (부모 창을 숨겨도 대화상자는 화면에 남는다.)

        대화상자는 **숨기면 안 된다** — Qt 의 QDialog 는 감춰지는 순간 ``exec()`` 루프를
        끝내 버려서, 도구를 쓰고 나면 편집 창이 닫혀 있다. 대신 투명하게 만든다. 화면
        캡처에서 똑같이 사라지면서 창은 살아 있다(둘 다 실제 화면에서 확인함).
        """
        windows = [
            w for w in QApplication.topLevelWidgets() if w.isVisible() and w.window() is w
        ]
        dialogs = [w for w in windows if isinstance(w, QDialog)]
        plain = [w for w in windows if not isinstance(w, QDialog)]

        for dialog in dialogs:
            dialog.setWindowOpacity(0.0)
        for widget in plain:
            widget.hide()
        if windows:
            QApplication.processEvents()
            QThread.msleep(160)  # 창이 실제로 사라질 시간을 준다
        try:
            return fn()
        finally:
            for widget in plain:
                widget.show()
            for dialog in dialogs:
                dialog.setWindowOpacity(1.0)
            if windows:
                # 맨 앞에 있던 창(보통 대화상자)이 다시 앞으로 와야 편집을 이어갈 수 있다.
                windows[-1].activateWindow()
                windows[-1].raise_()

    def pick_point(self) -> tuple[int, int] | None:
        from itda.gui.tools.coord_picker import pick_point

        return self._hidden_during(pick_point)

    def pick_rect(self) -> tuple[int, int, int, int] | None:
        from itda.gui.tools.snip_tool import pick_rect

        return self._hidden_during(pick_rect)

    def pick_window(self) -> tuple[str, int, int, int, int] | None:
        from itda.gui.tools.window_picker import pick_window

        picked = self._hidden_during(pick_window)
        if picked is None:
            return None
        return (picked.title, picked.x, picked.y, picked.width, picked.height)

    def run_coord_tool(self) -> None:
        point = self.pick_point()
        if point is None:
            return
        text = f"{point[0]}, {point[1]}"
        QApplication.clipboard().setText(text)
        BUS.log(f"좌표 {text} (클립보드에 복사됨)", level="info")
        self.statusBar().showMessage(f"좌표 {text} 를 클립보드에 복사했습니다", 5000)

    def capture_object(self) -> None:
        """화면 영역을 잘라 객체 하나로 저장한다."""
        from itda.gui.tools.snip_tool import snip

        if not self._require_saved_project():
            return
        result = self._hidden_during(snip)
        if result is None:
            return

        name, ok = QInputDialog.getText(self, "객체 이름", "이름:", text="새 객체")
        if not ok or not name.strip():
            return
        tags_text, _ = QInputDialog.getText(self, "태그", "쉼표로 구분 (건너뛰려면 비워 두세요):")

        temp = self.project.path / "objects" / "img" / ".capture.tmp.png"
        capture.save_pixmap(result.pixmap, temp)
        try:
            relative = self.project.import_image(temp, name.strip())
        finally:
            temp.unlink(missing_ok=True)  # 실패해도 찌꺼기를 남기지 않는다

        obj = TargetObject(
            name=name.strip(),
            tags=[t.strip() for t in (tags_text or "").split(",") if t.strip()],
            images=[relative],
            note=f"스크린샷 도구로 생성 · 원본 좌표 {result.rect}",
        )
        created = self.object_panel.add_object(obj)
        self.dock_objects.raise_()
        BUS.log(f"객체 '{created.name}' 를 저장했습니다", level="info")

    def capture_exception_image(self) -> None:
        """현재 객체에 스크린샷 캡처로 예외 이미지를 추가한다."""
        from itda.gui.tools.snip_tool import snip

        current_obj = self.object_panel.current_object()
        if current_obj is None:
            QMessageBox.information(self, "객체 선택 필요", "예외 이미지를 추가할 객체를 먼저 선택하세요.")
            return

        if not self._require_saved_project():
            return
        result = self._hidden_during(snip)
        if result is None:
            return

        temp = self.project.path / "objects" / "img" / ".capture_exp.tmp.png"
        capture.save_pixmap(result.pixmap, temp)
        try:
            relative = self.project.import_image(temp, f"{current_obj.name}_exp")
        finally:
            temp.unlink(missing_ok=True)  # 실패해도 찌꺼기를 남기지 않는다

        current_obj.images.append(relative)
        self.object_panel.object_updated(current_obj)
        BUS.log(f"객체 '{current_obj.name}'에 예외 이미지를 추가했습니다", level="info")

    def open_objectify(self) -> None:
        """스크린샷을 자동 분할해 여러 객체를 한꺼번에 만든다."""
        from itda.gui.tools.objectify_dialog import ObjectifyDialog
        from itda.gui.tools.snip_tool import snip

        if not self._require_saved_project():
            return
        result = self._hidden_during(snip)
        if result is None:
            return

        image = capture.pixmap_to_bgr(result.pixmap)
        dialog = ObjectifyDialog(image, self.project, self)
        dialog.exec()
        if dialog.saved:
            self.object_panel.reload()
            self._on_objects_changed()
            self.dock_objects.raise_()
            BUS.log(f"객체화 도구로 {len(dialog.saved)}개 객체를 만들었습니다", level="info")

    def _require_saved_project(self) -> bool:
        """이미지를 넣으려면 프로젝트 폴더가 있어야 한다."""
        if self.project.path is not None:
            return True
        answer = QMessageBox.question(
            self,
            "프로젝트를 먼저 저장",
            "이미지를 프로젝트 폴더에 넣어야 합니다. 지금 저장할까요?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
        return self.save_project_as()

    def _on_objects_changed(self) -> None:
        self.property_panel.refresh_choices()
        self._update_title()

    # ------------------------------------------------------------ 설정 대화상자

    def open_states(self) -> None:
        from itda.gui.dialogs.state_dialog import StateDialog

        dialog = StateDialog(self.project, self.form_context(), self)
        dialog.exec()
        self.property_panel.refresh_choices()
        for scene in (view.flow_scene for view in self.views.values()):
            for item in scene.node_items.values():
                item.refresh()
        self._update_title()

    def open_timing(self) -> None:
        from itda.gui.dialogs.timing_dialog import TimingProfileDialog

        dialog = TimingProfileDialog(self.project, self)
        if dialog.exec():
            from itda.core.humanize import describe

            profile = self.project.settings.timing
            BUS.log(
                "타이밍 프로파일 적용 — "
                f"배율 {profile.delay_scale}배 · 변동 ±{int(profile.jitter_pct * 100)}% · "
                f"좌표 오차 {profile.click_offset_px}px",
                level="info",
            )
            BUS.log(f"사람처럼 움직이기 — {describe(self.project.settings.human)}", level="info")
            # 상속 중인 항목의 표시값이 함께 바뀌도록 현재 선택을 다시 그린다
            scene = self.current_scene()
            if scene is not None:
                scene.selectionChanged.emit()
            self._update_title()

    def open_flow_entries(self) -> None:
        from itda.gui.dialogs.flow_entries_dialog import FlowEntriesDialog

        dialog = FlowEntriesDialog(self.project, self)
        if dialog.exec():
            self.project_panel.reload()
            self._update_title()

    # ------------------------------------------------------------ 플로우 탭

    def open_flow(self, key: str) -> None:
        if key in self.views:
            self.tabs.setCurrentWidget(self.views[key])
            return
        flow = self.project.flow(key)
        if flow is None:
            return
        scene = FlowScene(self.project, flow, key)
        scene.model_changed.connect(self._on_model_changed)
        scene.selection_changed.connect(self._on_selection_changed)
        scene.node_double_clicked.connect(self._on_node_double_clicked)

        view = FlowView(scene)
        view.zoom_changed.connect(lambda z: self.status_zoom.setText(f"{int(z * 100)}%"))
        view.status_message.connect(lambda m: self.statusBar().showMessage(m, 4000))
        if self.editing_locked:
            view.set_read_only(True)

        self.undo_group.addStack(scene.undo_stack)
        self.views[key] = view
        self.tabs.addTab(view, flow.name or key)
        self.tabs.setCurrentWidget(view)
        self._bind_panels(scene)
        QTimer.singleShot(0, view.fit_all)

    def _bind_panels(self, scene: FlowScene) -> None:
        """속성/액션 패널을 현재 씬에 연결한다."""
        self.property_panel.set_scene(scene, self.form_context())
        self.action_panel.set_scene(scene)

    def _close_tab(self, index: int) -> None:
        widget = self.tabs.widget(index)
        for key, view in list(self.views.items()):
            if view is widget:
                self.undo_group.removeStack(view.flow_scene.undo_stack)
                del self.views[key]
                break
        self.tabs.removeTab(index)

    def current_view(self) -> FlowView | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, FlowView) else None

    def current_scene(self) -> FlowScene | None:
        view = self.current_view()
        return view.flow_scene if view else None

    def _with_view(self, fn) -> None:
        view = self.current_view()
        if view:
            fn(view)

    def _with_scene(self, fn) -> None:
        scene = self.current_scene()
        if scene:
            fn(scene)

    # ------------------------------------------------------------ 이벤트

    def _on_tab_changed(self, _index: int) -> None:
        scene = self.current_scene()
        if scene:
            self.undo_group.setActiveStack(scene.undo_stack)
            self._bind_panels(scene)
            scene.selectionChanged.emit()

    def _on_model_changed(self) -> None:
        self._update_title()

    def _on_project_changed(self) -> None:
        self._update_title()

    def _on_selection_changed(self, kind: str, target) -> None:
        if kind == "node" and target is not None:
            self.property_panel.show_node(target)
            self.action_panel.set_node(target)
            self.statusBar().showMessage(f"선택: {target.title}", 2500)
        else:
            self.property_panel.show_none()
            self.action_panel.set_node(None)

    def _on_action_selected(self, node, action) -> None:
        if node is None:
            return
        if action is None:
            self.property_panel.show_node(node)
        else:
            self.property_panel.show_action(node, action)
            self.dock_property.raise_()

    def _on_property_edited(self) -> None:
        """속성이 바뀌면 액션 요약과 창 제목 표시를 갱신한다.

        목록을 다시 만들지 않고 글자만 바꾼다 — 그래야 속성 폼에 타이핑하는 중에도
        포커스가 유지된다.
        """
        self.action_panel.refresh_labels()
        self._update_title()

    def _on_node_double_clicked(self, node_id: str) -> None:
        """노드를 더블클릭하면 그 노드만 따로 편집한다."""
        from itda.gui.dialogs.node_editor_dialog import NodeEditorDialog

        scene = self.current_scene()
        if scene is None:
            return
        node = scene.flow.node(node_id)
        if node is None:
            return

        dialog = NodeEditorDialog(scene, node, self.form_context(), self)
        dialog.exec()

        # 창에서 바꾼 내용을 캔버스와 패널에 반영한다
        item = scene.node_items.get(node_id)
        if item is not None:
            item.refresh()
        scene.sync_edges_of(node_id)
        self.action_panel.set_node(node)
        self.property_panel.show_node(node)
        self._update_title()

    def _update_title(self) -> None:
        mark = " •" if self.project.dirty else ""
        where = str(self.project.path) if self.project.path else "저장 안 됨"
        self.setWindowTitle(f"{self.project.display_name}{mark} — {APP_NAME}({APP_NAME_EN})  [{where}]")
        self.status_dirty.setText("저장 필요" if self.project.dirty else "")
        for key, view in self.views.items():
            flow = self.project.flow(key)
            if flow:
                self.tabs.setTabText(self.tabs.indexOf(view), flow.name or key)

    def _about(self) -> None:
        QMessageBox.about(
            self,
            f"{APP_NAME} 정보",
            f"<b>{APP_NAME} ({APP_NAME_EN})</b><br>"
            "플로우차트 기반 경량 범용 매크로 도구<br><br>"
            "타겟 프로그램의 상황을 먼저 인식하고, 필요한 화면으로 스스로 이동한 뒤 동작합니다.",
        )

    # ------------------------------------------------------------ 종료

    def _confirm_discard(self) -> bool:
        if not self.project.dirty:
            return True
        answer = QMessageBox.question(
            self,
            "저장하지 않은 변경",
            "변경 내용을 저장할까요?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return answer == QMessageBox.StandardButton.Discard

    def closeEvent(self, event) -> None:
        if self.runner.running:
            # 실행은 GUI 스레드에서 돌기 때문에, 여기서 창을 닫으면 엔진이 아직 쓰고 있는
            # 씬과 패널이 사라진다. 정지 신호만 보내고 닫기는 미룬다.
            self.runner.stop()
            self.statusBar().showMessage("실행을 멈추는 중입니다 — 멈춘 뒤 다시 닫아 주세요", 6000)
            event.ignore()
            return

        self.runner.stop()
        self.runner.stop_watching()
        self.runner.release_hotkey()
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
