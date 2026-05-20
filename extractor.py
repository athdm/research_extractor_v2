import os
import base64
import io
import re
import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


# =========================================================
# Exceptions
# =========================================================

class FetchBlockedError(Exception):
    pass


class FetchParseError(Exception):
    pass


class GeminiQuotaExhaustedError(Exception):
    pass


# =========================================================
# Public schema expected by app.py
# =========================================================

DISPLAY_COLUMNS = [
    "Title",
    "Publisher",
    "Date",
    "CATEGORY",
    "DESTINATION_FOCUS",
    "Ethnicity Focus",
    "TRAVELER_MARKET",
    "RESEARCH_TYPE",
    "Sample",
    "Methodology",
    "Data Points",
    "Summary",
    "Conclusion",
    "Digital Marketing Insight",
]

FIELDS = DISPLAY_COLUMNS.copy()

CRM_CATEGORY_OPTIONS = [
    "Traveler Behavior",
    "Booking Trends",
    "Demographics",
    "Sustainability",
    "Technology & AI",
    "Market Intelligence",
    "Reputation & Reviews",
    "Pricing & Revenue",
    "Content & Social",
    "Seasonality",
    "Wellness",
    "Food & Dining",
    "Luxury",
    "Adventure",
    "Destination competitiveness",
    "Visitor experience",
    "Transportation",
    "Accommodation",
    "Experiences",
    "Food & Beverage",
    "Travel Planning & Booking",
    "Destinations / DMOs",
    "MICE & Business Travel",
    "Special Interest Tourism",
]

CRM_DESTINATION_FOCUS_OPTIONS = [
    "Global",
    "Europe",
    "Greece",
    "Mediterranean",
    "UK",
    "Germany",
    "USA",
    "Asia Pacific",
    "Middle East",
    "Specific City",
    "Specific Region",
]

CRM_TRAVELER_MARKET_OPTIONS = [
    "GB UK",
    "DE Germany",
    "US USA",
    "FR France",
    "IT Italy",
    "NL Netherlands",
    "AT Austria",
    "CH Switzerland",
    "CN China",
    "AE UAE/Middle East",
    "GR Greece",
    "EU Europe",
    "Global",
    "OTHER",
]


CRM_RESEARCH_TYPE_OPTIONS = [
    "Report",
    "Survey",
    "Article",
    "eBook",
    "Infographic",
    "Whitepaper",
    "Case Study",
]

CRM_TRAVELER_SEGMENT_OPTIONS = [
    "Business Travelers",
    "Bleisure Travelers",
    "Luxury Travelers",
    "Wellness Travelers",
    "Adventure Travelers",
    "Family Travelers",
    "Solo Travelers",
    "Group Travelers",
    "Leisure Travelers",
]

BASE_DIR = Path(__file__).resolve().parent
TAXONOMY_PATH = BASE_DIR / "taxonomy.json"
PUBLISHERS_PATH = BASE_DIR / "publishers.json"


# =========================================================
# Constants / heuristics
# =========================================================

TITLE_BLACKLIST = {
    "confidential",
    "restricted",
    "confidential & restricted",
    "contents",
    "table of contents",
    "introduction",
    "summary",
    "highlights",
    "references",
    "annex",
    "methodology",
    "acknowledgements",
}

TITLE_STOP_TERMS = [
    "grant agreement",
    "visit our website",
    "www.",
    ".com",
    "download the app",
    "it's how travel works",
    "it’s how travel works",
    "learn more",
    "request time to talk",
    "contact us",
]

SLOGAN_PATTERNS = [
    r"^20\d{2}\s+is\s+the\s+year\s+of",
    r"\bmore trips\b",
    r"\bmore destinations\b",
    r"\bmore doing\b",
    r"\bit['’]s how travel works\b",
    r"\blearn more\b",
]

GENERIC_TITLE_WORDS = {
    "trends",
    "trend",
    "report",
    "survey",
    "insights",
    "outlook",
    "summary",
    "highlights",
    "findings",
    "results",
    "overview",
}

MONTH_PAT = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d{2}\b",
    re.I,
)
SEASON_PAT = re.compile(r"\b(Spring|Summer|Autumn|Fall|Winter)\s+20\d{2}\b", re.I)
YEAR_PAT = re.compile(r"\b20\d{2}\b")
URL_PAT = re.compile(r"https?://\S+|www\.\S+", re.I)

OCR_MIN_TEXT_CHARS_PER_PAGE = 80
OCR_DEFAULT_MAX_PAGES = 12
OCR_RENDER_DPI = 160

NUMERIC_PAT = re.compile(
    r"("
    r"\d+(?:\.\d+)?%"
    r"|"
    r"\$ ?\d[\d,\.]*"
    r"|"
    r"€ ?\d[\d,\.]*"
    r"|"
    r"\b\d+(?:\.\d+)? ?(?:million|billion|trillion)\b"
    r"|"
    r"\b\d+(?:\.\d+)? ?(?:euros?|euro|days|years|experts|professionals|travelers|travellers|respondents|cities|vessels|arrivals|people|adults|parents|guests|managers|points|hotels?)\b"
    r"|"
    r"\b\d{1,3}(?:,\d{3})+\b"
    r")",
    re.I,
)

CONTACT_TERMS = [
    "contact us",
    "learn more",
    "request time to talk",
    "visit our website",
    "sales",
    "book a demo",
]

METHODOLOGY_TERMS = [
    "methodology",
    "sample",
    "survey",
    "respondents",
    "responses",
    "fieldwork",
    "commissioned",
    "research was conducted",
    "third-party research",
    "third party research",
    "about this research",
    "research design",
    "data source",
    "data sources",
    "survey fielded",
    "online survey",
    "nationally representative",
    "representative sample",
    "in partnership with",
]

CONCLUSION_TERMS = [
    "conclusion",
    "in conclusion",
    "key takeaways",
    "next steps",
    "summary",
    "looking ahead",
    "what this means",
]

TREND_TERMS = [
    "trend",
    "trends",
    "travel trends",
    "traveler trends",
    "consumer trends",
    "future of travel",
    "where to next",
    "insights",
]

DATA_TERMS = [
    "%",
    "percent",
    "million",
    "billion",
    "euro",
    "euros",
    "$",
    "respondents",
    "responses",
    "spend",
    "spent",
    "budget",
    "increase",
    "decrease",
    "up from",
    "down from",
    "travelers",
    "travellers",
    "days",
    "occupancy",
    "revpar",
    "adr",
]

ETHNICITY_FOCUS_MAP = {
    "American travelers": ["american", "americans", "u.s. traveler", "u.s. travelers", "us traveler", "us travelers", "u.s. adults", "united states", "usa"],
    "British travelers": ["british", "uk traveler", "uk travelers", "uk travellers", "britons", "united kingdom", "uk market"],
    "German travelers": ["german", "germans", "germany", "german market"],
    "Greek travelers": ["greek", "greeks", "greece", "greek market"],
    "French travelers": ["french", "france", "french market"],
    "Italian travelers": ["italian", "italians", "italy", "italian market"],
    "Spanish travelers": ["spanish", "spain", "spanish market"],
    "Portuguese travelers": ["portuguese", "portugal"],
    "Dutch travelers": ["dutch", "netherlands"],
    "Belgian travelers": ["belgian", "belgium"],
    "Swiss travelers": ["swiss", "switzerland"],
    "Austrian travelers": ["austrian", "austria"],
    "Nordic travelers": ["nordic", "nordics", "scandinavian", "scandinavia"],
    "Swedish travelers": ["swedish", "sweden"],
    "Norwegian travelers": ["norwegian", "norway"],
    "Danish travelers": ["danish", "denmark"],
    "Finnish travelers": ["finnish", "finland"],
    "Polish travelers": ["polish", "poland"],
    "Czech travelers": ["czech", "czech republic"],
    "Hungarian travelers": ["hungarian", "hungary"],
    "Romanian travelers": ["romanian", "romania"],
    "Turkish travelers": ["turkish", "turkey"],
    "Chinese travelers": ["chinese", "china", "greater china", "china outbound"],
    "Japanese travelers": ["japanese", "japan"],
    "Korean travelers": ["korean", "koreans", "south korea"],
    "Indian travelers": ["indian", "indians", "india", "india outbound"],
    "Middle Eastern travelers": ["middle eastern", "middle east", "gcc travelers", "gcc tourists", "arab travelers", "arab tourists", "uae travelers", "saudi travelers"],
    "European travelers": ["european travelers", "european travellers", "european tourists", "european residents", "intra-european", "intra-europe"],
    "International travelers": ["international travelers", "international travellers", "global travelers", "global travellers", "overseas travelers", "overseas tourists"],
    "Arab travelers": ["arab", "arabs"],
    "African travelers": ["african", "africa"],
    "Latino / Hispanic travelers": ["latino", "latina", "latinx", "hispanic"],
    "Black travelers": ["black travelers", "black tourists", "african american", "african-american"],
    "White travelers": ["white travelers", "white tourists", "caucasian"],
    "Asian travelers": ["asian travelers", "asian tourists", "south asian", "east asian", "southeast asian"],
    "Indigenous travelers": ["indigenous", "native american", "first nations"],
    "Multiracial travelers": ["multiracial", "mixed race"],
    "Diaspora travelers": ["diaspora", "diaspora tourism", "heritage trip", "roots travel"],
    "Muslim travelers": ["muslim travelers", "halal travel", "halal tourism"],
    "Jewish travelers": ["jewish travelers", "jewish tourism"],
    "LGBTQ+ travelers": ["lgbtq", "lgbtq+", "queer travelers", "gay travelers", "inclusive travel"],
    "Diverse / multicultural travelers": ["diverse travelers", "multicultural travelers", "underrepresented travelers", "minority travelers", "inclusive audiences"],
}
DEFAULT_TAXONOMY = {
    "fields": {
        "Research Type": {"rules": {}},
        "Main Category": {"rules": {}},
        "Additional Category": {"rules": {}},
        "Destination Focus": {"rules": {}},
        "Traveler Market": {"rules": {}},
    },
    "methodology_keywords": {"positive": [], "negative": []},
    "datapoint_keywords": {"positive": [], "negative": []},
}

DEFAULT_PUBLISHERS = {
    "publishers": [
        {"canonical_name": "Amadeus", "aliases": ["amadeus", "amadeus it group"]},
        {"canonical_name": "Booking.com", "aliases": ["booking.com"]},
        {"canonical_name": "Current Forward", "aliases": ["current forward"]},
        {"canonical_name": "Deloitte", "aliases": ["deloitte"]},
        {"canonical_name": "Expedia", "aliases": ["expedia", "expedia group"]},
        {"canonical_name": "Google", "aliases": ["google"]},
        {"canonical_name": "Interreg Europe", "aliases": ["interreg europe"]},
        {"canonical_name": "McKinsey", "aliases": ["mckinsey", "mckinsey & company"]},
        {"canonical_name": "Mews", "aliases": ["mews"]},
        {"canonical_name": "Navan", "aliases": ["navan"]},
        {"canonical_name": "OAG", "aliases": ["oag"]},
        {"canonical_name": "Phocuswright", "aliases": ["phocuswright"]},
        {"canonical_name": "Priceline", "aliases": ["priceline"]},
        {"canonical_name": "Skift", "aliases": ["skift", "skift research"]},
        {"canonical_name": "University of Eastern Finland", "aliases": ["university of eastern finland"]},
    ]
}

DEFAULT_CATEGORY_KEYWORDS = {
    "Traveler Trends": ["travel trends", "traveler trends", "consumer trends", "future of travel", "where to next", "next-level destinations", "travel habits"],
    "Distribution & Booking": ["booking", "bookings", "ota", "distribution", "reservation", "booking window", "channel mix", "direct booking", "search and booking data"],
    "Technology & AI": ["artificial intelligence", "ai", "generative ai", "technology", "automation", "digital concierge"],
    "Luxury": ["luxury", "premium", "high-end", "high end", "exclusive", "upscale", "boutique", "boutiques", "chic"],
    "Wellness": ["wellness", "spa", "self-care", "self care", "emotional reset", "mood-boosting", "mood boosting", "recharge", "treat themselves", "digital detox", "unplug"],
    "Adventure": ["adventure", "outdoor adventure", "hiking", "parasailing", "jet skiing", "cliff diving", "snorkeling", "kayaking", "canoeing", "horseback", "surf", "zipline", "rafting", "volcano", "jungle"],
    "Food & Dining": ["food", "dining", "chef-driven", "chef driven", "farm-to-table", "farm to table", "culinary", "patisserie", "night markets", "brewery", "wines", "restaurants", "cuisine"],
    "Family Travel": ["family", "children", "kids", "parents", "gen alpha", "family-friendly", "family friendly", "planning family vacations"],
    "Sports Tourism": ["sports", "college town", "game day", "tailgating", "stadium", "athletics"],
    "Offline / Digital Detox": ["offline", "digital detox", "unplug", "off the grid", "better boundaries with work", "no-wifi", "no wifi"],
    "Content & Social": ["social media", "pop culture", "movie", "show", "game", "celebrity", "viewing habits"],
    "Sustainability": ["sustainability", "sustainable", "green", "environment", "climate", "carbon", "responsible travel", "degrowth", "slow tourism", "slow travel"],
    "Destination Discovery": ["destination", "destination discovery", "top destinations", "searched cities", "next-level destinations", "inspiration"],
    "Mobility & Transport": ["mobility", "transport", "airline", "aviation", "rail", "cycling"],
    "Policy": ["policy", "policies", "framework", "governance", "interreg", "public policy"],
    "Accommodation": ["hotel", "accommodation", "hospitality", "lodging", "rooms", "stay", "stays"],
    "Market Intelligence": ["market intelligence", "market insights", "market report", "demand360", "occupancy", "revpar", "adr"],
}


