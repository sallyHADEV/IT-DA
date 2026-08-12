"""코어 모델 / 직렬화 / 프로젝트 입출력 테스트."""

from __future__ import annotations

import pytest

from itda.core import registry
from itda.core.model import (
    Action,
    Condition,
    Edge,
    Flow,
    Node,
    State,
    StateGraph,
    TargetObject,
    Transition,
)
from itda.core.project import Project
from itda.core.schema import Field, coerce, defaults_for
from itda.core.serde import clone, from_dict, to_dict
from itda.core.timing import Timing, TimingProfile, jitter_ms, jitter_point, resolve


@pytest.fixture(scope="session", autouse=True)
def builtins_loaded():
    registry.load_builtins()


# ---------------------------------------------------------------- serde


def test_flow_roundtrip_keeps_everything():
    flow = Flow(name="테스트")
    start = flow.add_node(Node(type="start", title="시작", x=10, y=20))
    work = flow.add_node(Node(type="action_group", title="로그인", x=200, y=20))
    work.required_state = "st_login"
    work.actions.append(
        Action(type="click", params={"target_mode": "fixed", "point": [100, 200]})
    )
    work.actions.append(Action(type="type_text", params={"text": "안녕하세요"}))
    flow.connect(start.id, "ok", work.id)

    restored = from_dict(Flow, to_dict(flow))

    assert restored.name == "테스트"
    assert [n.title for n in restored.nodes] == ["시작", "로그인"]
    assert restored.nodes[1].required_state == "st_login"
    assert restored.nodes[1].actions[1].params["text"] == "안녕하세요"
    assert restored.edges[0].src_node == start.id
    assert to_dict(restored) == to_dict(flow)


def test_from_dict_fills_missing_keys_with_defaults():
    """옛 프로젝트 파일에 없던 필드는 기본값으로 채워져야 한다."""
    node = from_dict(Node, {"id": "n_1", "type": "action_group", "title": "옛날 노드"})
    assert node.on_wrong_state == "navigate"
    assert node.retry.count == 0
    assert node.actions == []


def test_from_dict_ignores_unknown_keys():
    """미래 버전이 추가한 키가 있어도 죽지 않아야 한다."""
    node = from_dict(Node, {"id": "n_1", "title": "미래", "quantum_flag": True})
    assert node.title == "미래"


def test_nested_condition_tree_roundtrip():
    cond = Condition(
        op="and",
        items=[
            Condition(type="object_visible", params={"object": "obj_1"}),
            Condition(op="or", items=[Condition(type="window_title", params={"contains": "메모장"})]),
        ],
    )
    restored = clone(cond)
    assert restored.items[1].items[0].params["contains"] == "메모장"


# ---------------------------------------------------------------- 스키마


def test_coerce_adds_missing_and_drops_removed():
    fields = [Field("a", "int", default=5), Field("b", "str", default="x")]
    assert coerce(fields, {"a": 9, "gone": 1}) == {"a": 9, "b": "x"}


def test_defaults_do_not_share_mutable_state():
    fields = [Field("objects", "object_ref_list")]
    one, two = defaults_for(fields), defaults_for(fields)
    one["objects"].append("obj_1")
    assert two["objects"] == []


def test_field_visibility_depends_on_other_value():
    f = Field("count", "int", depends_on=("mode", "count"))
    assert f.is_visible({"mode": "count"})
    assert not f.is_visible({"mode": "while"})
    multi = Field("expr", "expr", depends_on=("mode", ("while", "until")))
    assert multi.is_visible({"mode": "until"})


def test_unknown_field_type_is_rejected():
    with pytest.raises(ValueError):
        Field("x", "quantum")


# ---------------------------------------------------------------- 타이밍


def test_timing_inherits_profile_and_scales():
    profile = TimingProfile(default_pre_ms=50, default_post_ms=100, delay_scale=2.0)
    res = resolve(Timing(inherit=True), profile)
    assert (res.pre_ms, res.post_ms) == (100, 200)


def test_timing_override_uses_own_values():
    profile = TimingProfile(default_post_ms=100, jitter_pct=0.5)
    res = resolve(Timing(inherit=False, pre_ms=10, post_ms=20, jitter_pct=0.1), profile)
    assert (res.pre_ms, res.post_ms, res.jitter_pct) == (10, 20, 0.1)


