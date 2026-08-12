"""화면 캡처.

PyQt6 의 QScreen 만 쓴다. mss 같은 추가 의존성을 넣지 않기 위해서다(파이썬 3.14 에서
휠이 없는 패키지가 많다).

**모든 좌표와 결과 이미지는 물리 픽셀 기준이다.** 디스플레이 배율(150% 등)이 걸려 있어도
캡처 이미지 1픽셀 = 실제 화면 1픽셀이 되도록 맞춘다. 자세한 규칙은
:mod:`itda.vision.coords` 참고.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PyQt6.QtCore import QRect, Qt, QThread
from PyQt6.QtGui import QGuiApplication, QImage, QPainter, QPixmap, QScreen

from itda.vision import coords
from itda.vision.coords import ScreenInfo


def on_gui_thread() -> bool:
    """지금 스레드가 GUI(메인) 스레드인가.

    ``QScreen.grabWindow``/``QPixmap``/``QPainter`` 는 GUI 스레드 밖에서 부르면 Qt 가
    그 자리에서 죽인다(Fatal). 멀티 플로우는 플로우마다 ``threading.Thread`` 를 새로 띄우므로
    (:mod:`itda.engine.scheduler`), 그 스레드에서 실수로 Qt 캡처 경로를 타지 않도록 막는
    지점이 필요하다.
    """
    app = QGuiApplication.instance()
    if app is None:
        return False
    return QThread.currentThread() is app.thread()


def virtual_geometry() -> QRect:
    """모든 모니터를 합친 가상 데스크톱 영역 (물리 픽셀)."""
    area = coords.virtual_rect(coords.current_screens(), physical=True)
    return QRect(area.x, area.y, area.width, area.height)


def _qscreen(info: ScreenInfo) -> QScreen | None:
    for screen in QGuiApplication.screens():
        if screen.name() == info.name:
            return screen
    return QGuiApplication.primaryScreen()


def _grab_screen(info: ScreenInfo) -> QPixmap:
    """모니터 하나를 물리 픽셀 크기로 캡처한다."""
    screen = _qscreen(info)
    if screen is None:
        return QPixmap()
    logical = info.logical
    shot = screen.grabWindow(0, 0, 0, logical.width, logical.height)
    # grabWindow 는 배율이 걸린 픽스맵을 준다. 원시 픽셀로 다루기 위해 배율 표시를 지운다.
    shot.setDevicePixelRatio(1.0)
    physical = info.physical
    if shot.width() != physical.width or shot.height() != physical.height:
        shot = shot.scaled(
            physical.width,
            physical.height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return shot


def grab_all() -> QPixmap:
    """가상 데스크톱 전체를 한 장으로 캡처한다 (물리 픽셀)."""
    screens = coords.current_screens()
    area = coords.virtual_rect(screens, physical=True)
    if area.width <= 0 or area.height <= 0:
        return QPixmap()

    canvas = QPixmap(area.width, area.height)
    canvas.setDevicePixelRatio(1.0)
    canvas.fill()
    painter = QPainter(canvas)
    try:
        for info in screens:
            shot = _grab_screen(info)
            if shot.isNull():
                continue
            painter.drawPixmap(info.physical.x - area.x, info.physical.y - area.y, shot)
    finally:
        painter.end()
    return canvas


def grab_rect(x: int, y: int, w: int, h: int) -> QPixmap:
    """물리 픽셀 좌표 기준의 사각형을 캡처한다."""
    if w <= 0 or h <= 0:
        return QPixmap()
    screens = coords.current_screens()
    target = QRect(x, y, w, h)

    info = coords.screen_at_physical(screens, x, y)
    if info is not None:
        physical = info.physical
        screen_rect = QRect(physical.x, physical.y, physical.width, physical.height)
        if screen_rect.contains(target):
            shot = _grab_screen(info)
            return shot.copy(target.translated(-screen_rect.topLeft()))

    # 모니터 경계를 걸치는 영역은 전체를 찍어서 잘라낸다
    full = grab_all()
    area = coords.virtual_rect(screens, physical=True)
    return full.copy(target.translated(-area.x, -area.y))


def grab_array(rect: tuple[int, int, int, int] | None = None) -> np.ndarray:
    """화면을 BGR 배열로 찍는다 — **작업 스레드에서도 안전한 경로**.

    Qt 의 grabWindow 는 GUI 스레드 전용이라, 여러 플로우를 동시에 돌릴 때 쓸 수 없다.
    Windows 에서는 GDI(BitBlt)로 찍고, 실패하거나 다른 OS 면 Qt 경로로 되돌아간다 —
    **단 GUI 스레드일 때만.** 작업 스레드에서 GDI 마저 실패하면, Qt 로 폴백하는 대신
    빈 배열을 돌려준다. Qt 폴백을 그대로 태우면 Fatal 크래시로 앱 전체가 죽는다.
    """
    from itda.vision import gdi_capture

    if gdi_capture.is_available():
        image = gdi_capture.grab(*rect) if rect else gdi_capture.grab()
        if image.size:
            return image

    if not on_gui_thread():
        return _empty_bgr()

    pixmap = grab_rect(*rect) if rect else grab_all()
    return pixmap_to_bgr(pixmap)


def _empty_bgr() -> np.ndarray:
    return np.zeros((0, 0, 3), dtype=np.uint8)


def pixmap_to_bgr(pixmap: QPixmap) -> np.ndarray:
    """QPixmap → OpenCV BGR 배열."""
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB888)
    width, height = image.width(), image.height()
    if width == 0 or height == 0:
        return np.zeros((0, 0, 3), dtype=np.uint8)
    ptr = image.constBits()
    ptr.setsize(image.sizeInBytes())
    # 행 정렬(stride)이 폭과 다를 수 있으므로 잘라 낸다
    buffer = np.frombuffer(ptr, dtype=np.uint8).reshape(height, image.bytesPerLine())
    rgb = buffer[:, : width * 3].reshape(height, width, 3)
    return rgb[:, :, ::-1].copy()


def bgr_to_qimage(array: np.ndarray) -> QImage:
    """OpenCV BGR 배열 → QImage (복사본)."""
    if array.size == 0:
        return QImage()
    height, width = array.shape[:2]
    rgb = np.ascontiguousarray(array[:, :, ::-1])
    return QImage(rgb.data, width, height, width * 3, QImage.Format.Format_RGB888).copy()


def bgr_to_pixmap(array: np.ndarray) -> QPixmap:
    return QPixmap.fromImage(bgr_to_qimage(array))


def save_pixmap(pixmap: QPixmap, path: Path | str) -> bool:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return pixmap.save(str(path), "PNG")


def load_bgr(path: Path | str) -> np.ndarray:
    """파일에서 BGR 배열로 읽는다. 한글 경로도 안전하게 처리한다.

    객체가 지워진 이미지를 가리키는 일이 흔하므로, 없는 파일은 예외 대신 빈 배열이다.
    """
    import cv2

    path = Path(path)
    if not path.is_file():
        return np.zeros((0, 0, 3), dtype=np.uint8)
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return np.zeros((0, 0, 3), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return image if image is not None else np.zeros((0, 0, 3), dtype=np.uint8)


def save_bgr(array: np.ndarray, path: Path | str) -> bool:
    """BGR 배열을 PNG 로 쓴다 (한글 경로 안전)."""
    import cv2

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(".png", array)
    if not ok:
        return False
    buffer.tofile(str(path))
    return True