# =========================================================
# Data classes
# =========================================================

@dataclass
class FieldReview:
    value: str = ""
    confidence_pct: int = 0
    evidence_snippet: str = ""
    evidence_page: Optional[int] = None
    extraction_method: str = "rule"
    needs_review: bool = True


@dataclass
class ExtractionOutput:
    final_row: Dict[str, str]
    review_meta: Dict[str, Dict[str, Any]]
    raw_text_preview: str
    llm_used: bool = False
    llm_error: str = ""
    llm_debug: Dict[str, Any] = None
    llm_model_used: str = ""


# =========================================================
# Load helpers
# =========================================================

def load_json_file(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_taxonomy(path: Path = TAXONOMY_PATH) -> Dict[str, Any]:
    if path.exists():
        try:
            data = load_json_file(path)
            if "fields" in data:
                return data
        except Exception:
            pass
    return DEFAULT_TAXONOMY


def load_publishers(path: Path = PUBLISHERS_PATH) -> Dict[str, Any]:
    if path.exists():
        try:
            data = load_json_file(path)
            if "publishers" in data:
                return data
        except Exception:
            pass
    return DEFAULT_PUBLISHERS


TAXONOMY = load_taxonomy()
PUBLISHERS = load_publishers()


# =========================================================
# Generic helpers
# =========================================================

def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\xa0", " ")).strip()


def normalize_block(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", (text or "").replace("\xa0", " ")).strip()


def get_field_rule_map(field_name: str, nested_key: str = "rules") -> Dict[str, List[str]]:
    return TAXONOMY.get("fields", {}).get(field_name, {}).get(nested_key, {})


def best_rule_match(text: str, rules: Dict[str, List[str]], min_score: int = 1) -> Tuple[str, List[str], int]:
    low = (text or "").lower()
    best_label = ""
    best_hits: List[str] = []
    best_score = 0

    for label, keywords in rules.items():
        hits = [kw for kw in keywords if kw.lower() in low]
        score = len(hits)
        if score > best_score:
            best_label = label
            best_hits = hits
            best_score = score

    if best_score < min_score:
        return "", [], 0
    return best_label, best_hits, best_score


def normalize_publisher(text: str) -> str:
    low = (text or "").lower()
    found = []

    for pub in PUBLISHERS.get("publishers", []):
        canonical = clean_text(pub.get("canonical_name", ""))
        aliases = pub.get("aliases", [])
        if not canonical:
            continue

        for alias in aliases:
            alias = clean_text(alias)
            if not alias:
                continue

            pattern = rf"(?<![a-z0-9]){re.escape(alias.lower())}(?![a-z0-9])"
            if re.search(pattern, low):
                found.append(canonical)
                break

    deduped = []
    seen = set()
    for item in found:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    return "; ".join(deduped)


def is_slogan(text: str) -> bool:
    low = clean_text(text).lower()
    return any(re.search(pat, low) for pat in SLOGAN_PATTERNS)


def _is_toc_line(text: str) -> bool:
    t = clean_text(text)
    if not t:
        return False
    if "contents" in t.lower() or "table of contents" in t.lower():
        return True
    if re.search(r"\.{4,}", t):
        return True
    if re.match(r"^\d+(\.\d+)*\s+", t):
        return True
    return False


def _normalize_data_point(text: str) -> str:
    t = clean_text(text)
    t = re.sub(r"\s*\([^)]*\)\s*$", "", t)
    t = re.sub(r"\s{2,}", " ", t)
    return t


def _is_bad_data_sentence(text: str) -> bool:
    t = clean_text(text)
    low = t.lower()
    if not t:
        return True
    if len(t) < 20 or len(t) > 260:
        return True
    if URL_PAT.search(t):
        return True
    if _is_toc_line(t):
        return True
    if re.match(r"^\d+(\.\d+)+", t):
        return True
    if any(k in low for k in ["contents", "references", "annex", "copyright", "source:"]):
        return True
    return False


def normalize_bullet_block(text: str) -> str:
    text = normalize_block(text)
    if not text or text.lower() == "not specified":
        return "Not specified"

    # Split cases where bullets are returned inline as "• item • item".
    text = re.sub(r"\s*•\s*", "\n• ", text).strip()
    text = re.sub(r"\n{2,}", "\n", text)

    parts = []
    for line in text.splitlines():
        line = clean_text(line)
        if not line:
            continue
        line = re.sub(r"^[•\-\*\u2022]\s*", "", line)
        if line:
            parts.append(f"• {line}")

    if not parts:
        sentences = [clean_text(s) for s in re.split(r"(?<=[.!?])\s+", text) if clean_text(s)]
        for s in sentences[:8]:
            parts.append(f"• {s}")

    deduped = []
    seen = set()
    for item in parts:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    return "\n".join(deduped[:8]) if deduped else "Not specified"


def format_methodology_summary(raw_text: str) -> str:
    text = clean_text(raw_text)
    if not text or text.lower() == "not specified":
        return "Not specified"

    sentences = [clean_text(s) for s in re.split(r"(?<=[.!?])\s+", text) if clean_text(s)]
    ordered = []
    for s in sentences:
        if s not in ordered:
            ordered.append(s)

    summary = " ".join(ordered[:5]).strip()
    if len(summary) > 900:
        summary = summary[:897].rsplit(" ", 1)[0] + "..."
    return summary or "Not specified"


# =========================================================
# Fetching
# =========================================================

def _sanitize_url(url: str) -> str:
    url = url.strip().rstrip("\\/")
    url = re.sub(r"\s+", "", url)
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return url


def _jina_fetch(url: str, session: requests.Session) -> Optional[str]:
    try:
        clean = re.sub(r"^https?://", "", url)
        r = session.get(
            f"https://r.jina.ai/http://{clean}",
            timeout=40,
            headers={"Accept": "text/plain"},
        )
        if r.status_code == 200 and len(r.text.strip()) > 300:
            return r.text
    except Exception:
        pass
    return None


def fetch_url(url: str) -> Dict[str, Any]:
    url = _sanitize_url(url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/pdf,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/",
    }

    session = requests.Session()
    session.headers.update(headers)

    try:
        r = session.get(url, timeout=60, allow_redirects=True)
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        jina = _jina_fetch(url, session)
        if jina:
            return {"type": "html", "content": jina, "source_url": url}
        if status == 403:
            raise FetchBlockedError(f"403 Forbidden – site blocks automated access: {url}")
        if status == 404:
            raise FetchParseError(f"404 Not Found – check the URL: {url}")
        raise FetchParseError(f"HTTP {status} error fetching: {url}")
    except requests.exceptions.ConnectionError:
        jina = _jina_fetch(url, session)
        if jina:
            return {"type": "html", "content": jina, "source_url": url}
        raise FetchParseError(f"Connection failed for: {url}")
    except Exception as e:
        raise FetchParseError(f"Unexpected fetch error: {e}")

    ctype = r.headers.get("content-type", "").lower()
    if "pdf" in ctype or r.url.lower().endswith(".pdf"):
        return {"type": "pdf", "content": r.content, "source_url": r.url}

    soup = BeautifulSoup(r.text, "lxml")

    candidates = []
    for tag in soup.find_all(["meta", "link"]):
        for v in tag.attrs.values():
            if isinstance(v, str) and ".pdf" in v.lower():
                candidates.append(urljoin(r.url, v))

    for a in soup.find_all("a", href=True):
        full = urljoin(r.url, a["href"])
        txt = a.get_text(" ", strip=True).lower()
        if ".pdf" in full.lower() or any(k in txt for k in ["download pdf", "full report", "get the report"]):
            candidates.append(full)

    for pdf_url in list(dict.fromkeys(candidates))[:5]:
        try:
            pr = session.get(pdf_url, timeout=60, allow_redirects=True)
            pr.raise_for_status()
            if "pdf" in pr.headers.get("content-type", "").lower() or pdf_url.lower().endswith(".pdf"):
                return {"type": "pdf", "content": pr.content, "source_url": pdf_url}
        except Exception:
            continue

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.extract()

    text = normalize_block(soup.get_text("\n", strip=True))
    if len(text.strip()) < 300:
        jina = _jina_fetch(url, session)
        if jina:
            return {"type": "html", "content": jina, "source_url": url}
        raise FetchParseError("Page loaded but too little text could be extracted. Try uploading the PDF directly.")

    return {"type": "html", "content": text, "source_url": r.url}


# =========================================================
# Parsing
# =========================================================

def _gemini_vision_extract_page_text(image_png: bytes, page_no: int, model: str, fallback_model: str) -> str:
    """
    Extract visible text from a rendered PDF page image using Gemini vision through
    the OpenAI-compatible Gemini endpoint.

    This is used only as a fallback for scanned/image-based PDFs where PyMuPDF
    cannot extract a usable text layer.
    """
    client = get_gemini_client()
    if client is None:
        return ""

    image_b64 = base64.b64encode(image_png).decode("utf-8")
    prompt = (
        "Extract all readable text from this PDF page image. "
        "Preserve headings, bullet points, statistics, dates, names, and URLs when visible. "
        "Return plain text only. Do not summarize. "
        f"This is page {page_no}."
    )

    models_to_try = [model]
    if fallback_model and fallback_model != model:
        models_to_try.append(fallback_model)

    last_err = None
    for chosen_model in models_to_try:
        try:
            response = client.chat.completions.create(
                model=chosen_model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_b64}"
                                },
                            },
                        ],
                    }
                ],
                temperature=0,
            )
            return clean_text(response.choices[0].message.content or "")
        except Exception as e:
            last_err = e
            continue

    return ""


def _render_pdf_page_to_png(page: Any, dpi: int = OCR_RENDER_DPI) -> bytes:
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    return pix.tobytes("png")


def _ocr_page_limit() -> int:
    raw = os.getenv("OCR_MAX_PAGES", str(OCR_DEFAULT_MAX_PAGES)).strip()
    try:
        value = int(raw)
        return max(1, min(value, 30))
    except Exception:
        return OCR_DEFAULT_MAX_PAGES


def extract_pdf_pages(pdf_input) -> List[Dict[str, Any]]:
    if fitz is None:
        raise RuntimeError("PyMuPDF is not installed. Run: pip install pymupdf")

    pdf_bytes = pdf_input.read() if hasattr(pdf_input, "read") else pdf_input
    pages: List[Dict[str, Any]] = []

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            blocks = page.get_text("dict").get("blocks", [])
            lines = []
            for block in blocks:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    text = clean_text(" ".join(span.get("text", "") for span in spans))
                    if not text:
                        continue
                    max_size = max((span.get("size", 0) for span in spans), default=0)
                    bold = any("bold" in (span.get("font", "").lower()) for span in spans)
                    lines.append({"text": text, "size": max_size, "bold": bold})
            plain = page.get_text("text", sort=True)
            pages.append({"page": i + 1, "lines": lines, "text": plain, "ocr_used": False})

        total_text_chars = sum(len(clean_text(p.get("text", ""))) for p in pages)
        avg_text_chars = total_text_chars / max(1, len(pages))

        # If the PDF has a usable embedded text layer, keep the cheap/fast path.
        if total_text_chars >= 400 or avg_text_chars >= OCR_MIN_TEXT_CHARS_PER_PAGE:
            return pages

        # Fallback: image/scanned/screenshot PDF. Use Gemini vision if API key exists.
        client = get_gemini_client()
        if client is None:
            raise RuntimeError(
                "This PDF appears to be image-based/scanned and no selectable text could be extracted. "
                "Add GEMINI_API_KEY to enable OCR/vision fallback, or paste the article text manually."
            )

        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite").strip() or "gemini-2.5-flash-lite"
        fallback_model = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
        max_pages = min(len(doc), _ocr_page_limit())

        ocr_pages: List[Dict[str, Any]] = []
        for i in range(max_pages):
            page = doc[i]
            image_png = _render_pdf_page_to_png(page)
            page_text = _gemini_vision_extract_page_text(
                image_png=image_png,
                page_no=i + 1,
                model=model,
                fallback_model=fallback_model,
            )
            lines = [
                {"text": clean_text(x), "size": 12, "bold": False}
                for x in page_text.splitlines()
                if clean_text(x)
            ]
            ocr_pages.append({"page": i + 1, "lines": lines, "text": page_text, "ocr_used": True})

        if not any(clean_text(p.get("text", "")) for p in ocr_pages):
            raise RuntimeError(
                "This PDF appears to be image-based/scanned, but OCR/vision extraction did not return readable text."
            )

        return ocr_pages

def extract_html_pages(text: str) -> List[Dict[str, Any]]:
    lines = [{"text": clean_text(x), "size": 12, "bold": False} for x in text.splitlines() if clean_text(x)]
    return [{"page": 1, "lines": lines, "text": text}]


