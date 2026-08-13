"""
한글 음차 표기 흔들림을 흡수하는 자모 단위 매처.

딸보 / 탈보 / 타르보  →  전부 같은 키로 수렴
샤또 마고 / 샤토 마고 / 샤또마르고  →  전부 매칭

의존성 없음. VDI에서도 그대로 동작.
"""

import unicodedata
from functools import lru_cache

# ── 자음 정규화 ────────────────────────────────────────────────
# 된소리·거센소리를 예사소리로 붕괴시킨다.
# 원어의 무성 파열음이 한국어로 옮겨질 때 표기자마다 갈리는 지점이라
# 여기를 뭉개면 변이형이 한 점으로 모인다. (Talbot → 탈보/딸보)
CONSONANT_FOLD = {
    # ── 초성: 된소리·거센소리 → 예사소리
    # 원어의 파열음을 한글로 옮길 때 표기자마다 갈리는 지점.
    "ᄁ": "ᄀ", "ᄏ": "ᄀ",              # ㄲ ㅋ → ㄱ
    "ᄄ": "ᄃ", "ᄐ": "ᄃ",              # ㄸ ㅌ → ㄷ
    "ᄈ": "ᄇ", "ᄑ": "ᄇ",              # ㅃ ㅍ → ㅂ
    "ᄍ": "ᄌ", "ᄎ": "ᄌ",              # ㅉ ㅊ → ㅈ
    "ᄊ": "ᄉ",                        # ㅆ → ㅅ

    # ── 종성: 초성과 같은 코드포인트로 통일 (중요)
    # NFD는 같은 자음도 위치에 따라 다른 코드포인트를 준다.
    # (말=U+11AF, 르=U+1105) 통일하지 않으면 '탈보 vs 타르보'가
    # 삽입 1회가 아니라 치환+삽입으로 계산돼 거리가 4배로 뛴다.
    # 한국어 음절말 중화(ㅅ→[t])는 일부러 적용하지 않는다.
    # 우리가 맞추는 건 발음이 아니라 음차 '표기'이기 때문.
    "ᆨ": "ᄀ", "ᆩ": "ᄀ", "ᆿ": "ᄀ", "ᆪ": "ᄀ",
    "ᆫ": "ᄂ", "ᆬ": "ᄂ", "ᆭ": "ᄂ",
    "ᆮ": "ᄃ", "ᇀ": "ᄃ",
    "ᆯ": "ᄅ", "ᆰ": "ᄅ", "ᆱ": "ᄅ", "ᆲ": "ᄅ",
    "ᆳ": "ᄅ", "ᆴ": "ᄅ", "ᆵ": "ᄅ", "ᆶ": "ᄅ",
    "ᆷ": "ᄆ",
    "ᆸ": "ᄇ", "ᇁ": "ᄇ", "ᆹ": "ᄇ",
    "ᆺ": "ᄉ", "ᆻ": "ᄉ",
    "ᆽ": "ᄌ", "ᆾ": "ᄌ",
    "ᇂ": "ᄒ",
    # ᆼ(종성 이응)은 /ŋ/ 음가가 있으므로 통일하지 않고 그대로 둔다.
    # 초성 ᄋ은 무음이라 아래에서 제거되는데, 여기 섞으면 같이 사라진다.
}

# ── 모음 정규화 ────────────────────────────────────────────────
# 현대 한국어에서 변별력을 잃었거나 음차 시 자유변이인 쌍들.
# 반모음(y-)은 음차 표기에서 자유변이다. 쪼/쬬, 지아코모/자코모,
# 산지오베제/산조베제처럼 같은 원어를 두 가지로 옮기는 일이 흔하다.
# ※ 이 표는 src/matcher/matcher.js 의 VOW_FOLD와 반드시 일치해야 한다.
#    사전 키는 여기서, 조회 키는 저쪽에서 만들어지므로 어긋나면 매칭이 깨진다.
#    tests/test_sync.py 가 자동 검증한다.
VOWEL_FOLD = {
    "ᅢ": "ᅦ", "ᅤ": "ᅨ",              # ㅐ→ㅔ, ㅒ→ㅖ
    "ᅬ": "ᅰ", "ᅫ": "ᅰ",              # ㅚ ㅙ → ㅞ
    "ᅣ": "ᅡ", "ᅧ": "ᅥ",              # ㅑ→ㅏ, ㅕ→ㅓ
    "ᅭ": "ᅩ", "ᅲ": "ᅮ",              # ㅛ→ㅗ, ㅠ→ㅜ
    "ᅨ": "ᅦ",                        # ㅖ→ㅔ
}

# 삽입/탈락이 잦아 편집비용을 깎아줄 자모
CHEAP = {"ᅳ", "ᅮ", "ᄅ"}             # ㅡ ㅜ ㄹ (종성 ㄹ도 위에서 ᄅ로 통일됨)


