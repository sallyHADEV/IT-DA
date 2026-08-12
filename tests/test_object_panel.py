"""객체 저장소 패널 / 객체화 도구 테스트."""

from __future__ import annotations

import numpy as np
import pytest

from itda.core.model import TargetObject
from itda.gui.panels.object_panel import ObjectPanel
from itda.gui.tools.objectify_dialog import ObjectifyDialog
from tests.test_vision import make_ui_image


@pytest.fixture
def saved_project(project, tmp_path):
    project.save(tmp_path / "proj")
    return project


@pytest.fixture
def panel(qapp, saved_project):
    p = ObjectPanel()
    p.set_project(saved_project)
    return p


def _add(panel, name, tags=()):
    return panel.add_object(TargetObject(name=name, tags=list(tags)))


def test_list_shows_objects(panel):
    _add(panel, "로그인 버튼", ["login", "button"])
    _add(panel, "취소 버튼", ["button"])
    assert panel.list.count() == 2


def test_search_filters_by_name(panel):
    _add(panel, "로그인 버튼")
    _add(panel, "취소 버튼")

    panel.search.setText("로그인")
    assert panel.list.count() == 1


def test_tag_filter(panel):
    _add(panel, "로그인 버튼", ["login", "button"])
    _add(panel, "설정 제목", ["text"])

    index = panel.tag_filter.findText("login")
    assert index > 0
    panel.tag_filter.setCurrentIndex(index)
    assert panel.list.count() == 1


def test_selecting_object_loads_detail(panel):
    obj = _add(panel, "확인 버튼", ["dialog"])
    panel.select_object(obj.id)

    assert panel.current_object() is obj
    assert panel.edit_name.text() == "확인 버튼"
    assert panel.edit_tags.text() == "dialog"


def test_editing_tags_updates_model_and_filter(panel):
    obj = _add(panel, "확인 버튼")
    panel.select_object(obj.id)

    panel.edit_tags.setText("대화상자, 버튼")
    panel._on_tags_changed()

    assert obj.tags == ["대화상자", "버튼"]
    assert "대화상자" in [panel.tag_filter.itemText(i) for i in range(panel.tag_filter.count())]


def test_threshold_zero_means_inherit(panel):
    obj = _add(panel, "확인 버튼")
    panel.select_object(obj.id)

    panel.spin_threshold.setValue(0.93)
    assert obj.match.threshold == 0.93

    panel.spin_threshold.setValue(0.0)
    assert obj.match.threshold is None


def test_duplicate_names_are_made_unique(panel):
    _add(panel, "버튼")
    second = _add(panel, "버튼")
    assert second.name == "버튼 2"


def test_object_updated_refreshes_dirty_form_and_list(panel, saved_project):
    """바깥에서 객체를 고쳤을 때 쓰는 창구 — 메인 윈도우가 내부를 들여다보지 않도록."""
    obj = _add(panel, "로그인 버튼")
    saved_project.mark_dirty(False)
    changed = []
    panel.objects_changed.connect(lambda: changed.append(True))

    obj.images.append("img/새이미지.png")
    panel.object_updated(obj)

    assert saved_project.dirty is True
    assert changed == [True]
    assert panel.current_object() is obj
    assert panel.image_list.count() == 1  # 편집 폼이 새 이미지를 반영


def test_editing_marks_project_dirty(panel, saved_project):
    obj = _add(panel, "확인 버튼")
    saved_project.mark_dirty(False)
    panel.select_object(obj.id)

    panel.spin_dx.setValue(4)

    assert obj.anchor_dx == 4
    assert saved_project.dirty


# ---------------------------------------------------------------- 객체화 도구


@pytest.fixture
def dialog(qapp, saved_project):
    return ObjectifyDialog(make_ui_image(), saved_project)


def test_objectify_lists_detected_regions(dialog):
    assert dialog.regions
    assert dialog.list.count() == len(dialog.regions)


def test_failed_import_leaves_no_temp_file_behind(dialog, saved_project):
    """가져오기가 실패해도 .tmp.png 가 프로젝트 폴더에 남으면 안 된다."""
    dialog.name_prefix.setText("설정창")
    dialog._select_all(True)

    def failing_import(*_args, **_kwargs):
        raise OSError("디스크 가득 참")

    saved_project.import_image = failing_import

    with pytest.raises(OSError):
        dialog.save_selected()

    leftovers = list((saved_project.path / "objects" / "img").glob("*.tmp.png"))
    assert leftovers == []


def test_kind_filter_hides_items(dialog):
    dialog.chk_text.setChecked(False)
    hidden = [
        i for i, item in enumerate(dialog.items) if item.region.kind == "text"
    ]
    for index in hidden:
        assert dialog.list.item(index).isHidden()
        assert not dialog.items[index].isVisible()


def test_select_all_then_save_creates_objects(dialog, saved_project):
    dialog.name_prefix.setText("설정창")
    dialog.tags.setText("설정, 버튼")
    dialog._select_all(True)
    count = len(dialog.selected_regions())
    assert count > 0

    dialog.save_selected()

    assert len(saved_project.objects.objects) == count
    first = saved_project.objects.objects[0]
    assert first.name.startswith("설정창")
    assert first.tags == ["설정", "버튼"]
    # 이미지 파일이 실제로 프로젝트 폴더에 들어갔는지
    path = saved_project.image_path(first.images[0])
    assert path is not None and path.exists()