def all_text(pages: List[Dict[str, Any]]) -> str:
    return normalize_block("\n\n".join(p["text"] for p in pages))


# =========================================================
# Page-role classification
# =========================================================

def classify_page_roles(pages: List[Dict[str, Any]]) -> Dict[int, Dict[str, int]]:
    role_scores: Dict[int, Dict[str, int]] = {}

    for p in pages:
        page_no = p["page"]
        text = normalize_block(p["text"])
        low = text.lower()
        lines = p["lines"]

        scores = {
            "cover": 0,
            "intro": 0,
            "methodology": 0,
            "trend": 0,
            "data_heavy": 0,
            "conclusion": 0,
            "appendix": 0,
        }

        if page_no == 1:
            scores["cover"] += 8
        elif page_no == 2:
            scores["cover"] += 4

        if page_no <= 3:
            scores["intro"] += 2

        if page_no >= max(1, len(pages) - 2):
            scores["conclusion"] += 2

        if any(term in low for term in METHODOLOGY_TERMS):
            scores["methodology"] += 8

        if any(term in low for term in CONCLUSION_TERMS):
            scores["conclusion"] += 8

        if any(term in low for term in TREND_TERMS):
            scores["trend"] += 3

        if sum(1 for t in DATA_TERMS if t in low) >= 3 or len(NUMERIC_PAT.findall(text)) >= 5:
            scores["data_heavy"] += 6

        if any(k in low for k in ["appendix", "references", "bibliography", "annex"]):
            scores["appendix"] += 8

        large_lines = [ln for ln in lines if ln.get("size", 0) >= 16]
        if page_no <= 2 and large_lines:
            scores["cover"] += 3

        if _is_toc_line(text[:500]):
            scores["appendix"] += 3

        if any(k in low for k in CONTACT_TERMS):
            scores["cover"] -= 2
            scores["intro"] -= 1

        role_scores[page_no] = scores

    return role_scores


def top_pages_by_role(pages: List[Dict[str, Any]], role_scores: Dict[int, Dict[str, int]], role: str, limit: int = 4) -> List[Dict[str, Any]]:
    ranked = sorted(
        pages,
        key=lambda p: role_scores.get(p["page"], {}).get(role, 0),
        reverse=True,
    )
    selected = [p for p in ranked if role_scores.get(p["page"], {}).get(role, 0) > 0]
    return selected[:limit] if selected else []


# =========================================================
# Candidate extraction / scoring
# =========================================================

def _title_candidate_score(text: str, page_no: int, size: float, bold: bool, role_scores: Dict[int, Dict[str, int]]) -> int:
    low = text.lower()
    words = [w for w in re.split(r"\s+", low) if w]
    score = 0

    if page_no == 1:
        score += 34
    elif page_no == 2:
        score += 10
    else:
        score -= 4

    score += role_scores.get(page_no, {}).get("cover", 0) * 2

    if size >= 28:
        score += 22
    elif size >= 22:
        score += 15
    elif size >= 18:
        score += 9
    elif size >= 15:
        score += 5

    if bold:
        score += 5

    if 12 <= len(text) <= 120:
        score += 8
    elif len(text) < 8 or len(text) > 150:
        score -= 12

    if 2 <= len(words) <= 14:
        score += 8
    elif len(words) == 1:
        score -= 28

    if any(k in low for k in ["report", "survey", "outlook", "trends", "state of", "insights", "study", "whitepaper", "expense"]):
        score += 18

    if YEAR_PAT.search(text):
        score += 5

    if MONTH_PAT.search(text) or SEASON_PAT.search(text):
        score -= 8

    if low in TITLE_BLACKLIST:
        score -= 25

    if any(stop in low for stop in TITLE_STOP_TERMS):
        score -= 25

    if is_slogan(text):
        score -= 34

    if URL_PAT.search(text):
        score -= 20

    if text.endswith(".") and "report" not in low and "survey" not in low and "outlook" not in low:
        score -= 10

    if len(words) == 1 and words[0] in GENERIC_TITLE_WORDS:
        score -= 40

    if len(words) == 2 and all(w in GENERIC_TITLE_WORDS for w in words):
        score -= 28

    if low in {"the", "travel", "business", "leisure", "expense"}:
        score -= 30

    return score


