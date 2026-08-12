# 개발 가이드

소스에서 실행하거나 코드를 고치려는 사람을 위한 문서다. 그냥 쓰기만 할 거라면
[README](README.md#다운로드)의 Releases zip이면 충분하다.

## 의존성

| 패키지 | 역할 |
|---|---|
| [PyQt6](https://pypi.org/project/PyQt6/) | GUI 프레임워크 — 캔버스·도크·대화상자 전부 |
| [opencv-python](https://pypi.org/project/opencv-python/) | 이미지 전처리·템플릿 매칭 (이미지 찾기/대기) |
| [numpy](https://pypi.org/project/numpy/) | 화면 캡처 배열 연산 |
| [Pillow](https://pypi.org/project/Pillow/) | 이미지 인코딩/저장 |
| [pytest](https://pypi.org/project/pytest/) | 테스트 |

```bash
pip install -r requirements.txt
```

OCR 액션까지 테스트하려면 Tesseract도 필요하다 — [README의 OCR 설치 안내](README.md#ocr글자-읽기--tesseract-별도-설치) 참고.

## 실행

```bash
python -m itda
```

프로젝트 폴더를 바로 열려면: `python -m itda C:\경로\내프로젝트`

## 빌드 (실행 파일 만들기)

```bash
python tools/build.py
```

아이콘 생성 → PyInstaller 빌드 → 실제로 실행해 자체 점검까지 한 번에 한다.
결과는 `dist/itda` 폴더이며, 폴더째 압축해 넘기면 파이썬 없이 실행된다
(`itda.exe`가 같은 폴더의 `_internal`을 참조하므로 둘을 분리하면 안 된다).

`itda-check.exe --selftest`는 콘솔 판 — 빌드가 온전한지 확인할 때 쓴다
(창 프로그램은 stdout이 없어 출력이 보이지 않는다).

## 테스트

```bash
python -m pytest tests -q
```

## 구조

| 경로 | 역할 |
|---|---|
| `itda/core/` | 데이터 모델, 프로젝트 IO, 파라미터 스키마, 레지스트리, 변수, 타이밍, 이벤트 버스 |
| `itda/actions/` | 액션 타입 정의(파라미터 스키마 + 실행부) — 인식/입력/흐름/데이터/도구 |
| `itda/vision/` | 화면 캡처, 이미지 매칭, OCR, 영역 자동 분할 |
| `itda/engine/` | 실행 엔진, 스케줄러(멀티 플로우), 입력 중재자, 상황 판정/전이, 데모 재생기 |
| `itda/gui/` | 메인 윈도우, 캔버스, 패널, 대화상자, 작업 도구 |

설계 배경은 [docs/설계.md](docs/설계.md) 참고.

## 액션 추가하기

클래스 하나만 등록하면 팔레트·속성 폼·저장/로드가 전부 따라온다. GUI 코드는 건드리지 않는다.

```python
@register_action
class MyAction(ActionType):
    ID = "my_action"
    LABEL = "내 동작"
    CATEGORY = "입력"
    PARAMS = [Field("count", "int", "횟수", 1, minimum=1, maximum=99)]

    @classmethod
    def summary(cls, params):
        return f"내 동작 {params['count']}회"
```

## 프로젝트 파일 포맷

프로젝트는 폴더 하나이며 내용은 전부 JSON + PNG다. 플로우 파일을 복사해 다른 프로젝트에
붙여 넣으면 그대로 모듈이 된다.

```
MyProject/
  project.json          타이밍 프로파일, 엔트리 플로우/우선순위, 전역 변수
  flows/*.flow.json     플로우 하나 = 파일 하나
  objects/objects.json  타겟 객체 (이름/태그/이미지 목록/매칭 옵션)
  objects/img/*.png
  states/states.json    상황 정의 + 전이 그래프 + 워처 설정
```
