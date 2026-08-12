"""앱 아이콘 생성.

이미지 파일을 저장소에 두지 않고 그려서 만든다 — 테마 색이 바뀌면 다시 뽑으면 된다.
모양은 잇다의 상징인 "이어진 두 노드"다.

    python tools/make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "itda" / "resources" / "itda.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)

BACKGROUND = QColor("#232936")
NODE = QColor("#2a3040")
ACCENT = QColor("#ee7f63")
LINE = QColor("#7f8b9e")


def draw(size: int) -> QImage:
    """이어진 두 노드. 작은 크기에서도 형태가 남도록 단순하게."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    s = size

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(BACKGROUND))
    painter.drawRoundedRect(QRectF(0, 0, s, s), s * 0.22, s * 0.22)

    # 연결선
    pen = QPen(LINE, max(1.0, s * 0.055))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(s * 0.34, s * 0.34), QPointF(s * 0.66, s * 0.66))

    # 위 노드 (일반)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(NODE))
    painter.drawRoundedRect(QRectF(s * 0.14, s * 0.14, s * 0.34, s * 0.26), s * 0.07, s * 0.07)
    painter.setBrush(QBrush(LINE))
    painter.drawRoundedRect(QRectF(s * 0.14, s * 0.14, s * 0.06, s * 0.26), s * 0.03, s * 0.03)

    # 아래 노드 (악센트 — 실행 중인 노드를 뜻한다)
    painter.setBrush(QBrush(NODE))
    painter.drawRoundedRect(QRectF(s * 0.52, s * 0.6, s * 0.34, s * 0.26), s * 0.07, s * 0.07)
    painter.setBrush(QBrush(ACCENT))
    painter.drawRoundedRect(QRectF(s * 0.52, s * 0.6, s * 0.06, s * 0.26), s * 0.03, s * 0.03)

    painter.end()
    return image


def _to_pillow(image: QImage):
    """QImage → PIL Image. 행 정렬(stride)이 폭과 다를 수 있어 잘라 낸다."""
    from PIL import Image

    converted = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = converted.width(), converted.height()
    pointer = converted.constBits()
    pointer.setsize(converted.sizeInBytes())
    stride = converted.bytesPerLine()
    raw = bytes(pointer)
    rows = [raw[y * stride: y * stride + width * 4] for y in range(height)]
    return Image.frombytes("RGBA", (width, height), b"".join(rows))


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    assert app is not None

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    images = [draw(size) for size in SIZES]

    # QImage 는 .ico 를 못 쓰므로 Pillow 로 묶는다
    from PIL import Image

    frames = [_to_pillow(image) for image in images]
    frames[-1].save(TARGET, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"아이콘 저장: {TARGET} ({', '.join(str(s) for s in SIZES)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
