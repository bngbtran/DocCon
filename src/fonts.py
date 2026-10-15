"""PDF font name → Word font family + style, and text clean-up helpers."""
import re
from typing import Tuple

# Normalised (lower-case, no spaces/dashes) PDF base names → Word family.
_KNOWN = {
    "timesnewroman": "Times New Roman",
    "times": "Times New Roman",
    "timesroman": "Times New Roman",
    "arial": "Arial",
    "arialnarrow": "Arial Narrow",
    "helvetica": "Arial",
    "helveticaneue": "Arial",
    "couriernew": "Courier New",
    "courier": "Courier New",
    "symbol": "Symbol",
    "wingdings": "Wingdings",
    "zapfdingbats": "Wingdings",
    "calibri": "Calibri",
    "calibrilight": "Calibri Light",
    "cambria": "Cambria",
    "cambriamath": "Cambria Math",
    "aptos": "Aptos",
    "aptosdisplay": "Aptos Display",
    "verdana": "Verdana",
    "georgia": "Georgia",
    "tahoma": "Tahoma",
    "segoeui": "Segoe UI",
    "garamond": "Garamond",
    "bookantiqua": "Book Antiqua",
    "palatinolinotype": "Palatino Linotype",
    "centurygothic": "Century Gothic",
    "consolas": "Consolas",
    "cascadiacode": "Cascadia Code",
    "cascadiamono": "Cascadia Mono",
    "lucidaconsole": "Lucida Console",
    "trebuchetms": "Trebuchet MS",
    "comicsansms": "Comic Sans MS",
    "roboto": "Roboto",
    "opensans": "Open Sans",
    "notosans": "Noto Sans",
    "notoserif": "Noto Serif",
    "liberationserif": "Times New Roman",
    "liberationsans": "Arial",
    "liberationmono": "Courier New",
    "dejavusans": "DejaVu Sans",
    "dejavuserif": "DejaVu Serif",
    "dejavusansmono": "DejaVu Sans Mono",
    "msgothic": "MS Gothic",
    "mssmincho": "MS Mincho",
    "simsun": "SimSun",
    "simhei": "SimHei",
    "malgungothic": "Malgun Gothic",
}

# Fonts shipped with Windows / Office: no substitution hint needed.
COMMON_FONTS = {
    "Times New Roman", "Arial", "Arial Narrow", "Courier New", "Symbol",
    "Wingdings", "Calibri", "Calibri Light", "Cambria", "Cambria Math",
    "Aptos", "Aptos Display", "Verdana", "Georgia", "Tahoma", "Segoe UI",
    "Garamond", "Book Antiqua", "Palatino Linotype", "Century Gothic",
    "Consolas", "Cascadia Code", "Cascadia Mono", "Lucida Console",
    "Trebuchet MS", "Comic Sans MS", "MS Gothic", "MS Mincho", "SimSun",
    "SimHei", "Malgun Gothic",
}

_STYLE_WORDS = re.compile(
    r"(bolditalic|boldoblique|semibold|demibold|extrabold|ultrabold|bold|black|heavy|"
    r"italic|oblique|regular|roman|book|normal|medium|light|thin)",
    re.I,
)
_SUBSET = re.compile(r"^[A-Z]{6}\+")
_LEGACY_VN = re.compile(r"^\.?vn|^vni[-_ ]|^vntime|^vnarial", re.I)


def split_font(pdf_name: str, flags: int = 0) -> Tuple[str, bool, bool]:
    """Return (word_family, bold, italic) for a PDF font name and span flags."""
    name = _SUBSET.sub("", pdf_name or "").strip()
    bold = bool(flags & 16)
    italic = bool(flags & 2)

    base, style = name, ""
    for sep in (",", "-"):
        if sep in base:
            base, _, rest = base.partition(sep)
            style = rest + " " + style
    for suffix in ("PSMT", "MT", "PS"):
        if base.endswith(suffix) and len(base) > len(suffix) + 2:
            base = base[: -len(suffix)]
            break

    s = style.lower()
    if any(w in s for w in ("bold", "black", "heavy")):
        bold = True
    if "italic" in s or "oblique" in s:
        italic = True

    # Style words glued to the family, e.g. "CascadiaCodeRoman", "ArialBold".
    known = re.sub(r"[\s_\-]", "", base).lower() in _KNOWN
    m = None if known or " " in base else re.search(r"(Bold|Italic|Oblique|Roman|Regular|Book)+$", base)
    if m and m.start() > 2:
        tail = m.group(0).lower()
        bold = bold or "bold" in tail
        italic = italic or "italic" in tail or "oblique" in tail
        base = base[: m.start()]

    key = re.sub(r"[\s_\-]", "", base).lower()
    if key in _KNOWN:
        return _KNOWN[key], bold, italic
    for pat, fam in _KNOWN.items():
        if len(pat) >= 5 and key.startswith(pat) and key[len(pat):] in ("", "ps", "mt", "std", "pro"):
            return fam, bold, italic

    if not key or key.startswith("___wrd") or key.startswith("glyphless") or key.startswith("t3font"):
        return "", bold, italic
    # CamelCase → words: "DroidSansMono" → "Droid Sans Mono", "SegoeUI" → "Segoe UI".
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", base)
    spaced = re.sub(r"[_]+", " ", spaced).strip()
    return spaced, bold, italic


def is_legacy_vn_font(pdf_name: str) -> bool:
    """TCVN3 / VNI fonts store Vietnamese with a non-Unicode encoding."""
    return bool(_LEGACY_VN.match(_SUBSET.sub("", pdf_name or "")))


_ALT = {
    "Aptos": ("Calibri", "swiss"), "Aptos Display": ("Calibri Light", "swiss"),
    "Calibri": ("Arial", "swiss"), "Calibri Light": ("Arial", "swiss"),
    "Cambria": ("Times New Roman", "roman"), "Segoe UI": ("Arial", "swiss"),
    "Cascadia Code": ("Consolas", "modern"), "Cascadia Mono": ("Consolas", "modern"),
    "Consolas": ("Courier New", "modern"), "Roboto": ("Arial", "swiss"),
    "Open Sans": ("Arial", "swiss"), "Noto Sans": ("Arial", "swiss"),
    "Noto Serif": ("Times New Roman", "roman"), "DejaVu Sans": ("Verdana", "swiss"),
    "DejaVu Serif": ("Georgia", "roman"), "DejaVu Sans Mono": ("Consolas", "modern"),
}


def font_hint(family: str, mono: bool, serif: bool) -> Tuple[str, str, str]:
    """(altName, w:family, w:pitch) used by Word to substitute a missing font."""
    if family in _ALT:
        alt, fam = _ALT[family]
        return alt, fam, "fixed" if fam == "modern" else "variable"
    low = family.lower()
    mono = mono or "mono" in low or "code" in low or "courier" in low
    serif = serif and "sans" not in low
    if mono:
        return "Courier New", "modern", "fixed"
    if serif:
        return "Times New Roman", "roman", "variable"
    return "Arial", "swiss", "variable"


# Broken ToUnicode maps in Word→PDF exports of Vietnamese (ư/Ư come out as ƣ/Ƣ).
_FIXES = str.maketrans({"ƣ": "ư", "Ƣ": "Ư"})
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(text: str) -> str:
    return _CTRL.sub("", text.translate(_FIXES))


def garbage_ratio(text: str) -> float:
    """Share of characters that indicate an unusable text layer."""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    bad = sum(1 for c in chars if c == "�" or ord(c) < 32)
    return bad / len(chars)