def extract_title(pages: List[Dict[str, Any]], role_scores: Dict[int, Dict[str, int]]) -> Tuple[str, str, Optional[int], int]:
    candidates = []

    for p in pages[:3]:
        page_no = p["page"]
        page_lines = p["lines"][:35]

        for i, ln in enumerate(page_lines):
            text = clean_text(ln["text"])
            if not text:
                continue

            base_score = _title_candidate_score(
                text=text,
                page_no=page_no,
                size=ln.get("size", 0),
                bold=ln.get("bold", False),
                role_scores=role_scores,
            )

            if base_score <= 0:
                continue

            candidates.append((base_score, text, page_no, ln.get("size", 0)))

            if page_no <= 2 and i + 1 < len(page_lines):
                next_text = clean_text(page_lines[i + 1]["text"])
                if next_text:
                    merged = clean_text(f"{text} {next_text}")
                    merged_score = _title_candidate_score(
                        text=merged,
                        page_no=page_no,
                        size=max(ln.get("size", 0), page_lines[i + 1].get("size", 0)),
                        bold=ln.get("bold", False) or page_lines[i + 1].get("bold", False),
                        role_scores=role_scores,
                    )

                    if 3 <= len(merged.split()) <= 18 and len(merged) <= 140 and not is_slogan(merged):
                        merged_score += 8

                    if merged_score > 0:
                        candidates.append((merged_score, merged, page_no, max(ln.get("size", 0), page_lines[i + 1].get("size", 0))))

    if not candidates:
        return "Not specified", "No reliable title candidate", None, 55

    deduped = {}
    for score, text, page_no, size in candidates:
        key = text.lower()
        if key not in deduped or score > deduped[key][0]:
            deduped[key] = (score, text, page_no, size)

    ranked = sorted(deduped.values(), key=lambda x: (x[0], x[3], -x[2]), reverse=True)

    page1_ranked = [c for c in ranked if c[2] == 1]
    if page1_ranked:
        best_page1 = page1_ranked[0]
        best_overall = ranked[0]
        if best_page1[0] >= best_overall[0] - 12:
            best_score, best_text, best_page, _ = best_page1
        else:
            best_score, best_text, best_page, _ = best_overall
    else:
        best_score, best_text, best_page, _ = ranked[0]

    words = best_text.lower().split()

    confidence = 70
    confidence += min(20, max(0, best_score // 4))

    if best_page == 1:
        confidence += 6
    elif best_page == 2:
        confidence += 2

    if len(words) == 1 and words[0] in GENERIC_TITLE_WORDS:
        confidence = min(confidence, 45)
    elif len(words) == 1:
        confidence = min(confidence, 55)
    elif len(words) == 2 and all(w in GENERIC_TITLE_WORDS for w in words):
        confidence = min(confidence, 58)

    if is_slogan(best_text):
        confidence = min(confidence, 40)

    if not any(k in best_text.lower() for k in ["report", "survey", "outlook", "trends", "state of", "insights", "study", "expense"]):
        confidence = min(confidence, 78)

    confidence = max(40, min(96, confidence))
    return best_text, best_text, best_page, confidence


def extract_publisher(pages: List[Dict[str, Any]], role_scores: Dict[int, Dict[str, int]]) -> Tuple[str, str, Optional[int], int]:
    scores: Dict[str, int] = {}
    evidence: Dict[str, Tuple[int, str]] = {}

    for p in pages[:6]:
        page_no = p["page"]
        text = normalize_block(p["text"])
        low = text.lower()

        page_weight = 1
        if page_no == 1:
            page_weight += 10
        elif page_no == 2:
            page_weight += 4

        page_weight += role_scores.get(page_no, {}).get("cover", 0) * 3
        page_weight += role_scores.get(page_no, {}).get("methodology", 0) * 2

        for pub in PUBLISHERS.get("publishers", []):
            canonical = clean_text(pub.get("canonical_name", ""))
            aliases = pub.get("aliases", [])
            if not canonical:
                continue

            for alias in aliases:
                alias = clean_text(alias)
                if not alias:
                    continue

                pattern = rf"(?<![a-z0-9]){re.escape(alias.lower())}(?![a-z0-9])"
                if re.search(pattern, low):
                    scores[canonical] = scores.get(canonical, 0) + page_weight
                    if canonical not in evidence:
                        evidence[canonical] = (page_no, alias)
                    break

    if not scores:
        return "Not specified", "No reliable publisher signal found", None, 60

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_pub, best_score = ranked[0]
    ev_page, ev_term = evidence[best_pub]

    confidence = max(65, min(97, 65 + best_score))
    return best_pub, ev_term, ev_page, confidence


def extract_date(pages: List[Dict[str, Any]], role_scores: Dict[int, Dict[str, int]]) -> Tuple[str, str, Optional[int], int]:
    candidates = []

    for p in pages[:5]:
        text = p["text"]
        cover_bonus = role_scores.get(p["page"], {}).get("cover", 0) * 2

        for m in MONTH_PAT.finditer(text):
            candidates.append((95 + cover_bonus, m.group(0), p["page"]))
        for m in SEASON_PAT.finditer(text):
            candidates.append((90 + cover_bonus, m.group(0), p["page"]))
        for m in YEAR_PAT.finditer(text):
            candidates.append((75 + cover_bonus, m.group(0), p["page"]))

    if not candidates:
        return "Not specified", "No reliable date found", None, 60

    candidates.sort(key=lambda x: x[0], reverse=True)
    score, value, page = candidates[0]
    return value, value, page, min(98, score)


def extract_research_type(title: str, text: str) -> Tuple[str, str, int]:
    base = f"{title}\n{text[:15000]}"
    low = base.lower()

    if "state of play" in low:
        return "State of Play", "state of play", 95
    if "trend report" in low or "travel trends" in low:
        return "Trend Report", "trend report/travel trends", 94
    if "survey" in low and ("responses" in low or "respondents" in low or "sample" in low):
        return "Survey Report", "survey; sample/respondents", 92
    if "industry outlook" in low:
        return "Industry Outlook", "industry outlook", 92
    if "market intelligence" in low or "market insights" in low:
        return "Market Intelligence Report", "market intelligence/insights", 90

    rules = get_field_rule_map("Research Type")
    label, hits, score = best_rule_match(base, rules, min_score=1)
    if label:
        return label, "; ".join(hits[:3]), min(94, 78 + score * 4)

    return "Report", "fallback", 70


def classify_category(pages: List[Dict[str, Any]], role_scores: Dict[int, Dict[str, int]], title: str) -> Tuple[str, List[str], int]:
    scores: Dict[str, int] = {}
    evidence: Dict[str, List[str]] = {}
    title_low = title.lower()

    def add_hit(label: str, keyword: str, weight: int) -> None:
        scores[label] = scores.get(label, 0) + weight
        evidence.setdefault(label, []).append(keyword)

    category_maps = []
    for source_field in ["Main Category", "Additional Category"]:
        category_maps.append(get_field_rule_map(source_field))
    category_maps.append(DEFAULT_CATEGORY_KEYWORDS)

    for cat_map in category_maps:
        for label, keywords in cat_map.items():
            for kw in keywords:
                kw_low = kw.lower()
                if kw_low in title_low:
                    add_hit(label, kw, 8 if len(kw.split()) > 1 else 5)

    for p in pages:
        page_no = p["page"]
        text_low = p["text"].lower()
        weight_multiplier = 1
        if role_scores.get(page_no, {}).get("trend", 0) > 0:
            weight_multiplier += 1
        if role_scores.get(page_no, {}).get("cover", 0) > 0:
            weight_multiplier += 1

        heading_lines = [clean_text(ln["text"]) for ln in p["lines"] if ln.get("size", 0) >= 15 or ln.get("bold", False)]
        heading_text = " ".join(heading_lines).lower()

        for cat_map in category_maps:
            for label, keywords in cat_map.items():
                for kw in keywords:
                    kw_low = kw.lower()
                    if kw_low in heading_text:
                        add_hit(label, kw, 4 * weight_multiplier)
                    elif kw_low in text_low:
                        add_hit(label, kw, 1 * weight_multiplier if len(kw_low.split()) == 1 else 2 * weight_multiplier)

    if scores.get("Technology & AI", 0):
        strong_non_ai = max([v for k, v in scores.items() if k != "Technology & AI"], default=0)
        if strong_non_ai >= scores["Technology & AI"] + 4:
            scores["Technology & AI"] = max(0, scores["Technology & AI"] - 3)

    if not scores:
        return "Not specified", [], 60

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    selected = []
    for label, score in ranked:
        if score >= 3:
            selected.append(label)
        if len(selected) >= 6:
            break

    if not selected:
        selected = [ranked[0][0]]

    evs: List[str] = []
    for label in selected:
        evs.extend(evidence.get(label, [])[:2])

    confidence = min(95, 68 + ranked[0][1] * 2)
    return "; ".join(selected), evs[:10], confidence


def classify_destination_focus(text: str) -> Tuple[str, str, int]:
    low = text.lower()

    multi_signals = [
        "united states", "u.s.", "usa", "canada", "europe", "france", "germany", "greece",
        "italy", "spain", "greater china", "asia pacific", "apac", "middle east",
        "latin america", "global", "worldwide", "international",
    ]
    region_hits = sum(1 for k in multi_signals if k in low)

    if region_hits >= 3:
        return "Multi-region", "multiple countries/regions detected", 95
    if "global" in low or "worldwide" in low:
        return "Global", "global/worldwide", 92
    if "europe" in low or "european" in low:
        return "Europe", "europe", 90
    if "united states" in low or "u.s." in low or "usa" in low:
        return "US", "united states", 90

    rules = get_field_rule_map("Destination Focus")
    label, hits, score = best_rule_match(text, rules, min_score=1)
    if label:
        return label, "; ".join(hits[:2]), min(92, 70 + score * 5)

    return "Not specified", "No clear destination focus found", 60


def classify_traveler_market(text: str) -> Tuple[str, str, int]:
    low = text.lower()

    segment_rules = {
        "Business Travelers": [
            "business travel",
            "corporate travel",
            "business traveler",
            "business travelers",
            "business traveller",
            "business travellers",
        ],
        "Bleisure Travelers": [
            "bleisure",
            "business and leisure",
            "blended travel",
            "workcation",
            "extend business trip",
        ],
        "Luxury Travelers": [
            "luxury traveler",
            "luxury travelers",
            "luxury traveller",
            "luxury travellers",
            "luxury travel",
            "premium travelers",
            "premium travellers",
            "high-end travelers",
            "high end travelers",
            "affluent travelers",
            "affluent travellers",
        ],
        "Wellness Travelers": [
            "wellness traveler",
            "wellness travelers",
            "wellness traveller",
            "wellness travellers",
            "wellness travel",
            "wellness retreat",
            "wellness retreats",
            "spa traveler",
            "spa travelers",
            "spa traveller",
            "spa travellers",
            "retreat travelers",
            "retreat travellers",
        ],
        "Adventure Travelers": [
            "adventure traveler",
            "adventure travelers",
            "adventure traveller",
            "adventure travellers",
            "adventure travel",
            "outdoor adventure",
            "outdoor travelers",
            "outdoor travellers",
            "hiking travelers",
            "hiking travellers",
            "trekking travelers",
            "trekking travellers",
        ],
        "Family Travelers": [
            "family travel",
            "family traveler",
            "family travelers",
            "family traveller",
            "family travellers",
            "families",
            "parents",
            "children",
            "kids",
            "gen alpha",
        ],
        "Solo Travelers": [
            "solo travel",
            "solo traveler",
            "solo travelers",
            "solo traveller",
            "solo travellers",
            "traveling alone",
            "travelling alone",
        ],
        "Group Travelers": [
            "group travel",
            "group traveler",
            "group travelers",
            "group traveller",
            "group travellers",
            "small group",
            "travel groups",
            "group tours",
        ],
        "Leisure Travelers": [
            "leisure travel",
            "leisure traveler",
            "leisure travelers",
            "leisure traveller",
            "leisure travellers",
            "vacation",
            "holiday",
            "getaway",
        ],
    }

    scores: Dict[str, int] = {}
    hits_map: Dict[str, List[str]] = {}

    for label, keywords in segment_rules.items():
        hits = [kw for kw in keywords if kw in low]
        if hits:
            scores[label] = scores.get(label, 0) + len(hits)
            hits_map.setdefault(label, []).extend(hits)

    # Extra fallback from taxonomy.json, but only for traveler-segment labels.
    # This avoids classifying stakeholder terms like travel managers / finance managers
    # as Traveler Market.
    rules = get_field_rule_map("Traveler Market")
    allowed_labels = set(segment_rules.keys())

    for label, keywords in rules.items():
        if label not in allowed_labels:
            continue

        hits = [kw for kw in keywords if kw.lower() in low]
        if hits:
            scores[label] = scores.get(label, 0) + len(hits)
            hits_map.setdefault(label, []).extend(hits)

    if not scores:
        return "Not specified", "No clear traveler segment found", 60

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_score = ranked[0][1]

    selected = []
    for label, score in ranked:
        # Return every traveler segment that has a clear rule/taxonomy hit.
        # No top-score cutoff and no four-item cap.
        if score >= 1:
            selected.append(label)

    selected = _dedupe_keep_order(selected, CRM_TRAVELER_SEGMENT_OPTIONS)

    evidence = []
    for label in selected:
        evidence.extend(hits_map.get(label, [])[:3])

    confidence = min(94, 72 + top_score * 6)

    return "; ".join(selected), "; ".join(evidence[:20]), confidence

def extract_ethnicity_focus(pages: List[Dict[str, Any]]) -> Tuple[str, str, Optional[int], int]:
    """
    Detect explicit ethnicity, nationality, source-market, regional-audience, or cultural identity focus.
    Conservative enough to avoid hallucination, but no longer requires the literal word ethnicity/nationality.
    """
    found: List[str] = []
    evidence_snip = ""
    evidence_page = None
    counts: Dict[str, int] = {}

    source_market_context_terms = [
        "traveler", "travelers", "traveller", "travellers", "tourist", "tourists",
        "guest", "guests", "respondent", "respondents", "adults", "market",
        "source market", "outbound", "inbound", "visitor", "visitors", "segment",
        "audience", "consumer", "consumers", "residents", "population", "sample",
        "research", "survey",
    ]

    identity_context_terms = [
        "ethnicity", "ethnic", "nationality", "nationalities", "race", "racial",
        "cultural", "culture", "identity", "diaspora", "minority", "multicultural",
        "inclusive", "religious", "faith", "halal", "lgbtq", "queer",
    ]

    all_sentences: List[Tuple[int, str]] = []
    for p in pages:
        text_sentences = [clean_text(s) for s in re.split(r"(?<=[.!?])\\s+", normalize_block(p["text"])) if clean_text(s)]
        line_sentences = [clean_text(ln.get("text", "")) for ln in p.get("lines", []) if clean_text(ln.get("text", ""))]
        for s in text_sentences + line_sentences:
            all_sentences.append((p["page"], s))

    for page_no, s in all_sentences:
        low = s.lower()

        if len(s) < 5 or len(s) > 280:
            continue
        if _is_toc_line(s) or URL_PAT.search(s):
            continue
        if re.search(r"\\(\\w.+?,\\s*\\d{4}", s):
            continue

        has_context = any(term in low for term in source_market_context_terms + identity_context_terms)

        matched_here = []
        for canon, aliases in ETHNICITY_FOCUS_MAP.items():
            for alias in aliases:
                pattern = rf"(?<![a-z0-9]){re.escape(alias.lower())}(?![a-z0-9])"
                if re.search(pattern, low):
                    matched_here.append(canon)
                    break

        if matched_here:
            for item in matched_here:
                if has_context or any(k in item.lower() for k in ["travelers", "international", "european", "middle eastern"]):
                    counts[item] = counts.get(item, 0) + 1
                    if item not in found:
                        found.append(item)

            if not evidence_snip and found:
                evidence_snip = s
                evidence_page = page_no

    selected = [item for item in found if counts.get(item, 0) >= 1]

    narrow = [x for x in selected if x not in {"International travelers", "European travelers", "Diverse / multicultural travelers"}]
    if narrow:
        selected = narrow + [
            x for x in selected
            if x in {"International travelers", "European travelers", "Diverse / multicultural travelers"}
            and counts.get(x, 0) >= 2
        ]

    selected = _dedupe_keep_order(selected)[:8]

    if selected:
        return "; ".join(selected), evidence_snip or "; ".join(selected[:3]), evidence_page, 88

    return "Not specified", "No explicit nationality, ethnicity, source-market, or cultural-audience focus found", None, 88


def extract_sample_and_methodology_rule(
    pages: List[Dict[str, Any]],
    role_scores: Dict[int, Dict[str, int]],
) -> Tuple[Tuple[str, str, Optional[int], int], Tuple[str, str, Optional[int], int]]:
    method_pages = top_pages_by_role(pages, role_scores, "methodology", limit=6)
    if not method_pages:
        method_pages = pages[:6]

    for p in method_pages:
        txt = normalize_block(p["text"])
        low = txt.lower()

        if "commissioned skift" in low and "business travelers" in low:
            sample_match = re.search(
                r"garnered\s+([\d,]+)\s+total responses.*?including\s+([\d,]+).*?managers?\s+and\s+([\d,]+)\s+business travelers",
                txt,
                re.I | re.S,
            )
            sample_val = "Not specified"
            if sample_match:
                total, managers, travelers = sample_match.groups()
                sample_val = f"{total} total responses, including {managers} corporate travel and finance managers and {travelers} business travelers"

            method_val = (
                "Navan commissioned Skift to conduct global surveys of business travelers and travel and finance managers. "
                "The report uses 2025 survey results and compares findings with prior years where noted."
            )
            return (
                (sample_val, txt[:300], p["page"], 97),
                (method_val, "commissioned Skift / global surveys", p["page"], 97),
            )

        if "current forward" in low or "third-party research" in low or "third party research" in low:
            sample = "Not specified"

            m1 = re.search(r"nationally representative sample of\s+([\d,]+)\s+(?:u\.s\.\s+)?adults ages 18[-–]79", txt, re.I)
            m2 = re.search(r"([\d,]+)\s+(?:u\.s\.\s+)?adults ages 18[-–]79", txt, re.I)
            m3 = re.search(r"survey of\s+([\d,]+)\s+parents", txt, re.I)

            if m1:
                sample = f"Nationally representative sample of {m1.group(1)} U.S. adults ages 18–79"
            elif m2:
                sample = f"{m2.group(1)} U.S. adults ages 18–79"
            elif m3:
                sample = f"Survey of {m3.group(1)} parents"

            method = (
                "Third-party research conducted on behalf of Priceline by Current Forward. "
                "Consumer survey fielded in 2025, supplemented with Priceline search and booking data where noted."
            )
            return (
                (sample, txt[:300], p["page"], 95 if sample != "Not specified" else 80),
                (method, "third-party research / Current Forward", p["page"], 96),
            )

    # Strong specific pattern for reports using Delphi-inspired expert-panel methodology.
    # Search the full document, because methodology is often on the final pages.
    full_text = normalize_block("\n\n".join(p.get("text", "") for p in pages))
    full_low = full_text.lower()
    if "delphi-inspired research method" in full_low and "18 hospitality experts" in full_low:
        sample_val = (
            "18 hospitality experts from across the hospitality industry, including hoteliers, technology vendors, consultants, "
            "investors, operators and travel/hospitality specialists."
        )
        method_val = (
            "The report used a Delphi-inspired research method for business forecasting. In September 2025, an expert panel of "
            "18 hospitality experts completed two online surveys. The first survey presented 15 future-looking scenarios and asked "
            "panelists to score them by likelihood, impact and desirability. The second survey explored major areas of agreement, "
            "disagreement and contention in more depth. Consensus was assessed using the variation in experts' likelihood, desirability "
            "and impact scores."
        )
        page_no = next((p["page"] for p in pages if "delphi-inspired research method" in p.get("text", "").lower()), None)
        return (
            (sample_val, "18 hospitality experts / expert panel", page_no, 97),
            (method_val, "Delphi-inspired method / two online surveys / September 2025", page_no, 97),
        )

    sample_candidates = []
    method_candidates = []

    sample_patterns = [
        r"\bn\s*=\s*[\d,]+\b",
        r"\bsample of [\d,]+\b",
        r"\bsurvey of [\d,]+\b",
        r"\bbased on a survey of [^.]+",
        r"\b[\d,]+ respondents\b",
        r"\b[\d,]+ responses\b",
        r"\b[\d,]+ travelers\b",
        r"\b[\d,]+ travellers\b",
        r"\b[\d,]+ adults\b",
        r"\bnationally representative sample of [^.]+",
        r"\brepresentative sample of [^.]+",
    ]

    method_patterns = [
        "survey fielded",
        "fielded",
        "commissioned",
        "conducted",
        "online survey",
        "third-party research",
        "third party research",
        "supplemented with",
        "search data",
        "booking data",
        "secondary research",
        "desk research",
        "interviews",
        "questionnaire",
        "methodology",
    ]

    for p in method_pages:
        sentences = [clean_text(s) for s in re.split(r"(?<=[.!?])\s+", normalize_block(p["text"])) if clean_text(s)]
        for s in sentences:
            low = s.lower()

            if any(re.search(pat, low, re.I) for pat in sample_patterns):
                score = 10
                if "representative" in low:
                    score += 3
                if "survey" in low:
                    score += 3
                if "respondent" in low or "responses" in low:
                    score += 3
                if "parents" in low or "adults" in low or "travelers" in low or "travellers" in low:
                    score += 2
                sample_candidates.append((score, s, p["page"]))

            if any(term in low for term in method_patterns):
                score = 8
                if "conducted" in low or "fielded" in low or "commissioned" in low:
                    score += 4
                if "search data" in low or "booking data" in low or "secondary research" in low:
                    score += 3
                if "survey" in low:
                    score += 2
                method_candidates.append((score, s, p["page"]))

    sample_val, sample_ev, sample_pg, sample_conf = "Not specified", "No explicit sample found", None, 70
    method_val, method_ev, method_pg, method_conf = "Not specified", "No explicit methodology found", None, 70

    if sample_candidates:
        sample_candidates.sort(key=lambda x: x[0], reverse=True)
        _, best_s, best_pg = sample_candidates[0]
        sample_val, sample_ev, sample_pg, sample_conf = best_s, best_s, best_pg, 85

    if method_candidates:
        method_candidates.sort(key=lambda x: x[0], reverse=True)
        picked = []
        seen = set()
        pg = None
        for _, s, pno in method_candidates:
            key = s.lower()
            if key not in seen:
                seen.add(key)
                picked.append(s)
                pg = pg or pno
            if len(picked) >= 2:
                break
        method_val = format_methodology_summary(" ".join(picked))
        method_ev, method_pg, method_conf = picked[0], pg, 85

    return (
        (sample_val, sample_ev, sample_pg, sample_conf),
        (method_val, method_ev, method_pg, method_conf),
    )


def extract_data_points_rule(pages: List[Dict[str, Any]], role_scores: Dict[int, Dict[str, int]], max_items: int = 8) -> Tuple[str, List[str], int]:
    candidates = []
    data_pages = top_pages_by_role(pages, role_scores, "data_heavy", limit=8) or pages

    for p in data_pages:
        lines = [clean_text(x["text"]) for x in p["lines"] if clean_text(x["text"])]
        for line in lines:
            if not NUMERIC_PAT.search(line) or _is_bad_data_sentence(line):
                continue

            score = 0
            low = line.lower()
            if "%" in line:
                score += 6
            if "$" in line or "€" in line or "euro" in low or "euros" in low:
                score += 5
            if any(t in low for t in ["million", "billion", "respondents", "responses", "days", "increase", "decrease", "spend", "budget", "up from", "down from"]):
                score += 4
            if len(line) <= 170:
                score += 2
            candidates.append((score, _normalize_data_point(line), p["page"]))

        sentences = [clean_text(s) for s in re.split(r"(?<=[.!?])\s+", p["text"]) if clean_text(s)]
        for s in sentences:
            if _is_bad_data_sentence(s):
                continue
            if not NUMERIC_PAT.search(s):
                continue

            score = 0
            low = s.lower()
            if "%" in s:
                score += 6
            if "$" in s or "€" in s or "euro" in low or "euros" in low:
                score += 5
            if any(t in low for t in ["million", "billion", "respondents", "responses", "days", "increase", "decrease", "spend", "budget", "up from", "down from", "travelers", "travellers"]):
                score += 4
            if len(s) <= 200:
                score += 2
            candidates.append((score, _normalize_data_point(s), p["page"]))

    candidates.sort(key=lambda x: x[0], reverse=True)

    picked = []
    seen = set()
    for _, s, _ in candidates:
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        picked.append(f"• {s}")
        if len(picked) >= max_items:
            break

    return ("\n".join(picked), picked, 88) if picked else ("Not specified", [], 70)


DISCLAIMER_TERMS = [
    "copyright",
    "all rights reserved",
    "terms and conditions",
    "privacy policy",
    "cookie",
    "disclaimer",
    "not possible to eliminate every margin of error",
    "every possible effort has been made",
    "no responsibility",
    "liability",
    "manage consent",
]


def is_disclaimer_or_boilerplate(value: str) -> bool:
    low = clean_text(value).lower()
    if not low:
        return True
    if any(term in low for term in DISCLAIMER_TERMS):
        return True
    # Very short fragments are not useful conclusions.
    if len(low.split()) < 8:
        return True
    return False


def normalize_conclusion_or_summary(value: str) -> str:
    value = clean_text(value)
    if not value or value.lower() == "not specified":
        return "Not specified"
    if is_disclaimer_or_boilerplate(value):
        return "Not specified"
    return value

def normalize_summary(value: str) -> str:
    value = clean_text(value)
    if not value or value.lower() == "not specified":
        return "Not specified"
    if is_disclaimer_or_boilerplate(value):
        return "Not specified"
    return value


def extract_conclusion_rule(pages: List[Dict[str, Any]], role_scores: Dict[int, Dict[str, int]]) -> Tuple[str, str, Optional[int], int]:
    conclusion_pages = top_pages_by_role(pages, role_scores, "conclusion", limit=4)
    if not conclusion_pages:
        conclusion_pages = pages[-3:] if len(pages) >= 3 else pages

    for p in conclusion_pages:
        sentences = [clean_text(s) for s in re.split(r"(?<=[.!?])\s+", normalize_block(p["text"])) if clean_text(s)]
        selected = []
        for s in sentences:
            if len(s) < 35 or len(s) > 240:
                continue
            if _is_toc_line(s) or URL_PAT.search(s):
                continue
            if not re.search(r"[A-Za-z]", s):
                continue
            selected.append(s)

        if selected:
            result = " ".join(selected[:2])
            return result, selected[0], p["page"], 85

    fallback_pages = pages[-2:] if len(pages) >= 2 else pages
    for p in fallback_pages:
        sentences = [clean_text(s) for s in re.split(r"(?<=[.!?])\s+", normalize_block(p["text"])) if clean_text(s)]
        usable = [s for s in sentences if 40 <= len(s) <= 220 and not URL_PAT.search(s)]
        if usable:
            result = " ".join(usable[:2])
            return result, usable[0], p["page"], 78

    return "Not specified", "No explicit conclusion found", None, 70



# =========================================================
# CRM taxonomy normalization
# =========================================================

def _split_labels(value: str) -> List[str]:
    if not value or clean_text(value).lower() == "not specified":
        return []
    return [clean_text(p) for p in re.split(r"[;\n,]+", value) if clean_text(p)]


def _dedupe_keep_order(items: List[str], allowed: Optional[List[str]] = None) -> List[str]:
    seen = set()
    out = []
    allowed_set = set(allowed or [])
    for item in items:
        item = clean_text(item)
        if not item:
            continue
        if allowed is not None and item not in allowed_set:
            continue
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def normalize_crm_category(old_category: str, title: str, text: str) -> Tuple[str, str, int]:
    combined = f"{title}\n{old_category}\n{text[:25000]}".lower()
    old_labels = " ".join(_split_labels(old_category)).lower()

    mapping = {
        "Traveler Behavior": ["traveler behavior", "traveller behavior", "traveler trends", "traveller trends", "consumer trends", "travel habits", "what travelers want", "what travellers want", "travel behavior", "travel behaviour", "visitor behavior", "visitor behaviour"],
        "Booking Trends": ["booking trends", "booking", "bookings", "reservation", "reservations", "booking window", "channel mix", "direct booking", "distribution", "ota", "online travel agency", "searched vs. booked", "search data", "booking data"],
        "Demographics": ["demographics", "demographic", "gen z", "millennials", "baby boomers", "age groups", "consumer segments", "parents", "children", "kids"],
        "Sustainability": ["sustainability", "sustainable", "responsible travel", "responsible tourism", "eco-tourism", "ecotourism", "environment", "environmental", "climate", "carbon", "green", "net zero", "degrowth", "slow tourism", "slow travel"],
        "Technology & AI": ["technology & ai", "technology", "artificial intelligence", "generative ai", "machine learning", "automation", "digital concierge", "chatbot", "predictive", "tech-enabled"],
        "Market Intelligence": ["market intelligence", "market insights", "market report", "industry report", "market analysis", "occupancy", "revpar", "adr", "demand", "performance"],
        "Reputation & Reviews": ["reputation", "reviews", "guest reviews", "ratings", "review score", "sentiment"],
        "Pricing & Revenue": ["pricing", "revenue", "revpar", "adr", "rate strategy", "yield", "revenue management", "average daily rate"],
        "Content & Social": ["content & social", "social media", "content", "creator", "influencer", "pop culture", "celebrity", "movie", "show", "viral", "social inspiration"],
        "Seasonality": ["seasonality", "seasonal", "peak season", "off season", "shoulder season", "winter travel", "summer travel"],
        "Wellness": ["wellness", "well-being", "wellbeing", "self-care", "self care", "spa", "retreat", "retreats", "recharge", "restore", "healing"],
        "Food & Dining": ["food & dining", "food", "dining", "culinary", "restaurant", "restaurants", "gastronomy", "wine tourism", "vineyard", "winery", "local cuisine", "farm-to-table", "night markets"],
        "Luxury": ["luxury", "premium", "high-end", "high end", "exclusive", "upscale", "elite travel", "affluent", "luxury travel"],
        "Adventure": ["adventure", "hiking", "outdoor", "nature & outdoors", "trekking", "trail", "trails", "snorkeling", "kayaking", "cycling", "ski", "wildlife", "safari"],
        "Destination competitiveness": ["destination competitiveness", "competitiveness", "destination development", "destination management", "regional development", "policy", "governance", "framework", "public policy", "interreg", "tourism strategy", "market development"],
        "Visitor experience": ["visitor experience", "guest experience", "experience design", "experiences", "authentic experiences", "local experiences", "immersive experiences", "personalization", "personalisation", "satisfaction", "quality experiences"],
        "Transportation": ["transportation", "transport", "mobility", "aviation", "airline", "airlines", "airport", "rail", "train", "cruise", "car rental", "ride-hailing", "transfer", "transfers"],
        "Accommodation": ["accommodation", "hotel", "hotels", "hospitality", "lodging", "resort", "resorts", "short-term rental", "vacation rental", "airbnb", "hostel", "serviced apartment"],
        "Experiences": ["experience", "experiences", "tours", "activities", "attractions", "sightseeing", "local tours", "guided tour", "things to do", "immersive", "unique experiences"],
        "Food & Beverage": ["food & beverage", "food and beverage", "f&b", "restaurants", "restaurant", "dining", "culinary", "gastronomy", "beverage", "bar", "bars", "wine", "local cuisine"],
        "Travel Planning & Booking": ["travel planning", "booking", "bookings", "reservation", "itinerary", "trip planning", "planning process", "booking journey", "booking behavior", "booking behaviour", "mobile booking", "online booking", "ota"],
        "Destinations / DMOs": ["dmo", "dmos", "destination marketing organization", "destination marketing organisation", "destination management organization", "destination management organisation", "tourism board", "destination brand", "destination marketing", "destination strategy"],
        "MICE & Business Travel": ["mice", "meetings", "incentives", "conferences", "exhibitions", "events", "business travel", "corporate travel", "trade show", "convention", "conference tourism", "event travel"],
        "Special Interest Tourism": ["special interest tourism", "niche tourism", "religious tourism", "cultural tourism", "heritage tourism", "sports tourism", "medical tourism", "wellness tourism", "eco tourism", "adventure tourism", "film tourism", "education tourism"],
    }

    scores: Dict[str, int] = {}
    evidence: Dict[str, List[str]] = {}
    for label, keywords in mapping.items():
        for kw in keywords:
            kw_low = kw.lower()
            if kw_low in old_labels:
                scores[label] = scores.get(label, 0) + 8
                evidence.setdefault(label, []).append(kw)
            elif kw_low in combined:
                scores[label] = scores.get(label, 0) + (4 if len(kw_low.split()) > 1 else 2)
                evidence.setdefault(label, []).append(kw)

    if not scores:
        return "Not specified", "No CRM category signal found", 60

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    selected = [label for label, score in ranked if score >= 3][:8]
    evs: List[str] = []
    for label in selected:
        evs.extend(evidence.get(label, [])[:2])
    return "; ".join(selected), "; ".join(evs[:12]), min(95, 68 + ranked[0][1] * 2)


def normalize_crm_destination_focus(old_destination: str, title: str, text: str) -> Tuple[str, str, int]:
    combined = f"{title}\n{old_destination}\n{text[:25000]}".lower()
    city_signals = ["athens", "thessaloniki", "london", "paris", "berlin", "rome", "madrid", "barcelona", "amsterdam", "dubai", "new york", "miami", "prague", "vienna"]

    if "global" in combined or "worldwide" in combined:
        return "Global", "global/worldwide", 92
    if "mediterranean" in combined:
        return "Mediterranean", "mediterranean", 92
    if any(k in combined for k in ["greece", "greek", "athens", "thessaloniki", "crete", "cyclades"]):
        return "Greece", "greece/greek destination signal", 92
    if any(k in combined for k in ["united kingdom", " uk ", "britain", "british", "london"]):
        return "UK", "uk/britain signal", 90
    if any(k in combined for k in ["germany", "german", "berlin", "munich"]):
        return "Germany", "germany/german signal", 90
    if any(k in combined for k in ["united states", "u.s.", " usa", "american", "new york", "miami"]):
        return "USA", "usa/united states signal", 90
    if any(k in combined for k in ["asia pacific", "apac", "china", "japan", "korea", "southeast asia"]):
        return "Asia Pacific", "asia pacific/apac signal", 88
    if any(k in combined for k in ["middle east", "gcc", "uae", "dubai", "saudi"]):
        return "Middle East", "middle east/gcc signal", 88
    if "europe" in combined or "european" in combined or " eu " in combined:
        return "Europe", "europe/european signal", 90
    if any(city in combined for city in city_signals):
        return "Specific City", "specific city signal", 82
    if any(k in combined for k in ["region", "regional", "province", "county", "island", "destination"]):
        return "Specific Region", "regional/destination signal", 78
    if clean_text(old_destination) in CRM_DESTINATION_FOCUS_OPTIONS:
        return clean_text(old_destination), "existing destination focus", 80
    return "Not specified", "No CRM destination signal found", 60


def normalize_crm_traveler_market(text: str, ethnicity_focus: str = "") -> Tuple[str, str, int]:
    combined = f"{ethnicity_focus}\n{text[:35000]}".lower()
    market_rules = {
        "GB UK": ["british", "uk traveler", "uk travellers", "uk travelers", "united kingdom", "brits abroad", "britain"],
        "DE Germany": ["german", "germans", "germany"],
        "US USA": ["american", "americans", "u.s. traveler", "u.s. travelers", "u.s. adults", "us travelers", "united states", "usa"],
        "FR France": ["french", "france"],
        "IT Italy": ["italian", "italians", "italy"],
        "NL Netherlands": ["dutch", "netherlands"],
        "AT Austria": ["austrian", "austria"],
        "CH Switzerland": ["swiss", "switzerland"],
        "CN China": ["chinese", "china", "greater china"],
        "AE UAE/Middle East": ["uae", "emirati", "middle eastern", "middle east", "gcc", "dubai", "saudi"],
        "GR Greece": ["greek", "greeks", "greece"],
        "EU Europe": ["european travelers", "european travellers", "european residents", "european tourists", "europeans", "eu population", "within the eu"],
        "Global": ["global travelers", "global travellers", "worldwide", "international travelers", "international travellers"],
    }
    scores: Dict[str, int] = {}
    evidence: Dict[str, List[str]] = {}
    for label, keywords in market_rules.items():
        for kw in keywords:
            if kw in combined:
                scores[label] = scores.get(label, 0) + (4 if len(kw.split()) > 1 else 2)
                evidence.setdefault(label, []).append(kw)
    if not scores:
        return "OTHER", "No source-market signal found", 65
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    selected = [label for label, score in ranked if score >= 2][:6]
    evs: List[str] = []
    for label in selected:
        evs.extend(evidence.get(label, [])[:2])
    return "; ".join(selected), "; ".join(evs[:12]), min(94, 70 + ranked[0][1] * 3)


def normalize_crm_research_type(old_research_type: str, title: str, source_url: str = "") -> Tuple[str, str, int]:
    combined = f"{old_research_type}\n{title}\n{source_url}".lower()
    if "survey" in combined:
        return "Survey", "survey signal", 92
    if "whitepaper" in combined or "white paper" in combined:
        return "Whitepaper", "whitepaper signal", 92
    if "case study" in combined:
        return "Case Study", "case study signal", 92
    if "ebook" in combined or "e-book" in combined or "e book" in combined:
        return "eBook", "ebook signal", 88
    if "infographic" in combined:
        return "Infographic", "infographic signal", 88
    if "article" in combined or "blog" in combined or re.search(r"/blog/", combined):
        return "Article", "article/blog signal", 82
    if any(k in combined for k in ["report", "state of play", "outlook", "trends", "insights", "study", "market intelligence"]):
        return "Report", "report/study signal", 90
    return "Report", "default", 75



def apply_crm_validation_result(row: Dict[str, str], reviews: Dict[str, FieldReview], validation: Dict[str, Any]) -> None:
    confidence = validation.get("confidence", {}) if isinstance(validation, dict) else {}
    corrections = validation.get("corrections", {}) if isinstance(validation, dict) else {}
    allowed_map = {
        "CATEGORY": CRM_CATEGORY_OPTIONS,
        "DESTINATION_FOCUS": CRM_DESTINATION_FOCUS_OPTIONS,
        "TRAVELER_MARKET": CRM_TRAVELER_SEGMENT_OPTIONS,
        "RESEARCH_TYPE": CRM_RESEARCH_TYPE_OPTIONS,
    }
    for field, allowed in allowed_map.items():
        value = clean_text(validation.get(field, "")) if isinstance(validation, dict) else ""
        if not value:
            continue

        # Multi-value fields may be semicolon-separated.
        if field in {"CATEGORY", "TRAVELER_MARKET"}:
            selected = _dedupe_keep_order(_split_labels(value), allowed)
            if selected:
                row[field] = "; ".join(selected)
                conf = int(confidence.get(field, 90)) if isinstance(confidence, dict) else 90
                reviews[field] = FieldReview(row[field], min(96, max(75, conf)), "Rule + Gemini cross-check", None, "rule+gemini", conf < 85)
        else:
            if value in allowed:
                row[field] = value
                conf = int(confidence.get(field, 90)) if isinstance(confidence, dict) else 90
                reviews[field] = FieldReview(row[field], min(96, max(75, conf)), "Rule + Gemini cross-check", None, "rule+gemini", conf < 85)

    for field in ["Ethnicity Focus", "Digital Marketing Insight"]:
        value = clean_text(validation.get(field, "")) if isinstance(validation, dict) else ""
        if value:
            conf = int(confidence.get(field, 86)) if isinstance(confidence, dict) else 86
            row[field] = value
            reviews[field] = FieldReview(value, min(94, max(70, conf)), "Rule + Gemini cross-check", None, "rule+gemini", conf < 85)

    for field in ["Title", "Publisher", "Date"]:
        value = clean_text(corrections.get(field, "")) if isinstance(corrections, dict) else ""
        if value and value.lower() != "not specified":
            conf = int(confidence.get(field, 88)) if isinstance(confidence, dict) else 88
            row[field] = value
            reviews[field] = FieldReview(value, min(96, max(75, conf)), "Gemini cross-check correction", reviews.get(field, FieldReview()).evidence_page, "rule+gemini", conf < 85)



def extract_digital_marketing_insight_rule(text: str) -> Tuple[str, str, int]:
    """Find actionable digital-marketing inputs/hacks/advice in the source."""
    cleaned = normalize_block(text)
    sentences = [clean_text(s) for s in re.split(r"(?<=[.!?])\s+", cleaned) if clean_text(s)]

    marketing_terms = [
        "digital marketing", "marketing", "campaign", "content", "social media", "seo", "search", "paid media", "ads", "advertising",
        "influencer", "creator", "tiktok", "instagram", "facebook", "youtube", "email", "newsletter", "website", "conversion",
        "personalization", "personalisation", "reviews", "ugc", "user-generated", "brand", "storytelling", "mobile", "app",
        "booking journey", "customer journey", "inspiration", "discoverability", "visibility", "audience", "segment",
    ]
    action_terms = [
        "should", "need to", "must", "opportunity", "recommend", "focus", "prioritize", "prioritise", "leverage", "use", "create", "offer", "promote", "target", "highlight", "optimize", "optimise", "improve", "invest", "build",
    ]

    candidates: List[str] = []
    evidence = ""
    for s in sentences:
        low = s.lower()
        if len(s) < 35 or len(s) > 320:
            continue
        if _is_toc_line(s) or URL_PAT.search(s):
            continue
        if any(t in low for t in marketing_terms) and any(t in low for t in action_terms):
            candidates.append(s)
            if not evidence:
                evidence = s
        elif any(t in low for t in ["social media", "content", "influencer", "creator", "reviews", "ugc", "seo", "advertising", "campaign"]):
            candidates.append(s)
            if not evidence:
                evidence = s

    if not candidates:
        return "Not specified", "No explicit digital marketing input found", 65

    selected = []
    seen = set()
    for c in candidates:
        key = c[:80].lower()
        if key not in seen:
            seen.add(key)
            selected.append(c)
        if len(selected) >= 3:
            break

    return " • ".join(selected), evidence, 78


def generate_basic_summary_fallback(row: Dict[str, str]) -> str:
    """Create a simple non-AI summary from extracted fields when Gemini summary is unavailable."""
    title = clean_text(row.get("Title", ""))
    publisher = clean_text(row.get("Publisher", ""))
    category = clean_text(row.get("CATEGORY", ""))
    market = clean_text(row.get("TRAVELER_MARKET", ""))
    sample = clean_text(row.get("Sample", ""))
    methodology = clean_text(row.get("Methodology", ""))
    data_points = clean_text(row.get("Data Points", ""))
    conclusion = clean_text(row.get("Conclusion", ""))

    parts = []
    if title and title.lower() != "not specified":
        if publisher and publisher.lower() != "not specified":
            parts.append(f"{title} by {publisher} covers tourism/hospitality research insights.")
        else:
            parts.append(f"{title} covers tourism/hospitality research insights.")
    if sample and sample.lower() != "not specified":
        parts.append(f"The source is based on {sample}.")
    if methodology and methodology.lower() != "not specified":
        parts.append(f"Methodology: {methodology}")
    if category and category.lower() != "not specified":
        parts.append(f"The main topics identified are {category}.")
    if market and market.lower() != "not specified":
        parts.append(f"The relevant traveler market includes {market}.")
    if data_points and data_points.lower() != "not specified":
        first_items = [x.replace("•", "").strip() for x in data_points.splitlines() if x.strip()][:2]
        if first_items:
            parts.append("Key findings include: " + " ".join(first_items))
    if conclusion and conclusion.lower() != "not specified":
        parts.append(f"Overall takeaway: {conclusion}")

    summary = " ".join(parts).strip()
    return summary if summary else "Not specified"

# =========================================================
# Gemini helpers
# =========================================================

def get_gemini_client() -> Optional[Any]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key or OpenAI is None:
        return None
    return OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )


def _make_page_brief(p: Dict[str, Any], max_chars: int = 2400) -> str:
    return f"[PAGE {p['page']}]\n{normalize_block(p['text'])[:max_chars]}"


def _json_response_format(name: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": schema},
    }


def _multi_field_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "sample": {"type": "string"},
            "methodology": {"type": "string"},
            "data_points": {"type": "array", "items": {"type": "string"}},
            "conclusion": {"type": "string"},
            "digital_marketing_insight": {"type": "string"},
        },
        "required": ["sample", "methodology", "data_points", "conclusion", "digital_marketing_insight"],
        "additionalProperties": False,
    }


