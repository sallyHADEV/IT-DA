"""인식 계열 액션 — 이미지 서치, 대기, OCR.

실행부(``execute``)는 2차에서 채운다. 1차에서는 파라미터 스키마와 요약만 있으면
플로우를 그리고 저장하는 데 충분하다.
"""

from __future__ import annotations

from itda.core.registry import ActionType, register_action
from itda.core.schema import Field

#: 여러 액션이 공유하는 검색 범위 필드
_REGION_FIELDS = [
    Field(
        "region_mode",
        "enum",
        "검색 범위",
        "full",
        options=[("full", "전체 화면"), ("rect", "지정 영역"), ("window", "지정 창"), ("object", "객체 설정 따름")],
        help="검색할 화면 범위입니다. 지정 영역은 화면 좌표, 지정 창은 창 내부 기준으로 제한합니다.",
        group="범위",
    ),
    Field("region", "rect", "영역", None, depends_on=("region_mode", "rect"), group="범위",
          help="검색할 화면 영역(x, y, 너비, 높이)입니다."),
    Field("window_title", "str", "창 제목", "", depends_on=("region_mode", "window"), group="범위",
          help="검색 대상 창의 제목입니다. 제목에 포함된 문자열로 창을 찾습니다."),
]


@register_action
class ImageSearch(ActionType):
    ID = "image_search"
    LABEL = "이미지 찾기"
    CATEGORY = "인식"
    COLOR = "#3f8f8f"
    ICON = "🔍"
    HELP = (
        "화면에서 객체를 찾아 <b>좌표를 얻습니다</b>. 결과 변수에 [x, y] 가 담기고, "
        "같은 객체의 '최근 찾은 위치'로도 기억됩니다. 이후 클릭·이동에서 그 객체를 고르면 "
        "기본적으로 이 위치를 재사용합니다.<br>"
        "· 기다리는 것이 목적이면 <b>이미지 대기</b>를 쓰세요.<br>"
        "· 예외 상황이 많으면 객체를 여러 개 지정하세요."
    )
    HAS_OUTPUT = True
    PARAMS = [
        Field("objects", "object_ref_list", "찾을 객체", None,
              help="객체에 등록된 이미지들을 검색합니다. 여러 객체를 넣으면 판정 방식에 따라 처리합니다."),
        Field(
            "mode",
            "enum",
            "판정 방식",
            "any",
            options=[("any", "하나라도 찾으면 성공"), ("best", "가장 점수 높은 것"), ("all", "전부 찾아야 성공")],
            help="여러 객체를 지정했을 때 성공 조건과 반환할 좌표를 결정합니다.",
        ),
        Field("threshold", "match_threshold", "일치 임계값", 0.0,
              help="화면과 등록 이미지의 유사도 기준입니다. 0이면 객체 설정값을 상속하고, 높일수록 오인식은 줄지만 놓칠 수 있습니다."),
        Field("retry_ms", "int", "못 찾으면 재시도", 0, minimum=0, maximum=600000, suffix=" ms",
              help="required를 켜면 이 시간 동안만 반복 검색합니다. 0이면 즉시 한 번만 확인합니다. required를 끄면 성공할 때까지 계속 검색합니다.",),
        Field("required", "bool", "못 찾으면 실패 처리", True,
              help="켜면 재시도 시간이 끝날 때 액션을 실패시킵니다. 끄면 성공할 때까지 계속 검색하며, F12로 중단할 수 있습니다."),
        *_REGION_FIELDS,
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        objs = params.get("objects") or []
        if not objs:
            return "이미지 찾기 (객체 미지정)"
        head = objs[0] if len(objs) == 1 else f"{objs[0]} 외 {len(objs) - 1}개"
        return f"이미지 찾기 → 좌표: {head}"


@register_action
class WaitImage(ActionType):
    ID = "wait_image"
    LABEL = "이미지 대기"
    CATEGORY = "인식"
    COLOR = "#3f8f8f"
    ICON = "⏳"
    HELP = (
        "화면이 바뀔 때까지 <b>기다립니다</b>. 결과는 성공/실패(참·거짓)이며 좌표를 목적으로 하지 "
        "않습니다.<br>"
        "· 창이 뜨기를 기다릴 때 → '나타날 때까지'<br>"
        "· 로딩 표시가 사라지기를 기다릴 때 → '사라질 때까지' (이미지 찾기로는 못 하는 일)<br>"
        "· 좌표가 필요하면 대기 뒤에 <b>이미지 찾기</b>를 두거나, 대기에서 '찾은 좌표도 기억' 을 켜세요."
    )
    HAS_OUTPUT = True
    PARAMS = [
        Field("objects", "object_ref_list", "대상 객체", None,
              help="나타나거나 사라지는지 확인할 객체입니다. 여러 객체를 넣으면 하나라도 조건을 만족할 때 성공합니다."),
        Field("threshold", "match_threshold", "일치 임계값", 0.0,
              help="화면과 등록 이미지의 유사도 기준입니다. 0이면 각 객체의 설정값을 상속합니다."),
        Field(
            "until",
            "enum",
            "대기 조건",
            "appear",
            options=[("appear", "나타날 때까지"), ("disappear", "사라질 때까지")],
            help="화면에 보여야 성공할지, 화면에서 없어져야 성공할지 정합니다.",
        ),
        Field("timeout_ms", "int", "제한시간", 5000, minimum=0, maximum=600000, suffix=" ms",
              help="이미지가 나타나거나 사라지기를 기다리는 최대 시간입니다."),
        Field("poll_ms", "int", "확인 간격", 200, minimum=10, maximum=60000, suffix=" ms",
              help="화면을 다시 캡처해 확인하는 간격입니다. 짧을수록 빠르지만 CPU 사용량이 늘어납니다."),
        Field("remember_position", "bool", "찾은 좌표도 기억", True,
              depends_on=("until", "appear"),
              help="켜 두면 뒤따르는 클릭이 다시 찾지 않고 이 위치를 씁니다."),
        Field("required", "bool", "시간 초과 시 실패 처리", True,
              help="켜면 제한시간 초과를 실패로 처리합니다. 끄면 시간 초과 후에도 성공으로 간주하고 다음 동작으로 진행합니다."),
        *_REGION_FIELDS,
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        objs = params.get("objects") or []
        what = objs[0] if objs else "(미지정)"
        verb = "나타날" if params.get("until") == "appear" else "사라질"
        return f"{what} 이(가) {verb} 때까지 대기 ({params.get('timeout_ms', 0)}ms)"


@register_action
class OcrRead(ActionType):
    ID = "ocr_read"
    LABEL = "글자 읽기(OCR)"
    CATEGORY = "인식"
    COLOR = "#3f8f8f"
    ICON = "文"
    HELP = "지정 영역의 글자를 읽어 변수에 담습니다. 숫자/영어/한글."
    HAS_OUTPUT = True
    PARAMS = [
        Field("region", "rect", "인식 영역", None),
        Field(
            "lang",
            "enum",
            "언어",
            "kor+eng",
            options=[("kor+eng", "한글+영어"), ("kor", "한글"), ("eng", "영어"), ("digits", "숫자만")],
        ),
        Field(
            "layout",
            "enum",
            "글자 배치",
            "line",
            options=[
                ("line", "한 줄"),
                ("word", "단어 하나"),
                ("block", "여러 줄 덩어리"),
                ("sparse", "흩어진 글자"),
                ("auto", "자동 (문서 전체)"),
            ],
            help="대개 작은 영역의 한 줄을 읽습니다. '자동'은 한글을 세로쓰기로 오해할 수 있습니다.",
        ),
        Field(
            "post",
            "enum",
            "후처리",
            "trim",
            options=[("none", "원본 그대로"), ("trim", "앞뒤 공백 제거"), ("digits", "숫자만 추출"), ("int", "정수로 변환"), ("float", "실수로 변환")],
        ),
        Field("scale", "float", "전처리 확대배율", 2.0, minimum=1.0, maximum=8.0, step=0.5,
              help="작은 글자는 확대하면 인식률이 오릅니다."),
        Field("binarize", "bool", "이진화 전처리", True),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        r = params.get("region") or [0, 0, 0, 0]
        return f"OCR({params.get('lang', '')}) 영역 {r[2]}×{r[3]} @({r[0]},{r[1]})"


@register_action
class PixelCheck(ActionType):
    ID = "pixel_check"
    LABEL = "픽셀 색 확인"
    CATEGORY = "인식"
    COLOR = "#3f8f8f"
    ICON = "◧"
    HAS_OUTPUT = True
    PARAMS = [
        Field("point", "point", "좌표", None),
        Field("color", "color", "기대 색", "#ffffff"),
        Field("tolerance", "int", "허용오차", 12, minimum=0, maximum=255),
        Field("required", "bool", "다르면 실패 처리", False),
    ]

    @classmethod
    def summary(cls, params: dict) -> str:
        p = params.get("point") or [0, 0]
        return f"픽셀 ({p[0]},{p[1]}) ≈ {params.get('color', '')}"
