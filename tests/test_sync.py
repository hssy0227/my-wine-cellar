"""Python ↔ JS 정규화 규칙 동기화 검증.

CLAUDE.md 규칙 1·2가 요구하는 검증이다.

사전 키(key_ko / key_en)는 빌드 시 Python이 만들고, 조회 키는 런타임에
JS(src/matcher/matcher.js)가 만든다. 두 구현이 어긋나면 **에러 없이 매칭만
조용히 틀린다.** 실제로 "가야"(Gaja)가 "Cowra"로 매칭된 사고가 있었다.

두 층위로 검증한다.

  층위 1  테이블 리터럴 대조 — 드리프트를 정확한 메시지로 즉시 잡는다
  층위 2  골든 데이터 대조   — 테이블이 같아도 적용 순서·조건이 갈릴 수 있다

층위 2가 실질적 보증이다. 같은 골든 데이터(data/dist/)를 Python과 JS 양쪽에서
통과시킨다. JS측은 tests/matcher.test.js 가 담당한다.
"""

import csv
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "matcher"))
sys.path.insert(0, str(ROOT / "scripts"))

from jamo_matcher import (  # noqa: E402
    CHEAP,
    CONSONANT_FOLD,
    VOWEL_FOLD,
    similarity,
    to_jamo,
)

MATCHER_JS = ROOT / "src" / "matcher" / "matcher.js"
DIST_CSV = ROOT / "data" / "dist" / "wine_terms.csv"


# ── matcher.js 리터럴 파싱 ────────────────────────────────────────
# JS를 실행하지 않고 소스를 읽는다. node가 없어도 Python 테스트만으로
# 테이블 드리프트를 잡을 수 있어야 하기 때문.

@pytest.fixture(scope="module")
def js_src() -> str:
    assert MATCHER_JS.exists(), f"matcher.js가 없습니다: {MATCHER_JS}"
    return MATCHER_JS.read_text(encoding="utf-8")


def _parse_js_object(src: str, name: str) -> dict:
    m = re.search(r"export const %s\s*=\s*\{(.*?)\};" % name, src, re.S)
    assert m, f"matcher.js에서 {name} 리터럴을 찾지 못했습니다"
    return dict(re.findall(r"'([^']+)'\s*:\s*'([^']+)'", m.group(1)))


def _parse_js_set(src: str, name: str) -> set:
    m = re.search(r"export const %s\s*=\s*new Set\(\[(.*?)\]\);" % name, src, re.S)
    assert m, f"matcher.js에서 {name} Set을 찾지 못했습니다"
    return set(re.findall(r"'([^']+)'", m.group(1)))


def _parse_js_regex(src: str, name: str) -> tuple[str, str]:
    """정규식 리터럴을 (본문, 플래그)로 반환."""
    m = re.search(r"export const %s\s*=\s*/(.+?)/([a-z]*);" % name, src, re.S)
    assert m, f"matcher.js에서 {name} 정규식을 찾지 못했습니다"
    return m.group(1), m.group(2)


def _diff_report(label: str, py: dict, js: dict) -> str:
    """어느 키가 어떻게 다른지 사람이 읽을 수 있게 출력한다.

    단순 assert py == js 는 30여 개 항목 앞에서 읽을 수 없는 메시지를 낸다.
    """
    lines = [f"{label} 불일치:"]
    for k in sorted(set(py) - set(js)):
        lines.append(f"  Python에만 있음:  {k!r} -> {py[k]!r}")
    for k in sorted(set(js) - set(py)):
        lines.append(f"  JS에만 있음:      {k!r} -> {js[k]!r}")
    for k in sorted(set(py) & set(js)):
        if py[k] != js[k]:
            lines.append(f"  값이 다름: {k!r}  Python={py[k]!r}  JS={js[k]!r}")
    return "\n".join(lines)


# ── 층위 1: 테이블 리터럴 대조 ────────────────────────────────────

def test_consonant_fold_동일(js_src):
    """CONSONANT_FOLD(py) == CONS_FOLD(js). 이름만 다르고 내용은 같아야 한다."""
    js = _parse_js_object(js_src, "CONS_FOLD")
    assert CONSONANT_FOLD == js, _diff_report("자음 정규화 테이블", CONSONANT_FOLD, js)


