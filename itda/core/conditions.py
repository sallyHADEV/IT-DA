"""상태 판정 조건 타입.

"타겟 프로그램의 상황 판단 기능" 의 최소 단위다. 상태는 이 조건들을 AND/OR 트리로 묶어
정의하고, 워처가 주기적으로 평가해 현재 상황 이름을 결정한다.
"""

from __future__ import annotations

from itda.core.registry import ConditionType, register_condition
from itda.core.schema import Field


@register_condition
class ObjectVisible(ConditionType):
    ID = "object_visible"
    LABEL = "객체가 보임"
    ICON = "◉"
    PARAMS = [
        Field("object", "object_ref", "객체", ""),
        Field("threshold", "match_threshold", "일치 임계값", 0.0,
              help="화면과 등록 이미지가 얼마나 닮아야 '찾음'으로 볼지의 기준입니다."),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        return f"객체 '{params.get('object') or '?'}' 가 보임"


@register_condition
class WindowTitle(ConditionType):
    ID = "window_title"
    LABEL = "창 제목"
    ICON = "▭"
    PARAMS = [
        Field("contains", "str", "제목에 포함", ""),
        Field("exact", "bool", "정확히 일치", False),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        op = "==" if params.get("exact") else "포함"
        return f"창 제목 {op} '{params.get('contains', '')}'"


@register_condition
class WindowActive(ConditionType):
    ID = "window_active"
    LABEL = "창이 활성"
    ICON = "◱"
    PARAMS = [Field("title", "str", "창 제목", "")]

    @classmethod
    def summary(cls, params: dict) -> str:
        return f"'{params.get('title', '')}' 창이 활성"


@register_condition
class OcrContains(ConditionType):
    ID = "ocr_contains"
    LABEL = "글자 인식(OCR)"
    ICON = "文"
    PARAMS = [
        Field("region", "rect", "인식 영역", None),
        Field("text", "str", "포함할 글자", ""),
        Field(
            "lang",
            "enum",
            "언어",
            "kor+eng",
            options=[("kor+eng", "한글+영어"), ("kor", "한글"), ("eng", "영어"), ("digits", "숫자")],
        ),
        Field(
            "layout",
            "enum",
            "글자 배치",
            "line",
            options=[("line", "한 줄"), ("word", "단어 하나"), ("block", "여러 줄"),
                     ("sparse", "흩어진 글자"), ("auto", "자동")],
        ),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        return f"OCR 결과에 '{params.get('text', '')}' 포함"


@register_condition
class PixelColor(ConditionType):
    ID = "pixel_color"
    LABEL = "픽셀 색"
    ICON = "◧"
    PARAMS = [
        Field("point", "point", "좌표", None),
        Field("color", "color", "색", "#ffffff"),
        Field("tolerance", "int", "허용오차", 12, minimum=0, maximum=255),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        p = params.get("point") or [0, 0]
        return f"({p[0]},{p[1]}) 색 ≈ {params.get('color', '')}"


@register_condition
class Expression(ConditionType):
    ID = "expr"
    LABEL = "식"
    ICON = "ƒ"
    PARAMS = [Field("expr", "expr", "식", "")]

    @classmethod
    def summary(cls, params: dict) -> str:
        return f"식: {params.get('expr', '')}"
