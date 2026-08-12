"""배포용 실행 파일 빌드.

    python tools/build.py            # 빌드 + 검증
    python tools/build.py --clean    # 이전 산출물 지우고 처음부터
    python tools/build.py --verify   # 빌드하지 않고 기존 산출물만 검증

빌드가 끝나면 **실제로 실행해 자체 점검(`--selftest`)을 돌린다.** PyInstaller 는 빠뜨린
모듈이 있어도 조용히 성공하기 때문에, 실행해 보지 않으면 배포하고 나서야 안다.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "itda"
EXE = DIST / "itda.exe"
CHECK_EXE = DIST / "itda-check.exe"
BUILD = ROOT / "build"


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(command)}")
    # PyInstaller 는 한국어 Windows 에서 cp949 로 출력한다. utf-8 로 읽으면 터진다.
    kwargs.setdefault("encoding", "utf-8")
    kwargs.setdefault("errors", "replace")
    return subprocess.run(command, cwd=ROOT, **kwargs)


def make_icon() -> None:
    print("아이콘 생성")
    result = run([sys.executable, "tools/make_icon.py"], capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout, result.stderr)
        raise SystemExit("아이콘 생성 실패")


def clean() -> None:
    for folder in (BUILD, ROOT / "dist"):
        if folder.exists():
            print(f"삭제: {folder}")
            shutil.rmtree(folder, ignore_errors=True)


def build() -> None:
    started = time.perf_counter()
    result = run([sys.executable, "-m", "PyInstaller", "itda.spec", "--noconfirm"])
    if result.returncode != 0:
        raise SystemExit("빌드 실패")
    print(f"빌드 완료 ({time.perf_counter() - started:.1f}초)")


def _decode(raw: bytes | None) -> str:
    """묶은 실행 파일의 출력 디코딩.

    PyInstaller 부트로더는 PYTHONIOENCODING 을 무시하고 콘솔 코드페이지로 내보낸다.
    한국어 Windows 면 cp949 다. 순서대로 시도한다.
    """
    if not raw:
        return ""
    for encoding in ("utf-8", "cp949", "mbcs"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def folder_size_mb(folder: Path) -> float:
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file()) / 1024 / 1024


def verify() -> int:
    """묶은 실행 파일을 실제로 돌려 확인한다.

    창 프로그램(itda.exe)은 stdout 이 없어 출력이 보이지 않는다. 그래서 같은 코드의 콘솔 판
    (itda-check.exe)으로 점검한다 — 없으면 검증 자체가 의미 없으므로 실패로 본다.
    """
    if not EXE.exists():
        print(f"실행 파일이 없습니다: {EXE}")
        return 1
    if not CHECK_EXE.exists():
        print(f"검증용 실행 파일이 없습니다: {CHECK_EXE}")
        return 1

    print(f"\n산출물: {DIST}  ({folder_size_mb(DIST):.0f} MB)")

    failed = False
    for name, args in [("버전", ["--version"]), ("자체 점검", ["--selftest"])]:
        print(f"\n--- {name} ---")
        result = subprocess.run([str(CHECK_EXE), *args], capture_output=True, timeout=300)
        output = _decode(result.stdout).strip()
        print(output or "(출력 없음)")
        if result.returncode != 0 or not output:
            print(_decode(result.stderr).strip())
            failed = True

    if failed:
        print("\n검증 실패 — 빠진 모듈이 없는지 위 출력을 확인하세요")
        return 1
    print("\n검증 통과. dist/itda 폴더를 통째로 압축해 배포하세요.")
    print("참고: OCR 을 쓰려면 대상 PC 에 Tesseract 설치가 필요합니다(한국어 데이터 포함).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="잇다 배포 빌드")
    parser.add_argument("--clean", action="store_true", help="이전 산출물 삭제 후 빌드")
    parser.add_argument("--verify", action="store_true", help="빌드 없이 검증만")
    args = parser.parse_args()

    if args.verify:
        return verify()
    if args.clean:
        clean()

    make_icon()
    build()
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