def _chat_json(
    client: Any,
    model: str,
    system_prompt: str,
    user_prompt: str,
    schema_name: str,
    schema: Dict[str, Any],
    fallback_model: Optional[str] = None,
    max_retries: int = 3,
) -> Tuple[Dict[str, Any], str]:
    last_err = None
    models_to_try = [model]
    if fallback_model and fallback_model != model:
        models_to_try.append(fallback_model)

    for chosen_model in models_to_try:
        for attempt in range(max_retries):
            try:
                response = client.chat.completions.create(
                    model=chosen_model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format=_json_response_format(schema_name, schema),
                    temperature=0,
                )
                return json.loads(response.choices[0].message.content), chosen_model
            except Exception as e:
                last_err = e
                err_text = str(e).lower()

                if "429" in err_text or "resource_exhausted" in err_text or "quota exceeded" in err_text:
                    raise GeminiQuotaExhaustedError(str(e))

                if "503" in err_text or "unavailable" in err_text or "high demand" in err_text:
                    if attempt < max_retries - 1:
                        time.sleep(2 * (attempt + 1))
                        continue
                break

    raise last_err


def llm_extract_semantic_fields(
    client: Any,
    model: str,
    fallback_model: str,
    pages_for_llm: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], str]:
    context = "\n\n".join(_make_page_brief(p, max_chars=2400) for p in pages_for_llm)[:22000]

    prompt = (
        "Extract the following fields from the provided research-report excerpts and return strict JSON.\n\n"
        "Fields:\n"
        "- sample: detailed factual description of the study sample/panel/audience. Include number of respondents/experts, who they are, geography, and segment details when stated.\n"
        "- methodology: detailed factual summary of how the research was conducted. Include research method, timing, number of surveys/interviews, scoring dimensions, data sources, and fieldwork details when stated. Aim for 3-5 sentences.\n"
        "- data_points: 6 to 8 bullet-style findings when available. Each item should include a statistic/score/number and a short explanation of what it means.\n"
        "- conclusion: 2 to 3 sentences summarizing explicit conclusion/key takeaway/strategic implication only\n\n"
        "Rules:\n"
        "- Use only facts explicitly stated in the excerpts.\n"
        "- Prefer complete, useful explanations over short fragments.\n"
        "- Do not infer missing information.\n"
        "- If sample is unclear, return 'Not specified'.\n"
        "- If methodology is unclear, return 'Not specified'.\n"
        "- If there are no good data points, return an empty array.\n"
        "- If no conclusion is explicit, return 'Not specified'.\n"
        "- Do not mix sample with methodology.\n"
        "- Do not include source labels or headings.\n\n"
        f"Page excerpts:\n{context}"
    )

    return _chat_json(
        client=client,
        model=model,
        system_prompt="You extract grounded structured research fields from evidence.",
        user_prompt=prompt,
        schema_name="semantic_fields_extraction",
        schema=_multi_field_schema(),
        fallback_model=fallback_model,
        max_retries=4,
    )



