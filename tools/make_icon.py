"""앱 아이콘 생성.

이미지 파일을 저장소에 두지 않고 그려서 만든다 — 테마 색이 바뀌면 다시 뽑으면 된다.
모양은 잇다의 상징인 "이어진 노드들" — 서로 다른 색의 노드 넷을 선으로 이어, 작은
크기에서도 "여러 갈래가 하나로 이어진다"는 컨셉이 알록달록하게 남도록 그린다.

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

BACKGROUND = QColor("#1c2230")
LINE = QColor(255, 255, 255, 130)

#: 노드 네 개 — 위치(가로, 세로 비율), 색. 서로 다른 색으로 "여러 갈래"를 표현한다.
NODES = (
    (0.50, 0.16, QColor("#ee7f63")),  # 위 — 코럴 (시작)
    (0.19, 0.50, QColor("#38c6d9")),  # 왼쪽 — 시안
    (0.81, 0.50, QColor("#b083f0")),  # 오른쪽 — 보라
    (0.50, 0.84, QColor("#5fd18c")),  # 아래 — 초록 (도착)
)
#: 노드를 잇는 선 (인덱스 쌍)
EDGES = ((0, 1), (0, 2), (1, 3), (2, 3))
NODE_RADIUS = 0.145


def draw(size: int) -> QImage:
    """서로 다른 색의 노드 넷이 마름모꼴로 이어진 모양."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    s = size

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(BACKGROUND))
    painter.drawRoundedRect(QRectF(0, 0, s, s), s * 0.22, s * 0.22)

    points = [QPointF(x * s, y * s) for x, y, _ in NODES]

    # 연결선 — 노드보다 먼저 그려서 아래에 깔리게 한다
    pen = QPen(LINE, max(1.0, s * 0.05))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    for a, b in EDGES:
        painter.drawLine(points[a], points[b])

    # 노드
    painter.setPen(Qt.PenStyle.NoPen)
    r = s * NODE_RADIUS
    for (x, y, color), point in zip(NODES, points):
        painter.setBrush(QBrush(color))
        painter.drawEllipse(point, r, r)

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