def test_clicking_regions_accumulates_selection(dialog):
    """박스를 누르면 선택, 다시 누르면 해제 — 여러 개를 한 번에 고를 수 있어야 한다."""
    first, second = dialog.items[0], dialog.items[1]

    first.setSelected(True)
    second.setSelected(True)
    assert len(dialog.selected_regions()) == 2

    second.setSelected(False)
    assert len(dialog.selected_regions()) == 1


def click_region(dialog, item, qapp) -> None:
    """실제 뷰를 눌러 본다 — 이벤트 객체는 PyQt6 에서 직접 만들 수 없다."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtTest import QTest

    dialog.view.resize(600, 400)
    dialog.view.centerOn(item)
    center = QPointF(item.region.x + item.region.w / 2, item.region.y + item.region.h / 2)
    QTest.mouseClick(
        dialog.view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        dialog.view.mapFromScene(center),
    )
    qapp.processEvents()


def test_region_click_toggles(dialog, qapp):
    item = dialog.items[0]

    click_region(dialog, item, qapp)
    assert item.isSelected() is True

    click_region(dialog, item, qapp)
    assert item.isSelected() is False


def test_selecting_a_second_region_keeps_the_first(dialog, qapp):
    """하나 고른 뒤 다른 것을 골라도 앞의 선택이 풀리면 안 된다."""
    first, second = dialog.items[0], dialog.items[1]

    click_region(dialog, first, qapp)
    click_region(dialog, second, qapp)

    assert first.isSelected() and second.isSelected()
    assert len(dialog.selected_regions()) >= 2


def test_manual_region_can_be_added(dialog):
    from itda.vision.segmenter import Region

    before = len(dialog.regions)
    dialog.add_manual_region(Region(5, 5, 40, 20, "button"))

    assert len(dialog.regions) == before + 1
    assert dialog.items[-1].isSelected()


def test_saving_without_selection_does_nothing(dialog, saved_project):
    dialog._select_all(False)
    dialog.save_selected()
    assert saved_project.objects.objects == []


def test_saved_images_are_cropped_to_region(dialog, saved_project):
    from itda.vision import capture

    dialog._select_all(False)
    dialog.items[0].setSelected(True)
    region = dialog.items[0].region
    dialog.padding.setValue(0)

    dialog.save_selected()

    obj = saved_project.objects.objects[0]
    image = capture.load_bgr(saved_project.image_path(obj.images[0]))
    assert image.shape[0] == region.h
    assert image.shape[1] == region.w


def test_objectify_handles_blank_image(qapp, saved_project):
    blank = np.full((120, 120, 3), 255, dtype=np.uint8)
    dlg = ObjectifyDialog(blank, saved_project)
    assert dlg.list.count() == len(dlg.regions)


def test_cells_are_wide_enough_to_read(panel):
    """예전 44x44 격자는 한 화면에 14개가 보였지만 이름이 세 글자에서 잘리고 썸네일도
    알아볼 수 없었다 — 그 14 는 '읽을 수 없을 만큼 작아서' 나온 숫자였다.

    반대로 세로 목록은 2개밖에 안 보였다. 지금 크기는 그 사이의 절충이다.
    """
    from itda.gui.panels.object_panel import CELL, THUMB

    assert THUMB.width() >= 48  # 무엇을 찍었는지 알아볼 수 있는 크기
    assert CELL.width() >= 96  # 한글 여섯 글자쯤
    assert CELL.height() >= THUMB.height() + 30  # 이름 두 줄이 들어갈 자리
    assert panel.list.wordWrap() is True
    assert panel.list.minimumHeight() >= CELL.height() * 3


def test_a_reasonable_number_still_fits_on_screen(panel):
    """읽히게 하느라 한 번에 몇 개 안 보이면 그것대로 못 쓴다."""
    from itda.gui.panels.object_panel import CELL

    dock_w, list_h = 330, 200  # 실제 도크 크기 대략치
    visible = (dock_w // CELL.width()) * (list_h // CELL.height())
    assert visible >= 6


def test_cell_shows_the_whole_name(panel):
    obj = _add(panel, "낚시 시작 버튼")
    item = panel.list.item(0)

    assert obj.name in item.text()
    assert "..." not in item.text()


def test_row_flags_objects_that_need_attention(panel):
    """장수는 매칭 성패를 좌우하는데 이름만 봐선 모른다. 평범한 경우는 조용히 둔다."""
    _add(panel, "보통")
    plain = panel.list.item(0)
    assert plain.text() == "보통  " or plain.text().startswith("보통")

    empty = _add(panel, "이미지없음")
    panel.reload()
    texts = {panel.list.item(i).text() for i in range(panel.list.count())}
    assert any("이미지 없음" in t for t in texts)


def test_tooltip_still_carries_the_details(panel):
    _add(panel, "로그인 버튼", ["login", "button"])
    tip = panel.list.item(0).toolTip()

    assert "로그인 버튼" in tip
    assert "login" in tip and "button" in tip
    assert "이미지" in tip