def test_timing_override_without_jitter_still_inherits_jitter():
    profile = TimingProfile(jitter_pct=0.3)
    res = resolve(Timing(inherit=False, pre_ms=10, post_ms=20), profile)
    assert res.jitter_pct == 0.3


def test_jitter_stays_within_range():
    import random

    rng = random.Random(42)
    for _ in range(100):
        assert 80 <= jitter_ms(100, 0.2, rng) <= 120
    x, y = jitter_point(500, 400, 3, rng)
    assert abs(x - 500) <= 3 and abs(y - 400) <= 3


def test_jitter_zero_is_identity():
    assert jitter_ms(250, 0.0) == 250
    assert jitter_point(10, 20, 0) == (10, 20)


# ---------------------------------------------------------------- 플로우 편집


def test_remove_node_detaches_edges():
    flow = Flow()
    a = flow.add_node(Node(title="A"))
    b = flow.add_node(Node(title="B"))
    c = flow.add_node(Node(title="C"))
    flow.connect(a.id, "ok", b.id)
    flow.connect(b.id, "ok", c.id)

    removed, detached = flow.remove_node(b.id)

    assert removed is b
    assert len(detached) == 2
    assert flow.edges == []
    assert [n.title for n in flow.nodes] == ["A", "C"]


def test_connect_refuses_duplicates():
    flow = Flow()
    a, b = flow.add_node(Node()), flow.add_node(Node())
    assert flow.connect(a.id, "ok", b.id) is not None
    assert flow.connect(a.id, "ok", b.id) is None
    assert flow.connect(a.id, "fail", b.id) is not None


# ---------------------------------------------------------------- 상태 그래프


def _sample_graph() -> StateGraph:
    g = StateGraph()
    for name in ("메인", "설정창", "편집메뉴", "출력메뉴"):
        g.states.append(State(id=f"st_{name}", name=name))
    g.transitions += [
        Transition(src="st_메인", dst="st_설정창", cost=1),
        Transition(src="st_설정창", dst="st_편집메뉴", cost=1),
        Transition(src="st_메인", dst="st_편집메뉴", cost=5),
        Transition(src="st_편집메뉴", dst="st_출력메뉴", cost=1),
    ]
    return g


def test_find_path_picks_cheapest_route():
    g = _sample_graph()
    path = g.find_path("st_메인", "st_편집메뉴")
    assert [t.dst for t in path] == ["st_설정창", "st_편집메뉴"]  # 1+1 < 5


def test_find_path_same_state_is_empty_and_missing_is_none():
    g = _sample_graph()
    assert g.find_path("st_메인", "st_메인") == []
    g.states.append(State(id="st_고립", name="고립"))
    assert g.find_path("st_메인", "st_고립") is None


# ---------------------------------------------------------------- 객체 저장소


def test_object_search_by_name_and_tags():
    proj = Project.create_default()
    proj.add_object(TargetObject(name="로그인 버튼", tags=["login", "button"]))
    proj.add_object(TargetObject(name="취소 버튼", tags=["button"]))
    proj.add_object(TargetObject(name="로그인 제목", tags=["login", "text"]))

    assert len(proj.objects.search(text="로그인")) == 2
    assert len(proj.objects.search(tags=["button"])) == 2
    assert len(proj.objects.search(text="로그인", tags=["button"])) == 1
    assert proj.objects.all_tags() == ["button", "login", "text"]


def test_add_object_makes_names_unique():
    proj = Project.create_default()
    proj.add_object(TargetObject(name="버튼"))
    second = proj.add_object(TargetObject(name="버튼"))
    assert second.name == "버튼 2"


# ---------------------------------------------------------------- 프로젝트 입출력


def test_project_save_load_roundtrip(tmp_path):
    proj = Project.create_default("샘플")
    key, flow = proj.add_flow("서브 루틴")
    node = flow.add_node(Node(type="action_group", title="클릭하기", x=40, y=60))
    node.actions.append(Action(type="click", params={"point": [12, 34]}))
    proj.objects.objects.append(TargetObject(name="확인 버튼", tags=["dialog"]))
    proj.states.states.append(State(id="st_1", name="설정창"))
    proj.states.transitions.append(Transition(src="st_1", dst="st_1"))

    proj.save(tmp_path / "proj")
    loaded = Project.load(tmp_path / "proj")

    assert loaded.settings.name == "샘플"
    assert set(loaded.flow_keys()) == {"main", key}
    assert loaded.flow(key).node(node.id).actions[0].params["point"] == [12, 34]
    assert loaded.objects.objects[0].tags == ["dialog"]
    assert loaded.states.states[0].name == "설정창"
    assert not loaded.dirty