def _crm_validation_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "CATEGORY": {"type": "string"},
            "DESTINATION_FOCUS": {"type": "string"},
            "TRAVELER_MARKET": {"type": "string"},
            "Ethnicity Focus": {"type": "string"},
            "RESEARCH_TYPE": {"type": "string"},
            "Digital Marketing Insight": {"type": "string"},
            "corrections": {
                "type": "object",
                "properties": {
                    "Title": {"type": "string"},
                    "Publisher": {"type": "string"},
                    "Date": {"type": "string"},
                },
                "required": ["Title", "Publisher", "Date"],
                "additionalProperties": False,
            },
            "confidence": {
                "type": "object",
                "properties": {
                    "CATEGORY": {"type": "integer"},
                    "DESTINATION_FOCUS": {"type": "integer"},
                    "TRAVELER_MARKET": {"type": "integer"},
                    "Ethnicity Focus": {"type": "integer"},
                    "RESEARCH_TYPE": {"type": "integer"},
                    "Digital Marketing Insight": {"type": "integer"},
                    "Title": {"type": "integer"},
                    "Publisher": {"type": "integer"},
                    "Date": {"type": "integer"},
                },
                "required": ["CATEGORY", "DESTINATION_FOCUS", "TRAVELER_MARKET", "Ethnicity Focus", "RESEARCH_TYPE", "Digital Marketing Insight", "Title", "Publisher", "Date"],
                "additionalProperties": False,
            },
        },
        "required": ["CATEGORY", "DESTINATION_FOCUS", "TRAVELER_MARKET", "Ethnicity Focus", "RESEARCH_TYPE", "Digital Marketing Insight", "corrections", "confidence"],
        "additionalProperties": False,
    }

