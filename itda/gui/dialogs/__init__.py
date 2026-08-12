"""대화상자."""

from __future__ import annotations

from PyQt6.QtWidgets import QDialogButtonBox

#: Qt 표준 버튼은 한국어 번역 파일이 없으면 영어로 나온다. 직접 붙인다.
_LABELS = {
    QDialogButtonBox.StandardButton.Ok: "확인",
    QDialogButtonBox.StandardButton.Cancel: "취소",
    QDialogButtonBox.StandardButton.Close: "닫기",
    QDialogButtonBox.StandardButton.Save: "저장",
    QDialogButtonBox.StandardButton.Apply: "적용",
    QDialogButtonBox.StandardButton.Reset: "되돌리기",
    QDialogButtonBox.StandardButton.Yes: "예",
    QDialogButtonBox.StandardButton.No: "아니요",
}


def localize(box: QDialogButtonBox) -> QDialogButtonBox:
    """표준 버튼 글자를 한국어로 바꾼다."""
    for standard, text in _LABELS.items():
        button = box.button(standard)
        if button is not None:
            button.setText(text)
    return box
