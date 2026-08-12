"""테마 / 폰트 테스트."""

from __future__ import annotations

from PyQt6.QtGui import QFontDatabase, QFontMetrics

from itda.gui import icons, style


def test_headless_environment_has_a_usable_font(qapp):
    """오프스크린에서도 글꼴이 있어야 캡처한 화면의 글자를 읽을 수 있다."""
    assert QFontDatabase.families(), "폰트가 하나도 없으면 모든 글자가 네모로 나온다"


def test_korean_glyphs_are_renderable(qapp):
    metrics = QFontMetrics(qapp.font())
    assert metrics.horizontalAdvance("가나다") > 0
    assert metrics.inFont("가")


def test_ensure_fonts_is_idempotent(qapp):
    before = len(QFontDatabase.families())
    style.ensure_fonts()
    style.ensure_fonts()
    assert len(QFontDatabase.families()) == before


def test_icons_are_cached_and_not_empty(qapp):
    first = icons.icon("play")
    second = icons.icon("play")
    assert first is second
    assert not first.isNull()
    assert not first.pixmap(24, 24).isNull()


def test_icon_color_variants_are_distinct(qapp):
    assert icons.icon("play", "#ff0000") is not icons.icon("play", "#00ff00")


def test_every_registered_icon_name_draws(qapp):
    for name in icons._DRAWERS:
        assert not icons.icon(name).pixmap(24, 24).isNull(), name


def test_action_and_node_icons_resolve(qapp):
    from itda.core import registry

    for type_id, at in registry.ACTION_TYPES.items():
        assert not icons.action_icon(type_id, at.CATEGORY, at.COLOR).isNull(), type_id
    for type_id, spec in registry.NODE_TYPES.items():
        assert not icons.node_icon(type_id, spec.color).isNull(), type_id


def test_unknown_icon_name_falls_back(qapp):
    assert not icons.icon("존재하지않는아이콘").isNull()
