"""OCR 테스트.

Tesseract 가 설치돼 있으면 실제로 글자를 읽어 확인하고, 없으면 건너뛴다.
글자 이미지는 Qt 로 그려서 만든다 — OpenCV 는 한글을 못 그린다.
"""

from __future__ import annotations

import numpy as np
import pytest

from itda.vision import ocr

needs_tesseract = pytest.mark.skipif(
    not ocr.is_available(), reason="Tesseract 가 설치돼 있지 않습니다"
)


def render(text: str, width: int = 520, height: int = 90, point_size: int = 34) -> np.ndarray:
    """글자를 그려 넣은 흰 배경 이미지."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPixmap

    from itda.vision import capture

    image = QImage(width, height, QImage.Format.Format_RGB888)
    image.fill(QColor("white"))
    painter = QPainter(image)
    font = QFont("Malgun Gothic")
    font.setPointSize(point_size)
    painter.setFont(font)
    painter.setPen(QColor("black"))
    painter.drawText(image.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return capture.pixmap_to_bgr(QPixmap.fromImage(image))


# ---------------------------------------------------------------- 전처리 / 후처리


def test_preprocess_scales_and_binarizes():
    source = np.full((20, 40, 3), 128, dtype=np.uint8)
    prepared = ocr.preprocess(source, scale=2.0, binarize=True)

    assert prepared.shape[:2] == (40, 80)
    assert prepared.ndim == 2  # 흑백
    assert set(np.unique(prepared)) <= {0, 255}


def test_preprocess_handles_empty():
    empty = np.zeros((0, 0, 3), dtype=np.uint8)
    assert ocr.preprocess(empty).size == 0


@pytest.mark.parametrize(
    "raw,mode,expected",
    [
        ("  값  ", "trim", "값"),
        ("  값  ", "none", "  값  "),
        ("가격: 1,200원", "digits", "1200"),
        ("12개", "int", 12),
        ("3.14 초", "float", 3.14),
        ("글자만", "int", 0),
        ("글자만", "float", 0.0),
    ],
)
def test_post_process(raw, mode, expected):
    assert ocr.post_process(raw, mode) == expected


def test_empty_image_is_reported():
    result = ocr.read(np.zeros((0, 0, 3), dtype=np.uint8))
    assert result.ok is False
    assert "비어" in result.message


# ---------------------------------------------------------------- 실제 인식


@needs_tesseract
def test_reads_english(qapp):
    result = ocr.read(render("Settings 1234"), lang="eng")
    assert result.ok
    assert "Settings" in result.text
    assert "1234" in result.text


@needs_tesseract
def test_reads_korean(qapp):
    """기본 PSM(자동)은 한글을 세로쓰기로 오해한다 — 한 줄 모드가 기본이어야 한다."""
    result = ocr.read(render("확인 취소"), lang="kor")
    assert result.ok
    assert ocr.post_process(result.text, "trim").replace(" ", "") == "확인취소"


@needs_tesseract
def test_auto_layout_is_worse_for_korean():
    """기본값을 'line' 으로 정한 근거를 테스트로 남긴다."""
    from PyQt6.QtWidgets import QApplication

    if QApplication.instance() is None:
        pytest.skip("QApplication 필요")

    image = render("확인 취소")
    line = ocr.post_process(ocr.read(image, lang="kor", layout="line").text, "trim")
    auto = ocr.post_process(ocr.read(image, lang="kor", layout="auto").text, "trim")

    assert line.replace(" ", "") == "확인취소"
    assert auto.replace(" ", "") != "확인취소"


@needs_tesseract
def test_reads_mixed_korean_and_numbers(qapp):
    result = ocr.read(render("잔액 12,500원"), lang="kor+eng")
    assert result.ok
    assert "12,500" in result.text.replace(" ", "")


@needs_tesseract
def test_digits_mode_extracts_numbers(qapp):
    result = ocr.read(render("98765"), lang="digits")
    assert ocr.post_process(result.text, "digits") == "98765"


@needs_tesseract
def test_small_text_needs_upscaling(qapp):
    """작은 글자는 확대해야 읽힌다 — scale 기본값 2.0 의 근거."""
    tiny = render("재고 42", width=170, height=34, point_size=11)

    scaled = ocr.post_process(ocr.read(tiny, lang="kor+eng", scale=3.0).text, "trim")

    assert "42" in scaled


@needs_tesseract
def test_ocr_action_reads_the_screen(project, qapp, monkeypatch):
    """액션 → 실행 엔진 → OCR 까지 이어지는지."""
    from itda.core.model import Action, Node
    from itda.engine.context import ExecutionContext
    from itda.engine.input import DryRunSender
    from itda.engine.runner import Engine

    scene = np.full((300, 800, 3), 255, dtype=np.uint8)
    patch = render("합계 3500", width=400, height=80, point_size=30)
    scene[100:180, 200:600] = patch

    monkeypatch.setattr(ExecutionContext, "screen", lambda self, fresh=False: scene)

    flow = project.flow("main")
    flow.nodes = [n for n in flow.nodes if n.type == "start"]
    flow.edges = []
    start = flow.start_node()
    node = flow.add_node(
        Node(type="action_group", title="읽기",
             actions=[Action(type="ocr_read", out_var="금액",
                             params={"region": [200, 100, 400, 80], "lang": "kor+eng",
                                     "post": "digits", "layout": "line"})])
    )
    flow.connect(start.id, "ok", node.id)

    engine = Engine(project, sender=DryRunSender())
    project.settings.timing.default_pre_ms = 0
    project.settings.timing.default_post_ms = 0

    assert engine.run("main") is True
    assert engine.ctx.variables.get("금액") == "3500"