def to_jamo(text: str) -> str:
    """한글을 자모로 분해하고 변이를 흡수한 정규 키로 변환."""
    out = []
    for ch in unicodedata.normalize("NFD", text):
        if ch.isspace() or ch in "·-–—.,'\"()":
            continue
        ch = CONSONANT_FOLD.get(ch, ch)
        ch = VOWEL_FOLD.get(ch, ch)
        if ch == "ᄋ":                  # 초성 ㅇ은 음가 없음 → 제거
            continue
        out.append(ch)
    return "".join(out)


@lru_cache(maxsize=8192)
def weighted_distance(a: str, b: str) -> float:
    """자모 편집거리(Damerau-Levenshtein). CHEAP 자모의 삽입·삭제는 0.3만 부과.

    ※ src/matcher/matcher.js 의 dist() 와 반드시 같은 결과를 내야 한다.
    """
    prev2 = None
    prev = [0.0] * (len(b) + 1)
    for j in range(1, len(b) + 1):
        prev[j] = prev[j - 1] + (0.3 if b[j - 1] in CHEAP else 1.0)

    for i in range(1, len(a) + 1):
        cur = [prev[0] + (0.3 if a[i - 1] in CHEAP else 1.0)] + [0.0] * len(b)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1]
            else:
                cur[j] = min(
                    prev[j] + (0.3 if a[i - 1] in CHEAP else 1.0),   # 삭제
                    cur[j - 1] + (0.3 if b[j - 1] in CHEAP else 1.0),  # 삽입
                    prev[j - 1] + 1.0,                                # 치환
                )
            # 인접 자모 자리바꿈은 0.6. '다브루초'와 '다부르초'처럼 ㅡ/ㅜ가
            # 도치되는 일이 잦은데, 자리바꿈 항이 없으면 삭제+삽입 2회로
            # 계산돼 실제 체감보다 훨씬 멀어진다. (docs/ARCHITECTURE.md 2단계)
            if (i > 1 and j > 1
                    and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]):
                cur[j] = min(cur[j], prev2[j - 2] + 0.6)
        prev2 = prev
        prev = cur
    return prev[len(b)]


def similarity(a: str, b: str) -> float:
    """0.0 ~ 1.0. 원문자열 두 개를 받아 정규화 후 비교."""
    ja, jb = to_jamo(a), to_jamo(b)
    if not ja or not jb:
        return 0.0
    return 1.0 - weighted_distance(ja, jb) / max(len(ja), len(jb))


class WineNameIndex:
    """한글 표기 → 원어명 조회 인덱스."""

    def __init__(self):
        self.exact = {}      # 정규화 키 → [(한글표기, 원어명)]
        self.entries = []

    def add(self, name_ko: str, name_original: str):
        key = to_jamo(name_ko)
        self.exact.setdefault(key, []).append((name_ko, name_original))
        self.entries.append((key, name_ko, name_original))

    def lookup(self, query: str, threshold: float = 0.82, top_k: int = 5):
        """정확 매칭 우선, 실패 시 fuzzy. (원어명, 한글표기, 점수) 리스트 반환."""
        qk = to_jamo(query)

        if qk in self.exact:
            return [(orig, ko, 1.0) for ko, orig in self.exact[qk]]

        scored = []
        for key, ko, orig in self.entries:
            # 길이 차가 크면 계산 생략 (프루닝)
            if abs(len(key) - len(qk)) > max(len(qk) * 0.4, 3):
                continue
            s = 1.0 - weighted_distance(qk, key) / max(len(qk), len(key))
            if s >= threshold:
                scored.append((orig, ko, round(s, 3)))

        scored.sort(key=lambda x: -x[2])
        return scored[:top_k]


if __name__ == "__main__":
    idx = WineNameIndex()
    for ko, en in [
        ("샤토 탈보", "Chateau Talbot"),
        ("샤토 마고", "Chateau Margaux"),
        ("피노 누아", "Pinot Noir"),
        ("카베르네 소비뇽", "Cabernet Sauvignon"),
        ("주브레 샹베르탱", "Gevrey-Chambertin"),
        ("바롤로", "Barolo"),
    ]:
        idx.add(ko, en)

    tests = ["샤또 딸보", "샤토 타르보", "샤또마르고", "삐노 누아",
             "까베르네 쇼비뇽", "쥬브레 샹베르땡", "바롤로", "리슬링"]

    for q in tests:
        hits = idx.lookup(q)
        if hits:
            orig, ko, score = hits[0]
            print(f"{q:16} → {orig:22} ({score})")
        else:
            print(f"{q:16} → (매칭 없음)")
