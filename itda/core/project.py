"""프로젝트 폴더 입출력.

프로젝트는 폴더 하나다. 플로우 하나가 파일 하나이므로 탐색기에서 복사해 다른 프로젝트에
붙여 넣기만 해도 모듈로 재사용된다.

    MyProject/
      project.json
      flows/main.flow.json
      objects/objects.json
      objects/img/*.png
      states/states.json
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from itda import SCHEMA_VERSION
from itda.core import registry
from itda.core.ids import slugify, unique_name
from itda.core.model import (
    Flow,
    FlowEntry,
    Node,
    ObjectRepo,
    ProjectSettings,
    StateGraph,
    TargetObject,
)
from itda.core.serde import from_dict, to_dict

PROJECT_FILE = "project.json"
FLOWS_DIR = "flows"
OBJECTS_DIR = "objects"
OBJECT_IMG_DIR = "objects/img"
STATES_DIR = "states"
FLOW_SUFFIX = ".flow.json"

#: 플로우 호출 중첩 한계. 검사와 실행 엔진이 함께 쓴다.
MAX_SUBFLOW_DEPTH = 12


class ProjectError(Exception):
    pass


@dataclass
class Issue:
    """유효성 검사 결과 한 건."""

    level: str  # error | warn
    message: str
    flow: str = ""
    node: str = ""

    def __str__(self) -> str:
        where = " / ".join(x for x in (self.flow, self.node) if x)
        return f"[{self.level}] {self.message}" + (f" ({where})" if where else "")


class Project:
    """열려 있는 프로젝트 하나. GUI 가 들고 다니는 최상위 객체."""

    def __init__(
        self,
        settings: ProjectSettings | None = None,
        path: Path | None = None,
    ) -> None:
        self.settings = settings or ProjectSettings()
        self.path: Path | None = Path(path) if path else None
        #: 파일 이름(확장자 제외) → Flow. 이 키가 플로우 참조에 쓰인다.
        self.flows: dict[str, Flow] = {}
        self.objects = ObjectRepo()
        self.states = StateGraph()
        self._dirty = False

    # ------------------------------------------------------------ 생성

    @classmethod
    def create_default(cls, name: str = "새 프로젝트") -> Project:
        """시작 노드 하나가 놓인 빈 프로젝트."""
        proj = cls(ProjectSettings(name=name, schema_version=SCHEMA_VERSION))
        flow = Flow(name="main")
        flow.add_node(Node(type="start", title="시작", x=-260, y=-40))
        flow.add_node(Node(type="action_group", title="새 동작", x=-20, y=-60))
        first, second = flow.nodes[0], flow.nodes[1]
        flow.connect(first.id, "ok", second.id)
        proj.flows["main"] = flow
        proj.settings.entries.append(FlowEntry(flow="main", priority=0, autostart=True))
        proj.normalize()
        # 방금 만든 빈 프로젝트는 잃을 것이 없다. 손대기 전까지 저장을 묻지 않는다.
        proj.mark_dirty(False)
        return proj

    # ------------------------------------------------------------ 상태

    @property
    def dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self, dirty: bool = True) -> None:
        self._dirty = dirty

    @property
    def display_name(self) -> str:
        return self.settings.name or (self.path.name if self.path else "이름 없음")

    # ------------------------------------------------------------ 플로우 관리

    def flow(self, key: str) -> Flow | None:
        return self.flows.get(key)

    def flow_keys(self) -> list[str]:
        return sorted(self.flows)

    def add_flow(self, name: str = "새 플로우") -> tuple[str, Flow]:
        key = unique_name(slugify(name, "flow"), set(self.flows))
        flow = Flow(name=name if name else key)
        flow.add_node(Node(type="start", title="시작", x=-260, y=-40))
        self.flows[key] = flow
        self.mark_dirty()
        return key, flow

    def remove_flow(self, key: str) -> Flow | None:
        flow = self.flows.pop(key, None)
        if flow is not None:
            self.settings.entries = [e for e in self.settings.entries if e.flow != key]
            self.mark_dirty()
        return flow

    def rename_flow(self, key: str, new_key: str) -> str:
        """플로우 파일 키를 바꾸고 참조도 함께 고친다."""
        if key not in self.flows or key == new_key:
            return key
        new_key = unique_name(slugify(new_key, "flow"), set(self.flows) - {key})
        self.flows[new_key] = self.flows.pop(key)
        for f in self.flows.values():
            for n in f.nodes:
                if n.type == "subflow" and n.params.get("flow") == key:
                    n.params["flow"] = new_key
                for a in n.actions:
                    if a.type == "run_flow" and a.params.get("flow") == key:
                        a.params["flow"] = new_key
        for e in self.settings.entries:
            if e.flow == key:
                e.flow = new_key
        self.mark_dirty()
        return new_key

    # ------------------------------------------------------------ 객체 이미지

    def image_path(self, rel: str) -> Path | None:
        """objects/img 상대경로를 실제 경로로. 저장 전 프로젝트면 None."""
        if not rel or self.path is None:
            return None
        return self.path / rel

    def import_image(self, source: Path, base_name: str) -> str:
        """이미지를 프로젝트 안으로 복사하고 상대경로를 돌려준다."""
        if self.path is None:
            raise ProjectError("프로젝트를 먼저 저장해야 이미지를 넣을 수 있습니다.")
        dest_dir = self.path / OBJECT_IMG_DIR
        dest_dir.mkdir(parents=True, exist_ok=True)
        stem = slugify(base_name, "img")
        candidate = dest_dir / f"{stem}.png"
        i = 2
        while candidate.exists():
            candidate = dest_dir / f"{stem}_{i}.png"
            i += 1
        shutil.copyfile(source, candidate)
        return f"{OBJECT_IMG_DIR}/{candidate.name}"

    def add_object(self, obj: TargetObject) -> TargetObject:
        obj.name = unique_name(obj.name, {o.name for o in self.objects.objects})
        self.objects.objects.append(obj)
        self.mark_dirty()
        return obj

    # ------------------------------------------------------------ 저장 / 열기

    def save(self, path: Path | str | None = None) -> Path:
        target = Path(path) if path else self.path
        if target is None:
            raise ProjectError("저장 위치가 지정되지 않았습니다.")
        target.mkdir(parents=True, exist_ok=True)
        (target / FLOWS_DIR).mkdir(exist_ok=True)
        (target / OBJECTS_DIR).mkdir(exist_ok=True)
        (target / STATES_DIR).mkdir(exist_ok=True)

        # 다른 폴더로 저장할 때는 이미지도 함께 옮긴다.
        if self.path and target != self.path:
            src_img = self.path / OBJECT_IMG_DIR
            if src_img.is_dir():
                shutil.copytree(src_img, target / OBJECT_IMG_DIR, dirs_exist_ok=True)

        self.settings.schema_version = SCHEMA_VERSION
        _write_json(target / PROJECT_FILE, to_dict(self.settings))

        # 사라진 플로우 파일 정리
        keep = {f"{k}{FLOW_SUFFIX}" for k in self.flows}
        for old in (target / FLOWS_DIR).glob(f"*{FLOW_SUFFIX}"):
            if old.name not in keep:
                old.unlink()
        for key, flow in self.flows.items():
            _write_json(target / FLOWS_DIR / f"{key}{FLOW_SUFFIX}", to_dict(flow))

        _write_json(target / OBJECTS_DIR / "objects.json", to_dict(self.objects))
        _write_json(target / STATES_DIR / "states.json", to_dict(self.states))

        self.path = target
        self.mark_dirty(False)
        return target

    @classmethod
    def load(cls, path: Path | str) -> Project:
        root = Path(path)
        if root.is_file():
            root = root.parent
        pfile = root / PROJECT_FILE
        if not pfile.exists():
            raise ProjectError(f"프로젝트 파일이 없습니다: {pfile}")

        settings = from_dict(ProjectSettings, _read_json(pfile))
        proj = cls(settings, root)

        for fp in sorted((root / FLOWS_DIR).glob(f"*{FLOW_SUFFIX}")):
            key = fp.name[: -len(FLOW_SUFFIX)]
            proj.flows[key] = from_dict(Flow, _read_json(fp))

        objects_file = root / OBJECTS_DIR / "objects.json"
        if objects_file.exists():
            proj.objects = from_dict(ObjectRepo, _read_json(objects_file))

        states_file = root / STATES_DIR / "states.json"
        if states_file.exists():
            proj.states = from_dict(StateGraph, _read_json(states_file))

        proj.normalize()
        proj.mark_dirty(False)
        return proj

    # ------------------------------------------------------------ 정규화 / 검사

    def normalize(self) -> None:
        """저장된 params 를 현재 스키마에 맞춘다.

        액션이 새 파라미터를 얻거나 잃어도 예전 프로젝트가 그대로 열리게 하는 지점이다.
        """
        registry.load_builtins()
        for flow in self.flows.values():
            for node in flow.nodes:
                node.params = registry.node_params(node.type, node.params)
                for action in node.actions:
                    action.params = registry.action_params(action.type, action.params)
        for tr in self.states.transitions:
            for action in tr.actions:
                action.params = registry.action_params(action.type, action.params)

    def validate(self) -> list[Issue]:
        """플로우를 실행하기 전에 잡을 수 있는 문제들."""
        issues: list[Issue] = []
        object_ids = {o.id for o in self.objects.objects}
        object_names = {o.name for o in self.objects.objects}
        state_ids = {s.id for s in self.states.states}
        state_names = {s.name for s in self.states.states}

        for key, flow in self.flows.items():
            if flow.start_node() is None:
                issues.append(Issue("warn", "시작 노드가 없습니다", flow=key))
            node_ids = {n.id for n in flow.nodes}

            for e in flow.edges:
                if e.src_node not in node_ids or e.dst_node not in node_ids:
                    issues.append(Issue("error", "연결이 없는 노드를 가리킵니다", flow=key))

            for n in flow.nodes:
                nt = registry.node_type(n.type)
                if nt is None:
                    issues.append(Issue("error", f"알 수 없는 노드 타입: {n.type}", key, n.title))
                    continue
                if n.required_state and n.required_state not in state_ids | state_names:
                    issues.append(Issue("warn", f"없는 상황을 참조합니다: {n.required_state}", key, n.title))
                if n.type == "subflow":
                    target = n.params.get("flow", "")
                    if target and target not in self.flows:
                        issues.append(Issue("error", f"없는 플로우를 호출합니다: {target}", key, n.title))
                if n.type not in ("start", "end", "note") and not flow.edges_to(n.id):
                    issues.append(Issue("warn", "들어오는 연결이 없습니다", key, n.title))

                for a in n.actions:
                    at = registry.action_type(a.type)
                    if at is None:
                        issues.append(Issue("error", f"알 수 없는 액션: {a.type}", key, n.title))
                        continue
                    for ref in a.params.get("objects", []) or []:
                        if ref and ref not in object_ids | object_names:
                            issues.append(Issue("warn", f"없는 객체를 참조합니다: {ref}", key, n.title))
                    single = a.params.get("object")
                    if single and single not in object_ids | object_names:
                        issues.append(Issue("warn", f"없는 객체를 참조합니다: {single}", key, n.title))
                    target_state = a.params.get("target_state")
                    if target_state and target_state not in state_ids | state_names:
                        issues.append(Issue("warn", f"없는 상황을 참조합니다: {target_state}", key, n.title))

        for cycle in self.find_cycles():
            issues.append(Issue("error", "플로우 호출이 순환합니다: " + " → ".join(cycle)))

        for key, depth in self.subflow_depths().items():
            if depth > MAX_SUBFLOW_DEPTH:
                issues.append(
                    Issue(
                        "error",
                        f"플로우 호출이 {depth}단계로 너무 깊습니다 (한계 {MAX_SUBFLOW_DEPTH})",
                        flow=key,
                    )
                )

        for t in self.states.transitions:
            if t.src not in state_ids or t.dst not in state_ids:
                issues.append(Issue("error", "전이가 없는 상황을 가리킵니다"))

        return issues

    def subflow_depths(self) -> dict[str, int]:
        """플로우별 최대 호출 중첩 깊이.

        순환이 아니어도 A→B→C→… 로 깊게 이어지면 실행 중 스택이 감당하지 못한다.
        검사(F8)와 2차 실행 엔진이 같은 한계값(:data:`MAX_SUBFLOW_DEPTH`)을 쓴다.
        """
        depths: dict[str, int] = {}

        def walk(key: str, seen: tuple[str, ...]) -> int:
            if key in seen or key not in self.flows:
                return len(seen)  # 순환은 find_cycles 가 따로 보고한다
            deepest = len(seen) + 1
            for ref in self.flows[key].subflow_refs():
                deepest = max(deepest, walk(ref, seen + (key,)))
                if deepest > MAX_SUBFLOW_DEPTH + 1:
                    break  # 더 파 봐야 결론은 같다
            return deepest

        for key in self.flows:
            depths[key] = walk(key, ())
        return depths

    def find_cycles(self) -> list[list[str]]:
        """subflow / run_flow 호출의 순환을 찾는다."""
        cycles: list[list[str]] = []
        visiting: list[str] = []
        done: set[str] = set()

        def walk(key: str) -> None:
            if key in visiting:
                cycles.append(visiting[visiting.index(key):] + [key])
                return
            if key in done or key not in self.flows:
                return
            visiting.append(key)
            for ref in self.flows[key].subflow_refs():
                walk(ref)
            visiting.pop()
            done.add(key)

        for key in self.flows:
            walk(key)
        return cycles


# ---------------------------------------------------------------- 파일 유틸


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)  # 쓰다 죽어도 원본이 남도록


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ProjectError(f"파일이 손상되었습니다: {path} ({e})") from e
