"""식별자 생성.

노드/액션/객체/상태는 모두 짧은 접두사 + 랜덤 8자리를 쓴다.
파일에 그대로 저장되므로 사람이 읽었을 때 종류를 알 수 있는 편이 낫다.
"""

from __future__ import annotations

import re
import uuid

_SAFE = re.compile(r"[^0-9A-Za-z_가-힣]+")


def new_id(prefix: str) -> str:
    """``prefix`` 로 시작하는 새 식별자를 만든다. 예: ``new_id("n") -> "n_3f2a91c4"``."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def slugify(text: str, fallback: str = "item") -> str:
    """사람이 입력한 이름을 파일명으로 쓸 수 있게 정리한다. 한글은 그대로 둔다."""
    cleaned = _SAFE.sub("_", (text or "").strip()).strip("_")
    return cleaned or fallback


def unique_name(base: str, taken: set[str]) -> str:
    """``taken`` 에 없는 이름을 만든다. 충돌하면 ``base 2``, ``base 3`` ... 로 늘린다."""
    if base not in taken:
        return base
    i = 2
    while f"{base} {i}" in taken:
        i += 1
    return f"{base} {i}"