def test_vowel_fold_동일(js_src):
    """VOWEL_FOLD(py) == VOW_FOLD(js).

    과거 JS에만 반모음 규칙(ㅑ→ㅏ)을 넣고 Python에는 안 넣어 "가야"(Gaja)가
    "Cowra"로 매칭된 사고가 있었다. 그 재발을 막는 케이스다.
    """
    js = _parse_js_object(js_src, "VOW_FOLD")
    assert VOWEL_FOLD == js, _diff_report("모음 정규화 테이블", VOWEL_FOLD, js)


def test_cheap_동일(js_src):
    js = _parse_js_set(js_src, "CHEAP")
    assert CHEAP == js, (
        f"CHEAP 불일치:\n  Python에만: {sorted(CHEAP - js)}\n  JS에만: {sorted(js - CHEAP)}"
    )


def test_en_prefix_정규식_동일(js_src):
    """접두어 제거 규칙이 build.py와 matcher.js에서 같아야 한다.

    여기가 갈리면 저장 키와 조회 키가 어긋난다. 실제 사례:
    JS가 맨단어 'dom'을 떼는 바람에 Dom Perignon의 저장 키('dom perignon')와
    조회 키('perignon')가 갈려 정확 매칭이 실패했다.
    """
    from build import EN_PREFIX_RE as PY_RE

    js_body, js_flags = _parse_js_regex(js_src, "EN_PREFIX_RE")
    assert "i" in js_flags, "matcher.js의 EN_PREFIX_RE에 대소문자 무시(i) 플래그가 없습니다"

    def alternatives(pattern: str) -> list[str]:
        m = re.search(r"\^\((.+)\)\\s\+$", pattern)
        assert m, f"예상과 다른 정규식 형태입니다: {pattern!r}"
        return m.group(1).split("|")

    py_alts, js_alts = alternatives(PY_RE.pattern), alternatives(js_body)
    assert py_alts == js_alts, (
        "접두어 목록 불일치:\n"
        f"  build.py에만:  {sorted(set(py_alts) - set(js_alts))}\n"
        f"  matcher.js에만: {sorted(set(js_alts) - set(py_alts))}\n"
        f"  (순서까지 같아야 함)\n  build.py  : {py_alts}\n  matcher.js: {js_alts}"
    )


def test_편집거리_상수_동일(js_src):
    """CHEAP 비용(0.3)과 자리바꿈 비용(0.6)이 양쪽에 모두 있어야 한다.

    docs/ARCHITECTURE.md 2단계가 규정한 값이다. 한쪽에만 자리바꿈 항이 있으면
    같은 질의에 다른 점수가 나온다(실측 0.50 vs 0.85).
    """
    py_src = (ROOT / "src" / "matcher" / "jamo_matcher.py").read_text(encoding="utf-8")
    for const, desc in [("0.3", "CHEAP 자모 삽입·삭제 비용"), ("0.6", "인접 자모 자리바꿈 비용")]:
        assert const in py_src, f"jamo_matcher.py에 {desc}({const})가 없습니다"
        assert const in js_src, f"matcher.js에 {desc}({const})가 없습니다"


# ── 층위 2: 골든 데이터 대조 ──────────────────────────────────────

