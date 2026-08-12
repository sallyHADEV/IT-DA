"""OCR 백엔드.

인터페이스를 먼저 고정해 두고 엔진은 갈아 끼운다. 1순위는 Tesseract(kor+eng)다 —
설치돼 있으면 자동으로 쓰고, 없으면 무엇을 설치해야 하는지 분명히 알린다.

전처리(확대 · 이진화)는 백엔드와 무관하게 여기서 한다. 작은 글자는 확대만 해도 인식률이
눈에 띄게 오른다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

#: 액션의 언어 값 → Tesseract 언어 코드
LANGS = {
    "kor+eng": "kor+eng",
    "kor": "kor",
    "eng": "eng",
    "digits": "eng",
}

#: 페이지 분할 모드. 기본값(3, 자동)은 한글을 세로쓰기로 오해해 글자를 뭉갠다.
#: 매크로가 읽는 대상은 대개 작은 영역의 한 줄이라 7 이 맞다.
PSM = {
    "line": 7,     # 한 줄 — 기본
    "block": 6,    # 여러 줄 덩어리
    "sparse": 11,  # 흩어진 글자
    "word": 8,     # 단어 하나
    "auto": 3,     # 자동 (문서 전체를 읽을 때만)
}
DEFAULT_PSM = "line"

INSTALL_HINT = (
    "Tesseract OCR 이 필요합니다. https://github.com/UB-Mannheim/tesseract 에서 설치한 뒤 "
    "한국어 데이터(kor.traineddata)를 포함하세요. 설치 경로가 PATH 에 없으면 "
    "환경변수 ITDA_TESSERACT 로 실행 파일 경로를 지정할 수 있습니다."
)


@dataclass
class OcrResult:
    ok: bool
    text: str = ""
    message: str = ""


#: 찾아 둔 실행 파일 경로 (없으면 None). 매번 디스크를 뒤지지 않으려고 기억한다.
_cached_path: str | None = None
_path_checked = False


def forget_tesseract_path() -> None:
    """경로 캐시를 버린다. 설치 직후 다시 찾게 할 때."""
    global _cached_path, _path_checked
    _cached_path, _path_checked = None, False


def tesseract_path() -> str | None:
    """설치된 tesseract 실행 파일 경로. 없으면 None.

    ``shutil.which`` 는 PATH 를 전부 훑어 실측 6.3ms 가 든다. OCR 을 한 번 부를 때마다
    치르면 한 줄 읽는 데 드는 시간의 6%가 여기서 나간다 — 한 번만 찾고 기억한다.
    """
    global _cached_path, _path_checked
    if _path_checked:
        return _cached_path
    _cached_path = _locate_tesseract()
    _path_checked = True
    return _cached_path


def _locate_tesseract() -> str | None:
    explicit = os.environ.get("ITDA_TESSERACT")
    if explicit and Path(explicit).is_file():
        return explicit
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def is_available() -> bool:
    return tesseract_path() is not None


def preprocess(image: np.ndarray, scale: float = 2.0, binarize: bool = True) -> np.ndarray:
    """작은 글자를 키우고 대비를 세운다."""
    if image is None or not image.size:
        return image
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    if scale and abs(scale - 1.0) > 1e-6:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if binarize:
        gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
    return gray


def read(
    image: np.ndarray,
    lang: str = "kor+eng",
    scale: float = 2.0,
    binarize: bool = True,
    layout: str = DEFAULT_PSM,
) -> OcrResult:
    """이미지에서 글자를 읽는다.

    Args:
        layout: 글자 배치 — :data:`PSM` 의 키. 기본은 한 줄.
    """
    if image is None or not image.size:
        return OcrResult(False, message="인식할 이미지가 비어 있습니다")

    exe = tesseract_path()
    if exe is None:
        return OcrResult(False, message=INSTALL_HINT)

    prepared = preprocess(image, scale, binarize)
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "patch.png"
        cv2.imencode(".png", prepared)[1].tofile(str(source))
        command = [
            exe, str(source), "stdout",
            "-l", LANGS.get(lang, "eng"),
            "--psm", str(PSM.get(layout, PSM[DEFAULT_PSM])),
        ]
        if lang == "digits":
            command += ["-c", "tessedit_char_whitelist=0123456789.,-"]
        try:
            output = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", timeout=20
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            return OcrResult(False, message=f"Tesseract 실행 실패: {e}")

    if output.returncode != 0:
        return OcrResult(False, message=(output.stderr or "").strip() or "Tesseract 오류")
    return OcrResult(True, text=output.stdout)


def post_process(text: str, mode: str = "trim"):
    """후처리 — 숫자만 뽑거나 형 변환."""
    raw = text or ""
    match mode:
        case "none":
            return raw
        case "digits":
            return "".join(ch for ch in raw if ch.isdigit())
        case "int":
            digits = "".join(ch for ch in raw if ch.isdigit() or ch == "-")
            return int(digits) if digits.strip("-") else 0
        case "float":
            allowed = "".join(ch for ch in raw if ch.isdigit() or ch in ".-")
            try:
                return float(allowed)
            except ValueError:
                return 0.0
        case _:
            return raw.strip()