def test_saving_twice_removes_deleted_flow_files(tmp_path):
    proj = Project.create_default()
    key, _ = proj.add_flow("임시")
    proj.save(tmp_path / "p")
    assert (tmp_path / "p" / "flows" / f"{key}.flow.json").exists()

    proj.remove_flow(key)
    proj.save()
    assert not (tmp_path / "p" / "flows" / f"{key}.flow.json").exists()


def test_load_normalizes_params_against_current_schema(tmp_path):
    proj = Project.create_default()
    node = proj.flow("main").nodes[1]
    node.actions.append(Action(type="click", params={"사라진키": 1}))
    proj.save(tmp_path / "p")

    loaded = Project.load(tmp_path / "p")
    params = loaded.flow("main").nodes[1].actions[0].params
    assert "사라진키" not in params
    assert params["button"] == "left"  # 스키마 기본값이 채워진다


def test_rename_flow_updates_references():
    proj = Project.create_default()
    key, _ = proj.add_flow("서브")
    caller = proj.flow("main").add_node(Node(type="subflow", params={"flow": key}))
    proj.flow("main").nodes[1].actions.append(Action(type="run_flow", params={"flow": key}))

    new_key = proj.rename_flow(key, "다른이름")

    assert caller.params["flow"] == new_key
    assert proj.flow("main").nodes[1].actions[0].params["flow"] == new_key


# ---------------------------------------------------------------- 검사


def test_validate_detects_missing_subflow_and_object():
    proj = Project.create_default()
    flow = proj.flow("main")
    flow.add_node(Node(type="subflow", title="호출", params={"flow": "없는플로우"}))
    flow.nodes[1].actions.append(
        Action(type="image_search", params={"objects": ["없는객체"]})
    )

    messages = [i.message for i in proj.validate()]
    assert any("없는 플로우를 호출" in m for m in messages)
    assert any("없는 객체를 참조" in m for m in messages)


def test_validate_detects_subflow_cycle():
    proj = Project.create_default()
    key, sub = proj.add_flow("서브")
    proj.flow("main").add_node(Node(type="subflow", params={"flow": key}))
    sub.add_node(Node(type="subflow", params={"flow": "main"}))

    assert any("순환" in i.message for i in proj.validate())


def test_union_field_falls_back_to_the_matching_type():
    """threshold: float | None 에 문자열이 와도 죽지 않아야 한다."""
    from itda.core.model import MatchOptions

    assert from_dict(MatchOptions, {"threshold": 0.9}).threshold == 0.9
    assert from_dict(MatchOptions, {"threshold": None}).threshold is None
    # 변환 불가능한 값이 와도 예외 대신 원본을 유지한다
    assert from_dict(MatchOptions, {"threshold": "높게"}).threshold == "높게"


def test_clone_is_a_deep_copy():
    node = Node(title="원본", actions=[Action(type="click", params={"point": [1, 2]})])
    copy = clone(node)

    copy.actions[0].params["point"][0] = 99
    copy.title = "사본"

    assert node.title == "원본"
    assert node.actions[0].params["point"] == [1, 2]


def test_validate_flags_too_deep_subflow_nesting():
    from itda.core.project import MAX_SUBFLOW_DEPTH

    proj = Project.create_default()
    previous = "main"
    for i in range(MAX_SUBFLOW_DEPTH + 2):
        key, _flow = proj.add_flow(f"단계{i}")
        proj.flow(previous).add_node(Node(type="subflow", params={"flow": key}))
        previous = key

    messages = [i.message for i in proj.validate() if i.level == "error"]
    assert any("너무 깊습니다" in m for m in messages)


def test_shallow_subflow_nesting_is_fine():
    proj = Project.create_default()
    key, _ = proj.add_flow("보조")
    proj.flow("main").add_node(Node(type="subflow", params={"flow": key}))

    assert not any("너무 깊습니다" in i.message for i in proj.validate())


def test_clean_project_has_no_errors():
    proj = Project.create_default()
    assert [i for i in proj.validate() if i.level == "error"] == []
