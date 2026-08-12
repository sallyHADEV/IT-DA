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


#: 이 크기보다 작은 프레임은 옛날 BMP 방식으로 담는다. 작업표시줄·창 아이콘을 읽는
#: 구식 Win32 경로(ExtractAssociatedIcon 등)가 PNG 압축 프레임을 못 읽어 아이콘이
#: 깨지거나 비어 보이는 경우가 있다 — 실측으로 확인했다(exe에서 뽑아보면 조각남).
#: 256 은 BMP로 담기엔 너무 커서(그리고 관례상) PNG 그대로 둔다.
PNG_THRESHOLD = 256


def _bmp_frame(image) -> bytes:
    """32bpp BGRA, bottom-up DIB — ICO 안에 넣을 구식(classic) 프레임."""
    import struct

    img = image.convert("RGBA")
    w, h = img.size
    pixels = img.tobytes()  # RGBA, top-down

    xor = bytearray(w * h * 4)
    for y in range(h):
        src_row = pixels[y * w * 4:(y + 1) * w * 4]
        dst_y = h - 1 - y  # bottom-up으로 뒤집는다
        dst_off = dst_y * w * 4
        for x in range(w):
            r, g, b, a = src_row[x * 4:x * 4 + 4]
            xor[dst_off + x * 4:dst_off + x * 4 + 4] = bytes((b, g, r, a))

    and_row_bytes = ((w + 31) // 32) * 4
    and_mask = bytes(and_row_bytes * h)  # 전부 0 = 불투명(알파 채널이 실제 투명도를 담당)

    header = struct.pack(
        "<IiiHHIIiiII",
        40, w, h * 2, 1, 32, 0, len(xor) + len(and_mask), 0, 0, 0, 0,
    )
    return header + bytes(xor) + and_mask


def _write_ico(frames: dict[int, "object"]) -> None:
    """크기별 프레임을 직접 묶어 .ico 로 쓴다.

    Pillow 의 ``Image.save(..., sizes=[...])`` 는 이미지 하나를 받아 내부에서 리샘플하며
    전부 PNG로 인코딩한다 — 크기별로 따로 그린 프레임을 못 쓰고, 작은 크기까지 PNG라
    구식 아이콘 로더에서 깨진다. 그래서 직접 ICONDIR/ICONDIRENTRY를 만든다.
    """
    import io
    import struct

    sizes = sorted(frames)
    entries = []
    blob = bytearray()
    offset = 6 + 16 * len(sizes)

    for size in sizes:
        frame = frames[size]
        if size >= PNG_THRESHOLD:
            buf = io.BytesIO()
            frame.save(buf, format="PNG")
            data = buf.getvalue()
        else:
            data = _bmp_frame(frame)
        b = size if size < 256 else 0
        entries.append(struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(data), offset))
        blob += data
        offset += len(data)

    with open(TARGET, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(sizes)))
        for entry in entries:
            f.write(entry)
        f.write(bytes(blob))


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    assert app is not None

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    frames = {size: _to_pillow(draw(size)) for size in SIZES}
    _write_ico(frames)
    print(f"아이콘 저장: {TARGET} ({', '.join(str(s) for s in SIZES)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
