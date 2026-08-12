"""레지스트리 / 액션 스키마 테스트."""

from __future__ import annotations

import pytest

from itda.core import registry
from itda.core.schema import FIELD_TYPES


@pytest.fixture(scope="module", autouse=True)
def builtins_loaded():
    registry.load_builtins()


def test_core_actions_are_registered():
    expected = {
        "image_search", "wait_image", "ocr_read",
        "click", "move", "drag", "key_press", "type_text",
        "touch_point", "touch_multi", "touch_drag",
        "set_var", "calc", "log",
        "sleep", "if", "run_flow", "goto_state", "wait_state", "stop",
        "beep", "screenshot", "window", "run_program",
    }
    assert expected <= set(registry.ACTION_TYPES)


def test_core_node_types_are_registered():
    expected = {"start", "action_group", "branch", "switch", "loop", "subflow", "state_gate", "end"}
    assert expected <= set(registry.NODE_TYPES)


def test_every_action_field_type_is_supported():
    for type_id, at in registry.ACTION_TYPES.items():
        for f in at.PARAMS:
            assert f.type in FIELD_TYPES, f"{type_id}.{f.name}"


def test_every_action_summary_survives_defaults():
    """요약 함수가 기본값만으로도 문자열을 돌려줘야 액션 목록이 안 깨진다."""
    for type_id, at in registry.ACTION_TYPES.items():
        text = registry.action_summary(type_id, at.defaults())
        assert isinstance(text, str) and text


def test_action_summary_of_unknown_type_is_graceful():
    assert "알 수 없는" in registry.action_summary("존재하지않음", {})


def test_action_params_normalizes_against_schema():
    params = registry.action_params("click", {"button": "right", "쓰레기": 1})
    assert params["button"] == "right"
    assert "쓰레기" not in params
    assert params["target_mode"] == "fixed"


def test_switch_node_ports_follow_cases():
    nt = registry.node_type("switch")
    assert nt.ports_out({"cases": "성공, 재시도 , 취소"}) == ["성공", "재시도", "취소", "default"]
    assert nt.ports_out({}) == ["default"]


def test_start_node_has_no_input_port():
    assert registry.node_type("start").in_ports == []
    assert registry.node_type("end").ports_out() == []


def test_conditions_are_registered():
    assert {"object_visible", "window_title", "ocr_contains", "pixel_color", "expr"} <= set(
        registry.CONDITION_TYPES
    )
    for type_id, ct in registry.CONDITION_TYPES.items():
        assert isinstance(registry.condition_summary(type_id, {}), str)


def test_actions_by_category_uses_known_order():
    groups = registry.actions_by_category()
    assert "인식" in groups and "입력" in groups
    assert list(groups)[0] == "인식"