@pytest.fixture(scope="module")
def dist_rows() -> list[dict]:
    assert DIST_CSV.exists(), (
        f"{DIST_CSV}가 없습니다. 먼저 `python3 scripts/build.py`를 실행하세요."
    )
    with open(DIST_CSV, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows, "wine_terms.csv가 비어 있습니다"
    return rows


def test_to_jamo가_저장된_key_ko를_재현한다(dist_rows):
    """to_jamo(name_ko) == key_ko — 전 행.

    테이블이 같아도 적용 순서나 제거 문자 집합이 갈리면 여기서 잡힌다.
    """
    bad = [(r["name_ko"], r["key_ko"], to_jamo(r["name_ko"]))
           for r in dist_rows if to_jamo(r["name_ko"]) != r["key_ko"]]
    assert not bad, (
        f"key_ko 불일치 {len(bad)}건 / 전체 {len(dist_rows)}행\n"
        + "\n".join(f"  {ko!r}: 저장={stored!r} 계산={calc!r}" for ko, stored, calc in bad[:10])
    )


def test_search_key_en이_저장된_key_en을_재현한다(dist_rows):
    """search_key_en(접두어 제거된 name_en) == key_en — 전 행.

    build.py가 key_en을 만들 때와 똑같은 순서로 적용해야 한다.
    """
    from build import EN_PREFIX_RE, search_key_en

    def key_en(name_en: str) -> str:
        return search_key_en(EN_PREFIX_RE.sub("", name_en).strip() or name_en)

    bad = [(r["name_en"], r["key_en"], key_en(r["name_en"]))
           for r in dist_rows if key_en(r["name_en"]) != r["key_en"]]
    assert not bad, (
        f"key_en 불일치 {len(bad)}건 / 전체 {len(dist_rows)}행\n"
        + "\n".join(f"  {en!r}: 저장={stored!r} 계산={calc!r}" for en, stored, calc in bad[:10])
    )


# ── CLAUDE.md의 판단 기준을 못 박는다 ─────────────────────────────
# "이 차이는 정규화가 흡수하므로 별칭이 불필요하다"는 규정이 실제로
# 성립하는지 검증한다. 규칙을 건드리면 여기서 먼저 깨진다.

@pytest.mark.parametrize("a,b,사유", [
    ("딸보", "탈보", "된소리·거센소리"),
    ("샤또마고", "샤또 마고", "띄어쓰기"),
    ("쪼", "쬬", "반모음"),
    ("까베르네", "카베르네", "된소리"),
    ("샤또 딸보", "샤토 탈보", "된소리 + 띄어쓰기 복합"),
    ("디상", "디샹", "반모음 (아래 주석 참조)"),
])
def test_정규화가_흡수하는_차이는_같은_키가_된다(a, b, 사유):
    """CLAUDE.md '자동 흡수 — 별칭 불필요' 표의 케이스.

    ※ '디상 / 디샹'은 CLAUDE.md의 판단 기준 표에서 "모음이 실제로 다름 →
      별칭 필요"로 분류돼 있으나, 실제로는 반모음 규칙(ㅑ→ㅏ)이 흡수해
      같은 키가 된다. 사전 데이터도 이를 뒷받침한다 — wine_terms.csv의
      '디샹'(alias)과 '디상'(stripped)은 key_ko가 둘 다 '디상'으로 동일하다.
      문서 쪽 분류가 구현과 어긋난 상태다. 여기서는 구현의 실제 동작을 고정한다.
    """
    assert to_jamo(a) == to_jamo(b), (
        f"{사유}: {a!r}와 {b!r}가 같은 키여야 하는데 다릅니다 "
        f"({to_jamo(a)!r} != {to_jamo(b)!r})"
    )


@pytest.mark.parametrize("a,b,사유", [
    ("지아코모", "자코모", "반모음 음절 분리"),
    ("산지오베제", "산조베제", "반모음 음절 분리"),
])
def test_반모음_음절차이는_편집거리가_흡수한다(a, b, 사유):
    """'지아 → 자' 류는 정규화가 아니라 편집거리가 흡수한다.

    CONSONANT_FOLD/VOWEL_FOLD 주석이 이 예시들을 반모음 근거로 들고 있지만,
    반모음 접기가 동일 키를 만드는 건 '쪼/쬬'처럼 한 음절 안에서 끝나는
    경우뿐이다. 음절 수가 갈리면(지아 2음절 vs 자 1음절) ㅣ 하나가 더 들어가
    키가 달라지고, 대신 편집거리에서 높은 유사도로 잡힌다.
    """
    assert to_jamo(a) != to_jamo(b), (
        f"{사유}: {a!r}와 {b!r}가 같은 키가 됐습니다. 정규화가 과하게 뭉개고 있습니다"
    )
    assert similarity(a, b) >= 0.85, (
        f"{사유}: {a!r}와 {b!r}의 유사도가 {similarity(a, b):.3f}로 너무 낮습니다. "
        "편집거리로도 못 잡으면 별칭이 필요해집니다"
    )


@pytest.mark.parametrize("a,b,사유", [
    ("샤르도네", "샤도네이", "음절 구성이 다름"),
])
def test_별칭이_필요한_차이는_다른_키가_된다(a, b, 사유):
    """CLAUDE.md '별칭 필요' 표의 케이스.

    이쪽이 같은 키가 되면 정규화가 과하게 뭉개고 있다는 뜻이고,
    서로 다른 이름끼리 오매칭이 늘어난다.
    """
    assert to_jamo(a) != to_jamo(b), (
        f"{사유}: {a!r}와 {b!r}는 다른 키여야 하는데 같습니다 ({to_jamo(a)!r})"
    )