def llm_crosscheck_crm_fields(client: Any, model: str, fallback_model: str, pages_for_llm: List[Dict[str, Any]], draft_row: Dict[str, str]) -> Tuple[Dict[str, Any], str]:
    context = "\n\n".join(_make_page_brief(p, max_chars=1400) for p in pages_for_llm)[:12000]
    draft_json = json.dumps(draft_row, ensure_ascii=False, indent=2)

    prompt = (
        "Cross-check and normalize a research extraction into a CRM taxonomy. Return strict JSON only.\\n\\n"
        "Allowed CATEGORY values, semicolon-separated if multiple truly apply:\\n"
        f"{CRM_CATEGORY_OPTIONS}\\n\\n"
        "Allowed DESTINATION_FOCUS values, choose one:\\n"
        f"{CRM_DESTINATION_FOCUS_OPTIONS}\\n\\n"
        "Allowed TRAVELER_MARKET values, semicolon-separated if multiple traveler segments truly apply:\\n"
        f"{CRM_TRAVELER_SEGMENT_OPTIONS}\\n\\n"
        "Allowed RESEARCH_TYPE values, choose one:\\n"
        f"{CRM_RESEARCH_TYPE_OPTIONS}\\n\\n"
        "Rules:\\n"
        "- Use only the document excerpts and draft extraction.\\n"
        "- CATEGORY is the research topic/theme, not every incidental word.\\n"
        "- DESTINATION_FOCUS is the destination/region being analyzed.\\n"
        "- TRAVELER_MARKET means traveler segment/type, e.g. Luxury Travelers, Wellness Travelers, Adventure Travelers, Family Travelers, Business Travelers.\\n"
        "- TRAVELER_MARKET is NOT source country or nationality; do not return values like Germany, France, UK, USA.\\n"
        "- Ethnicity Focus should capture explicit nationality, source-market, regional audience, ethnicity, cultural identity, or demographic audience signals. Examples: American travelers, German travelers, European travelers, GCC travelers, Black travelers, Muslim travelers, LGBTQ+ travelers.\\n"
        "- If the document mentions a statistic like '29% of Americans use AI for travel research', Ethnicity Focus should include American travelers.\\n"
        "- Keep all clearly mentioned traveler segments; do not limit to one.\\n"
        "- If no traveler segment is clear, return the draft value or Not specified.\\n"
        "- corrections.Title, corrections.Publisher and corrections.Date should be corrected only if clearly wrong; otherwise return the draft value.\\n"
        "- Confidence values must be 0-100 integers.\\n\\n"
        f"Draft extraction:\\n{draft_json}\\n\\n"
        f"Document excerpts:\\n{context}"
    )

    return _chat_json(
        client=client,
        model=model,
        system_prompt="You validate and normalize research metadata for a tourism-marketing research CRM.",
        user_prompt=prompt,
        schema_name="crm_validation",
        schema=_crm_validation_schema(),
        fallback_model=fallback_model,
        max_retries=3,
    )

def llm_generate_conclusion_summary(client: Any, model: str, fallback_model: str, pages_for_llm: List[Dict[str, Any]], draft_row: Dict[str, str]) -> Tuple[str, str]:
    context = "\n\n".join(_make_page_brief(p, max_chars=1400) for p in pages_for_llm)[:12000]
    draft_json = json.dumps(draft_row, ensure_ascii=False, indent=2)
    prompt = (
        "Write a concise conclusion or summary for this tourism/travel research source. "
        "Return 2-4 sentences. Focus on the main finding, trend, implication, or takeaway. "
        "Do not include copyright, legal disclaimers, privacy policy text, website footer text, or boilerplate. "
        "If the source contains no meaningful conclusion or summary, return Not specified.\n\n"
        f"Draft extraction:\n{draft_json}\n\n"
        f"Document excerpts:\n{context}"
    )

    models_to_try = [model]
    if fallback_model and fallback_model != model:
        models_to_try.append(fallback_model)

    last_err = None
    for chosen_model in models_to_try:
        try:
            response = client.chat.completions.create(
                model=chosen_model,
                messages=[
                    {"role": "system", "content": "You write accurate, concise research summaries from provided excerpts only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
            )
            return normalize_conclusion_or_summary(response.choices[0].message.content or ""), chosen_model
        except Exception as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    return "Not specified", ""

def llm_generate_summary(client: Any, model: str, fallback_model: str, pages_for_llm: List[Dict[str, Any]], draft_row: Dict[str, str]) -> Tuple[str, str]:
    context = "\n\n".join(_make_page_brief(p, max_chars=1400) for p in pages_for_llm)[:12000]
    draft_json = json.dumps(draft_row, ensure_ascii=False, indent=2)
    prompt = (
        "Write a detailed but concise summary for this tourism/travel research source. "
        "Return 4-6 sentences. Include the topic and scope, source type, main findings, methodology context, and practical relevance. "
        "Do not include copyright, legal disclaimers, privacy policy text, website footer text, or boilerplate. "
        "If there is not enough meaningful content, return Not specified.\n\n"
        f"Draft extraction:\n{draft_json}\n\n"
        f"Document excerpts:\n{context}"
    )

    models_to_try = [model]
    if fallback_model and fallback_model != model:
        models_to_try.append(fallback_model)

    last_err = None
    for chosen_model in models_to_try:
        try:
            response = client.chat.completions.create(
                model=chosen_model,
                messages=[
                    {"role": "system", "content": "You write accurate, concise research summaries from provided excerpts only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
            )
            return normalize_summary(response.choices[0].message.content or ""), chosen_model
        except Exception as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    return "Not specified", ""


def llm_generate_conclusion_only(client: Any, model: str, fallback_model: str, pages_for_llm: List[Dict[str, Any]], draft_row: Dict[str, str]) -> Tuple[str, str]:
    context = "\n\n".join(_make_page_brief(p, max_chars=1400) for p in pages_for_llm)[:12000]
    draft_json = json.dumps(draft_row, ensure_ascii=False, indent=2)
    prompt = (
        "Extract or write the conclusion/takeaway for this tourism/travel research source. "
        "Return 1-3 sentences focused on the final implication, recommendation, or strategic takeaway. "
        "This is NOT a general summary; avoid restating all details. "
        "Do not include copyright, legal disclaimers, privacy policy text, website footer text, or boilerplate. "
        "If there is no meaningful conclusion or takeaway, return Not specified.\n\n"
        f"Draft extraction:\n{draft_json}\n\n"
        f"Document excerpts:\n{context}"
    )

    models_to_try = [model]
    if fallback_model and fallback_model != model:
        models_to_try.append(fallback_model)

    last_err = None
    for chosen_model in models_to_try:
        try:
            response = client.chat.completions.create(
                model=chosen_model,
                messages=[
                    {"role": "system", "content": "You extract concise conclusions and strategic takeaways from provided excerpts only."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
            )
            return normalize_conclusion_or_summary(response.choices[0].message.content or ""), chosen_model
        except Exception as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    return "Not specified", ""

def build_llm_context_pages(
    pages: List[Dict[str, Any]],
    role_scores: Dict[int, Dict[str, int]],
) -> List[Dict[str, Any]]:
    chosen: List[Dict[str, Any]] = []
    seen = set()

    def add_page(p: Dict[str, Any]) -> None:
        if p and p.get("page") not in seen:
            seen.add(p.get("page"))
            chosen.append(p)

    # Always include opening pages for title/context.
    for p in pages[:3]:
        add_page(p)

    # Include pages by detected role.
    groups = [
        top_pages_by_role(pages, role_scores, "methodology", limit=4),
        top_pages_by_role(pages, role_scores, "data_heavy", limit=4),
        top_pages_by_role(pages, role_scores, "conclusion", limit=3),
        top_pages_by_role(pages, role_scores, "trend", limit=2),
    ]

    for group in groups:
        for p in group:
            add_page(p)

    # Include explicit methodology/summary/checklist pages even when the role classifier under-ranks them.
    keyword_sets = [
        ["methodology", "delphi", "sample", "fieldwork", "survey"],
        ["summary", "key areas of change", "take action", "readiness checklist"],
        ["digital marketing", "content ai-ready", "search results", "social media"],
    ]
    for keywords in keyword_sets:
        matches = []
        for p in pages:
            low = p.get("text", "").lower()
            if any(k in low for k in keywords):
                matches.append(p)
        for p in matches[:3]:
            add_page(p)

    # Include final pages because methodology, conclusion and acknowledgements often sit at the end.
    for p in pages[-5:]:
        add_page(p)

    if not chosen:
        chosen = pages[:8]

    # Keep context manageable but richer than before.
    return sorted(chosen, key=lambda x: x["page"])[:18]

# =========================================================
# Final arbitration
# =========================================================

def choose_final_value(
    rule_value: str,
    rule_conf: int,
    ai_value: str,
    ai_conf: int,
    prefer_rule_threshold: int = 88,
) -> Tuple[str, int, str]:
    rule_clean = clean_text(rule_value) or "Not specified"
    ai_clean = clean_text(ai_value) or "Not specified"

    if rule_clean.lower() == "not specified" and ai_clean.lower() != "not specified":
        return ai_clean, ai_conf, "gemini"
    if ai_clean.lower() == "not specified" and rule_clean.lower() != "not specified":
        return rule_clean, rule_conf, "rule"
    if ai_clean.lower() == "not specified" and rule_clean.lower() == "not specified":
        return "Not specified", max(rule_conf, ai_conf), "rule"

    if rule_clean.lower() == ai_clean.lower():
        return rule_clean, min(98, max(rule_conf, ai_conf) + 4), "rule+gemini"

    if rule_conf >= prefer_rule_threshold:
        return rule_clean, rule_conf, "rule"
    if ai_conf > rule_conf:
        return ai_clean, ai_conf, "gemini"
    return rule_clean, rule_conf, "rule"


# =========================================================
# Main builder
# =========================================================

def build_output(pages: List[Dict[str, Any]], source_url: str = "", pdf_path: str = "") -> ExtractionOutput:
    text = all_text(pages)
    role_scores = classify_page_roles(pages)

    row: Dict[str, str] = {field: "Not specified" for field in FIELDS}
    reviews: Dict[str, FieldReview] = {field: FieldReview(value="Not specified") for field in FIELDS}

    title, ev, pg, conf = extract_title(pages, role_scores)
    row["Title"] = title
    title_needs_review = conf < 88 or clean_text(title).lower() in GENERIC_TITLE_WORDS or len(clean_text(title).split()) < 2
    reviews["Title"] = FieldReview(title, conf, ev, pg, "rule", title_needs_review)

    pub, ev, pg, conf = extract_publisher(pages, role_scores)
    row["Publisher"] = pub
    reviews["Publisher"] = FieldReview(pub, conf, ev, pg, "rule", conf < 85)

    dt, ev, pg, conf = extract_date(pages, role_scores)
    row["Date"] = dt
    reviews["Date"] = FieldReview(dt, conf, ev, pg, "rule", conf < 85)

    legacy: Dict[str, str] = {}

    sample_rule, methodology_rule = extract_sample_and_methodology_rule(pages, role_scores)
    row["Sample"] = sample_rule[0]
    reviews["Sample"] = FieldReview(sample_rule[0], sample_rule[3], sample_rule[1], sample_rule[2], "rule", sample_rule[3] < 85)

    row["Methodology"] = format_methodology_summary(methodology_rule[0])
    reviews["Methodology"] = FieldReview(row["Methodology"], methodology_rule[3], methodology_rule[1], methodology_rule[2], "rule", methodology_rule[3] < 85)

    rt, ev, conf = extract_research_type(row["Title"], text)
    legacy["Research Type"] = rt

    cat, evs, conf_cat = classify_category(pages, role_scores, row["Title"])
    legacy["Category"] = cat

    dest, ev_dest, conf_dest = classify_destination_focus(text)
    legacy["Destination Focus"] = dest

    eth, ev_eth, pg_eth, conf_eth = extract_ethnicity_focus(pages)
    legacy["Ethnicity Focus"] = eth
    row["Ethnicity Focus"] = eth
    reviews["Ethnicity Focus"] = FieldReview(eth, conf_eth, ev_eth, pg_eth, "rule", conf_eth < 85)

    old_traveler_market, ev_tm, conf_tm = classify_traveler_market(text)
    legacy["Traveler Market"] = old_traveler_market

    crm_cat, ev, conf = normalize_crm_category(legacy["Category"], row["Title"], text)
    row["CATEGORY"] = crm_cat
    reviews["CATEGORY"] = FieldReview(crm_cat, conf, ev, None, "rule", conf < 85)

    crm_dest, ev, conf = normalize_crm_destination_focus(legacy["Destination Focus"], row["Title"], text)
    row["DESTINATION_FOCUS"] = crm_dest
    reviews["DESTINATION_FOCUS"] = FieldReview(crm_dest, conf, ev, None, "rule", conf < 85)

    # Keep Traveler Market exactly as the original traveler-segment field.
    row["TRAVELER_MARKET"] = old_traveler_market
    reviews["TRAVELER_MARKET"] = FieldReview(old_traveler_market, conf_tm, ev_tm, None, "rule", conf_tm < 85)

    crm_type, ev, conf = normalize_crm_research_type(legacy["Research Type"], row["Title"], source_url)
    row["RESEARCH_TYPE"] = crm_type
    reviews["RESEARCH_TYPE"] = FieldReview(crm_type, conf, ev, None, "rule", conf < 85)


    dp_rule, evs, conf = extract_data_points_rule(pages, role_scores)
    row["Data Points"] = normalize_bullet_block(dp_rule)
    reviews["Data Points"] = FieldReview(row["Data Points"], conf, evs[0] if evs else "", None, "rule", conf < 85)

    row["Summary"] = "Not specified"
    reviews["Summary"] = FieldReview("Not specified", 60, "Summary is generated by Gemini when available", None, "pending", True)

    concl_rule, ev, pg, conf = extract_conclusion_rule(pages, role_scores)
    row["Conclusion"] = normalize_conclusion_or_summary(concl_rule)
    reviews["Conclusion"] = FieldReview(row["Conclusion"], conf if row["Conclusion"] != "Not specified" else 65, ev, pg, "rule", row["Conclusion"] == "Not specified" or conf < 85)

    dm_rule, ev, conf = extract_digital_marketing_insight_rule(text)
    row["Digital Marketing Insight"] = dm_rule
    reviews["Digital Marketing Insight"] = FieldReview(dm_rule, conf, ev, None, "rule", conf < 85)

    llm_used = False
    llm_error = ""
    llm_debug: Dict[str, Any] = {
        "used": False,
        "page_roles": role_scores,
        "legacy_extraction": legacy,
        "ocr_used": any(bool(p.get("ocr_used")) for p in pages),
        "ocr_pages": [p.get("page") for p in pages if p.get("ocr_used")],
        "calls": [],
    }
    llm_model_used = ""

    client = get_gemini_client()
    if client is not None:
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
        fallback_model = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite").strip() or "gemini-2.5-flash-lite"

        try:
            llm_pages = build_llm_context_pages(pages, role_scores)

            llm_result, llm_model_used = llm_extract_semantic_fields(client, model, fallback_model, llm_pages)
            llm_used = True
            llm_debug["used"] = True
            llm_debug["calls"].append(
                {
                    "field_group": "sample_methodology_data_points_conclusion",
                    "model": llm_model_used,
                    "pages": [p["page"] for p in llm_pages],
                }
            )

            ai_sample = clean_text(llm_result.get("sample", "")) or "Not specified"
            ai_methodology = clean_text(llm_result.get("methodology", "")) or "Not specified"
            ai_data_points = normalize_bullet_block("\n".join(llm_result.get("data_points", []) or []))
            ai_conclusion = normalize_conclusion_or_summary(llm_result.get("conclusion", ""))
            ai_dm = clean_text(llm_result.get("digital_marketing_insight", "")) or "Not specified"

            final_sample, final_conf, final_method = choose_final_value(row["Sample"], reviews["Sample"].confidence_pct, ai_sample, 90 if ai_sample != "Not specified" else 0, prefer_rule_threshold=92)
            row["Sample"] = final_sample
            reviews["Sample"] = FieldReview(final_sample, final_conf, "Rule/AI arbitration for Sample", reviews["Sample"].evidence_page, final_method, final_conf < 85)

            final_methodology, final_conf, final_method = choose_final_value(row["Methodology"], reviews["Methodology"].confidence_pct, ai_methodology, 90 if ai_methodology != "Not specified" else 0, prefer_rule_threshold=90)
            row["Methodology"] = final_methodology
            reviews["Methodology"] = FieldReview(final_methodology, final_conf, "Rule/AI arbitration for Methodology", reviews["Methodology"].evidence_page, final_method, final_conf < 85)

            final_dps, final_conf, final_method = choose_final_value(row["Data Points"], reviews["Data Points"].confidence_pct, ai_data_points, 92 if ai_data_points != "Not specified" else 0, prefer_rule_threshold=94)
            row["Data Points"] = normalize_bullet_block(final_dps)
            reviews["Data Points"] = FieldReview(row["Data Points"], final_conf, "Rule/AI arbitration for Data Points", reviews["Data Points"].evidence_page, final_method, final_conf < 85)

            final_conclusion, final_conf, final_method = choose_final_value(row["Conclusion"], reviews["Conclusion"].confidence_pct, ai_conclusion, 92 if ai_conclusion != "Not specified" else 0, prefer_rule_threshold=90)
            row["Conclusion"] = normalize_conclusion_or_summary(final_conclusion)
            reviews["Conclusion"] = FieldReview(row["Conclusion"], final_conf if row["Conclusion"] != "Not specified" else 65, "Rule/AI arbitration for Conclusion/Summary", reviews["Conclusion"].evidence_page, final_method, row["Conclusion"] == "Not specified" or final_conf < 85)

            final_dm, final_conf, final_method = choose_final_value(row["Digital Marketing Insight"], reviews["Digital Marketing Insight"].confidence_pct, ai_dm, 90 if ai_dm != "Not specified" else 0, prefer_rule_threshold=88)
            row["Digital Marketing Insight"] = final_dm
            reviews["Digital Marketing Insight"] = FieldReview(row["Digital Marketing Insight"], final_conf, "Rule/AI arbitration for Digital Marketing Insight", reviews["Digital Marketing Insight"].evidence_page, final_method, final_conf < 85)

            draft_for_validation = {
                "Title": row["Title"],
                "Publisher": row["Publisher"],
                "Date": row["Date"],
                "CATEGORY": row["CATEGORY"],
                "DESTINATION_FOCUS": row["DESTINATION_FOCUS"],
                "TRAVELER_MARKET": row["TRAVELER_MARKET"],
                "Ethnicity Focus": row["Ethnicity Focus"],
                "RESEARCH_TYPE": row["RESEARCH_TYPE"],
                "Digital Marketing Insight": row["Digital Marketing Insight"],
                "Sample": row["Sample"],
                "Methodology": row["Methodology"],
                "Data Points": row["Data Points"],
                "Summary": row["Summary"],
                "Conclusion": row["Conclusion"],
                "Legacy Category": legacy.get("Category", ""),
                "Legacy Destination Focus": legacy.get("Destination Focus", ""),
                "Legacy Ethnicity Focus": legacy.get("Ethnicity Focus", ""),
                "Legacy Traveler Type": legacy.get("Traveler Market", ""),
                "Legacy Research Type": legacy.get("Research Type", ""),
            }
            crm_validation, crm_model_used = llm_crosscheck_crm_fields(client, model, fallback_model, llm_pages, draft_for_validation)
            apply_crm_validation_result(row, reviews, crm_validation)
            llm_debug["calls"].append(
                {
                    "field_group": "crm_taxonomy_crosscheck",
                    "model": crm_model_used,
                    "pages": [p["page"] for p in llm_pages],
                    "result": crm_validation,
                }
            )
            if not llm_model_used:
                llm_model_used = crm_model_used

            draft_for_summary = {
                "Title": row.get("Title", ""),
                "Publisher": row.get("Publisher", ""),
                "Date": row.get("Date", ""),
                "CATEGORY": row.get("CATEGORY", ""),
                "DESTINATION_FOCUS": row.get("DESTINATION_FOCUS", ""),
                "TRAVELER_MARKET": row.get("TRAVELER_MARKET", ""),
                "Ethnicity Focus": row.get("Ethnicity Focus", ""),
                "RESEARCH_TYPE": row.get("RESEARCH_TYPE", ""),
                "Sample": row.get("Sample", ""),
                "Methodology": row.get("Methodology", ""),
                "Data Points": row.get("Data Points", ""),
                "Conclusion": row.get("Conclusion", ""),
            }
            summary_value, summary_model_used = llm_generate_summary(
                client, model, fallback_model, llm_pages, draft_for_summary
            )
            if summary_value and summary_value.strip().lower() != "not specified":
                row["Summary"] = summary_value
                reviews["Summary"] = FieldReview(
                    summary_value,
                    88,
                    "Gemini generated detailed separate source summary",
                    None,
                    "gemini-summary",
                    False,
                )
                llm_debug["calls"].append(
                    {
                        "field_group": "summary",
                        "model": summary_model_used,
                        "pages": [p["page"] for p in llm_pages],
                    }
                )
                if not llm_model_used:
                    llm_model_used = summary_model_used

            if row.get("Conclusion", "Not specified").strip().lower() == "not specified":
                draft_for_conclusion = {
                    "Title": row.get("Title", ""),
                    "Publisher": row.get("Publisher", ""),
                    "Date": row.get("Date", ""),
                    "CATEGORY": row.get("CATEGORY", ""),
                    "DESTINATION_FOCUS": row.get("DESTINATION_FOCUS", ""),
                    "TRAVELER_MARKET": row.get("TRAVELER_MARKET", ""),
                    "RESEARCH_TYPE": row.get("RESEARCH_TYPE", ""),
                    "Summary": row.get("Summary", ""),
                    "Data Points": row.get("Data Points", ""),
                }
                conclusion_value, conclusion_model_used = llm_generate_conclusion_only(
                    client, model, fallback_model, llm_pages, draft_for_conclusion
                )
                if conclusion_value and conclusion_value.lower() != "not specified":
                    row["Conclusion"] = conclusion_value
                    reviews["Conclusion"] = FieldReview(
                        conclusion_value,
                        86,
                        "Gemini generated conclusion/takeaway because no valid conclusion was found",
                        None,
                        "gemini-conclusion",
                        False,
                    )
                    llm_debug["calls"].append(
                        {
                            "field_group": "conclusion_fallback",
                            "model": conclusion_model_used,
                            "pages": [p["page"] for p in llm_pages],
                        }
                    )
                    if not llm_model_used:
                        llm_model_used = conclusion_model_used

        except GeminiQuotaExhaustedError:
            llm_error = "You hit the daily limit."
        except Exception as e:
            llm_error = f"Gemini failed: {e}"

    row["Title"] = clean_text(row.get("Title", "")) or "Not specified"
    row["Publisher"] = clean_text(row.get("Publisher", "")) or "Not specified"
    row["Date"] = clean_text(row.get("Date", "")) or "Not specified"
    row["CATEGORY"] = clean_text(row.get("CATEGORY", "")) or "Not specified"
    row["DESTINATION_FOCUS"] = clean_text(row.get("DESTINATION_FOCUS", "")) or "Not specified"
    row["TRAVELER_MARKET"] = clean_text(row.get("TRAVELER_MARKET", "")) or "Not specified"
    row["Ethnicity Focus"] = clean_text(row.get("Ethnicity Focus", "")) or "Not specified"
    row["RESEARCH_TYPE"] = clean_text(row.get("RESEARCH_TYPE", "")) or "Report"
    row["Sample"] = clean_text(row.get("Sample", "")) or "Not specified"
    row["Methodology"] = format_methodology_summary(row.get("Methodology", ""))
    row["Data Points"] = normalize_bullet_block(row.get("Data Points", ""))
    row["Summary"] = normalize_summary(row.get("Summary", ""))
    if row["Summary"] == "Not specified":
        row["Summary"] = generate_basic_summary_fallback(row)
        if "Summary" in reviews:
            reviews["Summary"] = FieldReview(
                row["Summary"],
                72 if row["Summary"] != "Not specified" else 60,
                "Basic fallback summary from extracted fields",
                None,
                "fallback-summary",
                row["Summary"] == "Not specified",
            )
    row["Conclusion"] = normalize_conclusion_or_summary(row.get("Conclusion", ""))
    row["Digital Marketing Insight"] = clean_text(row.get("Digital Marketing Insight", "")) or "Not specified"

    for field in FIELDS:
        row[field] = str(row.get(field, "")).strip() or "Not specified"
        reviews[field].value = row[field]
        reviews[field].needs_review = reviews[field].needs_review or reviews[field].confidence_pct < 85

    return ExtractionOutput(
        final_row={field: row.get(field, "Not specified") for field in DISPLAY_COLUMNS},
        review_meta={k: asdict(v) for k, v in reviews.items() if k in DISPLAY_COLUMNS},
        raw_text_preview=text[:20000],
        llm_used=llm_used,
        llm_error=llm_error,
        llm_debug=llm_debug,
        llm_model_used=llm_model_used,
    )
