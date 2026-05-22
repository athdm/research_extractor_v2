import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

from extractor import (
    DISPLAY_COLUMNS,
    fetch_url,
    extract_pdf_pages,
    extract_html_pages,
    build_output,
    FetchBlockedError,
    FetchParseError,
)

APP_TITLE = "Research Extractor"
APP_SUBTITLE = (
    "Upload a PDF, paste a URL, or paste article text. "
    "Review the extracted fields, then send useful results to Teable."
)

CATEGORY_OPTIONS = [
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

DESTINATION_FOCUS_OPTIONS = [
    "Not specified",
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

TRAVELER_MARKET_OPTIONS = [
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

RESEARCH_TYPE_OPTIONS = [
    "Report",
    "Survey",
    "Article",
    "eBook",
    "Infographic",
    "Whitepaper",
    "Case Study",
]

STATUS_OPTIONS = [
    "New",
    "Needs Review",
    "Approved",
    "Sent to Content",
    "Used in Strategy",
    "Archived",
    "Rejected",
]

SOURCE_QUALITY_OPTIONS = [
    "High",
    "Medium",
    "Low",
    "Unclear",
]

USEFUL_FOR_OPTIONS = [
    "SEO",
    "Social Media",
    "Paid Ads",
    "Content Strategy",
    "Branding",
    "PR",
    "Email Marketing",
    "Market Research",
    "Client Proposal",
    "Strategy Deck",
    "Website Content",
    "Campaign Planning",
]

RELEVANT_CLIENT_TYPES_OPTIONS = [
    "Hotels",
    "Luxury Hotels",
    "Villas",
    "DMOs",
    "Tour Operators",
    "Travel Agencies",
    "Restaurants",
    "Cruises",
    "Airlines",
    "Car Rentals",
    "Experiences Providers",
]

TREND_STRENGTH_OPTIONS = [
    "Weak Signal",
    "Growing Trend",
    "Strong Trend",
    "Market Shift",
]

TEABLE_FIELD_MAP = {
    "Title": "Title",
    "Publisher": "Publisher",
    "Date": "Date",
    "Sample": "Sample",
    "Methodology": "Methodology",
    "Research Type": "RESEARCH_TYPE",
    "Category": "CATEGORY",
    "Destination Focus": "DESTINATION_FOCUS",
    "Traveler Market": "TRAVELER_MARKET",
    "Data Points": "Data Points",
    "Summary": "Summary",
    "Conclusion": "Conclusion",
    "Digital Marketing Insight": "Digital Marketing Insight",
    "Usefulness": "Usefulness",
    "Client-ready Insight": "Client-ready Insight",
    "Content Ideas": "Content Ideas",
    "Key Statistics": "Key Statistics",
    "Useful For": "Useful For",
    "Relevant Client Types": "Relevant Client Types",
    "Trend Strength": "Trend Strength",
    "Research Value Score": "Research Value Score",
}

OPTIONAL_TEABLE_FIELD_MAP = {
    "Ethnicity Focus": "Ethnicity Focus",
    "PDF Source URL": "PDF Source URL",
    "PDF File Name": "PDF File Name",
    "Source Type": "Source Type",
    "OCR Used": "OCR Used",
    "Gemini Used": "Gemini Used",
    "Confidence Score": "Confidence Score",
    "Needs Review Count": "Needs Review Count",
    "Status": "Status",
    "Source Quality": "Source Quality",
    "Reviewer Notes": "Reviewer Notes",
}


def get_secret(name: str, default: str = "") -> str:
    env_value = os.getenv(name, "").strip()
    if env_value:
        return env_value

    try:
        value = st.secrets.get(name, default)
        return str(value).strip() if value is not None else default
    except Exception:
        return default


def require_password() -> bool:
    password = get_secret("APP_PASSWORD")
    if not password:
        return True

    if st.session_state.get("app_authenticated"):
        return True

    st.title(APP_TITLE)
    st.caption("Private research extraction tool")
    entered = st.text_input("Password", type="password")
    if st.button("Enter", use_container_width=True):
        if entered == password:
            st.session_state.app_authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")

    return False


def _clean_teable_value(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    text = str(value or "").strip()
    if not text or text.lower() == "not specified":
        return ""
    return text


def _teable_multi_select_value(value: Any) -> List[str]:
    """Convert app semicolon/comma/newline separated multi-values to a Teable multiple-select array."""
    if value in ("", None):
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip() and str(v).strip().lower() != "not specified"]

    text = str(value or "").strip()
    if not text or text.lower() == "not specified":
        return []

    raw_parts = []
    for chunk in text.replace("\n", ";").split(";"):
        part = chunk.strip()
        if part:
            raw_parts.append(part)

    if len(raw_parts) <= 1 and "," in text:
        raw_parts = [p.strip() for p in text.split(",") if p.strip()]

    deduped = []
    seen = set()
    for item in raw_parts:
        if item.lower() == "not specified":
            continue
        key = item.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped

def build_teable_fields(final_row: Dict[str, Any], source_url: str = "") -> Dict[str, Any]:
    # Force-send extractor-generated insight fields to Teable.
    # If Usefulness is empty, derive it from the generated insight fields.
    if not str(final_row.get("Digital Marketing Insight", "")).strip():
        final_row["Digital Marketing Insight"] = str(final_row.get("Client-ready Insight", "") or "").strip()

    if not str(final_row.get("Usefulness", "")).strip():
        usefulness_parts = []
        for source_field in ["Client-ready Insight", "Digital Marketing Insight", "Summary", "Key Statistics"]:
            value = str(final_row.get(source_field, "") or "").strip()
            if value and value.lower() != "not specified":
                usefulness_parts.append(value)
        final_row["Usefulness"] = "\n\n".join(usefulness_parts[:3])

    fields: Dict[str, Any] = {}

    multiple_select_fields = {"Category", "Traveler Market", "Useful For", "Relevant Client Types"}

    for teable_field, app_field in TEABLE_FIELD_MAP.items():
        value = final_row.get(app_field, "")
        if teable_field in multiple_select_fields:
            fields[teable_field] = _teable_multi_select_value(value)
        else:
            fields[teable_field] = _clean_teable_value(value)

    for teable_field, app_field in OPTIONAL_TEABLE_FIELD_MAP.items():
        value = final_row.get(app_field, "")
        if value not in ("", None):
            if teable_field in multiple_select_fields:
                fields[teable_field] = _teable_multi_select_value(value)
            else:
                fields[teable_field] = _clean_teable_value(value)

    fields["Source URL"] = source_url.strip()
    fields["Created At"] = datetime.now(timezone.utc).isoformat()
    return fields


def _teable_headers() -> Dict[str, str]:
    api_token = get_secret("TEABLE_API_TOKEN")
    if not api_token:
        raise RuntimeError("TEABLE_API_TOKEN is missing")
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }


def _teable_endpoint(path: str) -> str:
    api_url = get_secret("TEABLE_API_URL", "https://app.teable.ai").rstrip("/")
    return f"{api_url}{path}"



def list_teable_records(limit: int = 100) -> List[Dict[str, Any]]:
    table_id = get_secret("TEABLE_TABLE_ID")
    if not table_id:
        return []

    endpoint = _teable_endpoint(f"/api/table/{table_id}/record")
    params = {
        "fieldKeyType": "name",
        "take": str(limit),
    }

    response = requests.get(endpoint, headers=_teable_headers(), params=params, timeout=30)
    if response.status_code >= 400:
        return []

    data = response.json()
    records = data.get("records") if isinstance(data, dict) else None
    return records if isinstance(records, list) else []


def find_duplicate_in_teable(final_row: Dict[str, Any], source_url: str = "") -> Optional[Dict[str, Any]]:
    title = str(final_row.get("Title", "")).strip().lower()
    url = str(source_url or "").strip().lower()

    if not title and not url:
        return None

    for record in list_teable_records(limit=150):
        fields = record.get("fields", {}) if isinstance(record, dict) else {}
        existing_title = str(fields.get("Title", "")).strip().lower()
        existing_url = str(fields.get("Source URL", "")).strip().lower()

        if url and existing_url and url == existing_url:
            return record
        if title and existing_title and title == existing_title:
            return record

    return None


def append_result_to_teable(final_row: Dict[str, Any], source_url: str = "") -> Dict[str, Any]:
    table_id = get_secret("TEABLE_TABLE_ID")
    if not table_id:
        raise RuntimeError("TEABLE_TABLE_ID is missing")

    endpoint = _teable_endpoint(f"/api/table/{table_id}/record")
    fields = build_teable_fields(final_row, source_url)
    payload = {
        "fieldKeyType": "name",
        "typecast": True,
        "records": [{"fields": fields}],
    }

    response = requests.post(endpoint, json=payload, headers=_teable_headers(), timeout=30)

    # If optional metadata fields have not been created in Teable yet,
    # retry once with only the core fields.
    if response.status_code >= 400 and any(k in fields for k in OPTIONAL_TEABLE_FIELD_MAP):
        core_fields = {
            k: v
            for k, v in fields.items()
            if k not in OPTIONAL_TEABLE_FIELD_MAP and k not in {"Ethnicity Focus", "Digital Marketing Insight", "PDF Source URL", "PDF File Name", "Source Type", "OCR Used", "Gemini Used", "Confidence Score", "Needs Review Count", "Status", "Source Quality", "Usefulness", "Reviewer Notes"}
        }
        payload["records"][0]["fields"] = core_fields
        response = requests.post(endpoint, json=payload, headers=_teable_headers(), timeout=30)

    if response.status_code >= 400:
        try:
            detail = response.json()
        except Exception:
            detail = response.text
        raise RuntimeError(f"Teable API error {response.status_code}: {detail}")

    try:
        return response.json()
    except Exception:
        return {"status": "ok"}


def friendly_llm_error(message: str) -> str:
    msg = (message or "").lower()

    if (
        "quota was exhausted" in msg
        or "quota exhausted" in msg
        or "resource_exhausted" in msg
        or "429" in msg
        or "daily limit" in msg
    ):
        return "You hit the daily limit."

    if "503" in msg or "unavailable" in msg or "high demand" in msg:
        return "Gemini is temporarily unavailable. Please try again later."

    return message or "Gemini error."


def split_multi(value: str) -> List[str]:
    if not value or str(value).strip().lower() == "not specified":
        return []
    parts = [p.strip() for p in str(value).replace("\n", ";").split(";")]
    return [p for p in parts if p]


def join_multi(values: List[str]) -> str:
    return "; ".join(values) if values else "Not specified"


def normalize_choice(value: str, options: List[str], default: str = "Not specified") -> str:
    value = str(value or "").strip()
    return value if value in options else default


def review_to_dataframe(final_row: Dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"Field": field, "Value": final_row.get(field, "Not specified")} for field in DISPLAY_COLUMNS]
    )


def row_to_dataframe(final_row: Dict[str, Any]) -> pd.DataFrame:
    ordered = {field: final_row.get(field, "Not specified") for field in DISPLAY_COLUMNS}
    return pd.DataFrame([ordered])


def review_meta_to_dataframe(review_meta: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for field in DISPLAY_COLUMNS:
        meta = review_meta.get(field, {})
        rows.append(
            {
                "Field": field,
                "Value": meta.get("value", ""),
                "Confidence %": meta.get("confidence_pct", 0),
                "Needs review": meta.get("needs_review", True),
                "Method": meta.get("extraction_method", ""),
                "Evidence page": meta.get("evidence_page", ""),
                "Evidence snippet": meta.get("evidence_snippet", ""),
            }
        )
    return pd.DataFrame(rows)


def style_not_specified(df: pd.DataFrame):
    def highlight(val):
        if isinstance(val, str) and val.strip().lower() == "not specified":
            return "color: #ffb3b3;"
        return ""

    return df.style.map(highlight, subset=["Value"])


def extract_pasted_article_pages(article_text: str) -> List[Dict[str, Any]]:
    cleaned = article_text.strip()
    if not cleaned:
        raise ValueError("Pasted article text is empty.")
    return extract_html_pages(cleaned)


def compute_source_quality(row: Dict[str, Any], avg_conf: int) -> str:
    publisher_ok = str(row.get("Publisher", "")).strip().lower() not in {"", "not specified"}
    methodology_ok = str(row.get("Methodology", "")).strip().lower() not in {"", "not specified"}
    data_ok = str(row.get("Data Points", "")).strip().lower() not in {"", "not specified"}
    conclusion_ok = str(row.get("Conclusion", "")).strip().lower() not in {"", "not specified"}

    if avg_conf >= 85 and publisher_ok and methodology_ok and data_ok:
        return "High"
    if avg_conf >= 75 and publisher_ok and (data_ok or conclusion_ok):
        return "Medium"
    if avg_conf < 65:
        return "Low"
    return "Unclear"


def compute_default_status(needs_review_count: int) -> str:
    return "Needs Review" if needs_review_count > 0 else "New"


def generate_default_usefulness(row: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    title = str(row.get("Title", "")).strip()
    category = str(row.get("CATEGORY", "")).strip()
    traveler_market = str(row.get("TRAVELER_MARKET", "")).strip()
    digital_insight = str(row.get("Digital Marketing Insight", "")).strip()
    summary = str(row.get("Summary", "")).strip()
    data_points = str(row.get("Data Points", "")).strip()

    parts = []

    if title and title.lower() != "not specified":
        parts.append(f"Useful source for tracking insights from '{title}'.")

    if category and category.lower() != "not specified":
        parts.append(f"It can support monitoring of themes such as {category}.")

    if traveler_market and traveler_market.lower() != "not specified":
        parts.append(f"It is relevant for understanding traveler segments such as {traveler_market}.")

    if digital_insight and digital_insight.lower() != "not specified":
        parts.append(f"Marketing relevance: {digital_insight}")

    elif summary and summary.lower() != "not specified":
        parts.append(f"Strategic relevance: {summary}")

    if data_points and data_points.lower() != "not specified":
        first_dp = data_points.replace("•", "").splitlines()[0].strip()
        if first_dp:
            parts.append(f"Contains usable supporting data, for example: {first_dp}")

    return " ".join(parts).strip()

def render_editable_review(row: Dict[str, Any], metadata: Dict[str, Any]) -> Dict[str, Any]:
    st.subheader("Review before sending")
    st.caption("Edit any field before sending the result to Teable.")

    edited: Dict[str, Any] = {}

    col1, col2, col3 = st.columns(3)
    with col1:
        edited["Title"] = st.text_input("Title", value=str(row.get("Title", "")))
    with col2:
        edited["Publisher"] = st.text_input("Publisher", value=str(row.get("Publisher", "")))
    with col3:
        edited["Date"] = st.text_input("Date", value=str(row.get("Date", "")))

    default_categories = [x for x in split_multi(row.get("CATEGORY", "")) if x in CATEGORY_OPTIONS]
    default_travelers = [x for x in split_multi(row.get("TRAVELER_MARKET", "")) if x in TRAVELER_MARKET_OPTIONS]

    edited["CATEGORY"] = join_multi(
        st.multiselect("CATEGORY", CATEGORY_OPTIONS, default=default_categories)
    )

    d_col1, d_col2 = st.columns(2)
    with d_col1:
        dest_default = normalize_choice(row.get("DESTINATION_FOCUS", ""), DESTINATION_FOCUS_OPTIONS, "Not specified")
        edited["DESTINATION_FOCUS"] = st.selectbox(
            "DESTINATION_FOCUS",
            DESTINATION_FOCUS_OPTIONS,
            index=DESTINATION_FOCUS_OPTIONS.index(dest_default),
        )
    with d_col2:
        type_default = normalize_choice(row.get("RESEARCH_TYPE", ""), RESEARCH_TYPE_OPTIONS, "Report")
        edited["RESEARCH_TYPE"] = st.selectbox(
            "RESEARCH_TYPE",
            RESEARCH_TYPE_OPTIONS,
            index=RESEARCH_TYPE_OPTIONS.index(type_default),
        )

    edited["TRAVELER_MARKET"] = join_multi(
        st.multiselect("TRAVELER_MARKET", TRAVELER_MARKET_OPTIONS, default=default_travelers)
    )

    edited["Ethnicity Focus"] = st.text_input(
        "Ethnicity Focus",
        value=str(row.get("Ethnicity Focus", "")),
        help="Ethnicity, nationality, demographic, or source-market focus if the source explicitly mentions one.",
    )

    edited["Sample"] = st.text_area("Sample", value=str(row.get("Sample", "")), height=90)
    edited["Methodology"] = st.text_area("Methodology", value=str(row.get("Methodology", "")), height=120)
    edited["Data Points"] = st.text_area("Data Points", value=str(row.get("Data Points", "")), height=170)
    edited["Summary"] = st.text_area(
        "Summary",
        value=str(row.get("Summary", "")),
        height=130,
        help="General 2-4 sentence summary of the source.",
    )
    edited["Conclusion"] = st.text_area(
        "Conclusion",
        value=str(row.get("Conclusion", "")),
        height=110,
        help="Final takeaway, implication, or recommendation. Separate from Summary.",
    )
    edited["Digital Marketing Insight"] = st.text_area(
        "Digital Marketing Insight",
        value=str(row.get("Digital Marketing Insight", "")),
        height=120,
        placeholder="Useful input, advice, campaign idea, content/social/SEO hint, or practical marketing hack from the source.",
    )

    st.subheader("Client & research intelligence")
    edited["Client-ready Insight"] = st.text_area(
        "Client-ready Insight",
        value=str(row.get("Client-ready Insight", "")),
        height=110,
        placeholder="Concise insight that can be sent to a client or used in a client-facing report.",
    )
    edited["Content Ideas"] = st.text_area(
        "Content Ideas",
        value=str(row.get("Content Ideas", "")),
        height=130,
        placeholder="Content, campaign, SEO, PR, social or strategy ideas.",
    )
    edited["Key Statistics"] = st.text_area(
        "Key Statistics",
        value=str(row.get("Key Statistics", "")),
        height=130,
        placeholder="Key statistics, percentages, scores or numeric findings.",
    )

    useful_default = [x for x in split_multi(row.get("Useful For", "")) if x in USEFUL_FOR_OPTIONS]
    client_types_default = [x for x in split_multi(row.get("Relevant Client Types", "")) if x in RELEVANT_CLIENT_TYPES_OPTIONS]
    edited["Useful For"] = join_multi(st.multiselect("Useful For", USEFUL_FOR_OPTIONS, default=useful_default))
    edited["Relevant Client Types"] = join_multi(st.multiselect("Relevant Client Types", RELEVANT_CLIENT_TYPES_OPTIONS, default=client_types_default))

    t_col1, t_col2 = st.columns(2)
    with t_col1:
        trend_default = normalize_choice(row.get("Trend Strength", ""), TREND_STRENGTH_OPTIONS, "Growing Trend")
        edited["Trend Strength"] = st.selectbox(
            "Trend Strength",
            TREND_STRENGTH_OPTIONS,
            index=TREND_STRENGTH_OPTIONS.index(trend_default),
        )
    with t_col2:
        try:
            score_default = int(float(row.get("Research Value Score", 0)))
        except Exception:
            score_default = 0
        edited["Research Value Score"] = st.number_input(
            "Research Value Score",
            min_value=0,
            max_value=100,
            value=max(0, min(100, score_default)),
            step=1,
        )

    st.subheader("Workflow metadata")
    m1, m2, m3 = st.columns(3)
    with m1:
        edited["Status"] = st.selectbox(
            "Status",
            STATUS_OPTIONS,
            index=STATUS_OPTIONS.index(metadata.get("Status", "Needs Review")),
        )
    with m2:
        edited["Source Quality"] = st.selectbox(
            "Source Quality",
            SOURCE_QUALITY_OPTIONS,
            index=SOURCE_QUALITY_OPTIONS.index(metadata.get("Source Quality", "Unclear")),
        )
    with m3:
        edited["Source Type"] = st.text_input("Source Type", value=str(metadata.get("Source Type", "")))

    edited["PDF Source URL"] = st.text_input(
        "PDF Source URL",
        value=str(metadata.get("PDF Source URL", "")),
        help="Clickable source URL for the PDF/article. In Teable, create this as a URL field.",
    )
    edited["PDF File Name"] = st.text_input(
        "PDF File Name",
        value=str(metadata.get("PDF File Name", "")),
        help="Uploaded local PDF filename. This is not clickable unless the file also has a public URL.",
    )

    edited["Usefulness"] = st.text_area(
        "Usefulness",
        value=str(metadata.get("Usefulness", "")),
        height=90,
        placeholder="Why is this source useful for content, marketing, strategy, or trend monitoring?",
    )
    edited["Reviewer Notes"] = st.text_area(
        "Reviewer Notes",
        value=str(metadata.get("Reviewer Notes", "")),
        height=90,
        placeholder="Manual notes, issues, or follow-up tasks.",
    )

    edited["OCR Used"] = bool(metadata.get("OCR Used", False))
    edited["Gemini Used"] = bool(metadata.get("Gemini Used", False))
    edited["Confidence Score"] = int(metadata.get("Confidence Score", 0))
    edited["Needs Review Count"] = int(metadata.get("Needs Review Count", 0))

    return edited


def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")

    if not require_password():
        return

    st.title(APP_TITLE)
    st.caption(APP_SUBTITLE)

    for key, default in {
        "last_extraction_result": None,
        "last_effective_source_url": "",
        "last_loaded_label": "",
        "last_source_type": "",
        "last_pdf_source_url": "",
        "last_pdf_file_name": "",
        "last_sent_teable_record_id": "",
        "send_anyway_duplicate": False,
    }.items():
        if key not in st.session_state:
            st.session_state[key] = default

    gemini_key = get_secret("GEMINI_API_KEY")
    gemini_model = get_secret("GEMINI_MODEL", "gemini-2.5-flash-lite")
    gemini_fallback_model = get_secret("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")
    teable_token = get_secret("TEABLE_API_TOKEN")
    teable_table_id = get_secret("TEABLE_TABLE_ID")

    with st.sidebar:
        st.header("Input")
        uploaded_pdf = st.file_uploader("Upload PDF", type=["pdf"])
        source_url = st.text_input("Or paste a URL")
        pasted_article_text = st.text_area(
            "Or paste article text",
            height=180,
            placeholder="Use this when a website blocks automated access or copy/paste is easier.",
        )
        run = st.button("Run extraction", use_container_width=True)

        st.divider()
        if gemini_key and teable_token and teable_table_id:
            st.success("System ready")
        elif gemini_key:
            st.warning("Gemini ready, Teable missing")
        else:
            st.warning("Gemini key missing")

        with st.expander("What if URL is blocked?"):
            st.write(
                "If a website blocks automated access, save the page as PDF and upload it, "
                "or paste the article text manually. Image-based PDFs will use OCR/vision fallback."
            )

    if run:
        if not uploaded_pdf and not source_url and not pasted_article_text.strip():
            st.warning("Upload a PDF, paste article text, or enter a URL, then click Run extraction.")
            st.stop()

        pages = []
        loaded_label = ""
        effective_source_url = source_url.strip()
        source_type = ""
        pdf_source_url = ""
        pdf_file_name = ""

        try:
            if uploaded_pdf is not None:
                with st.spinner("Reading PDF..."):
                    pages = extract_pdf_pages(uploaded_pdf)
                source_type = "PDF upload"
                pdf_file_name = uploaded_pdf.name
                pdf_source_url = source_url.strip()
                loaded_label = f"Loaded: {uploaded_pdf.name} ({len(pages)} pages)"
            elif pasted_article_text.strip():
                pages = extract_pasted_article_pages(pasted_article_text)
                effective_source_url = source_url.strip()
                source_type = "Pasted article text"
                pdf_source_url = ""
                pdf_file_name = ""
                loaded_label = "Loaded: pasted article text"
            else:
                with st.spinner("Fetching URL..."):
                    fetched = fetch_url(effective_source_url)

                effective_source_url = fetched.get("source_url", effective_source_url)

                if fetched["type"] == "pdf":
                    pages = extract_pdf_pages(fetched["content"])
                    source_type = "URL PDF"
                    pdf_source_url = effective_source_url
                    pdf_file_name = ""
                    loaded_label = f"Loaded: {effective_source_url} ({len(pages)} pages)"
                else:
                    pages = extract_html_pages(fetched["content"])
                    source_type = "URL web page"
                    pdf_source_url = ""
                    pdf_file_name = ""
                    loaded_label = f"Loaded: {effective_source_url} (web page)"

            st.info(loaded_label)

        except FetchBlockedError as e:
            st.error(str(e))
            st.info(
                "This website blocks automated access. Open the article in your browser, "
                "copy the article text into 'Or paste article text', or save the page as PDF and upload it."
            )
            st.stop()
        except FetchParseError as e:
            st.error(str(e))
            st.stop()
        except Exception as e:
            st.error(f"Input processing failed: {e}")
            st.stop()

        try:
            with st.spinner("Extracting fields..."):
                result = build_output(
                    pages=pages,
                    source_url=effective_source_url,
                    pdf_path=uploaded_pdf.name if uploaded_pdf is not None else "",
                )
        except Exception as e:
            st.error(f"Extraction failed: {e}")
            st.stop()

        st.session_state.last_extraction_result = result
        st.session_state.last_effective_source_url = effective_source_url
        st.session_state.last_loaded_label = loaded_label
        st.session_state.last_source_type = source_type
        st.session_state.last_pdf_source_url = pdf_source_url
        st.session_state.last_pdf_file_name = pdf_file_name
        st.session_state.last_sent_teable_record_id = ""
        st.session_state.send_anyway_duplicate = False

    result = st.session_state.last_extraction_result

    if result is None:
        st.info("Upload a PDF, paste article text, or paste a URL, then click Run extraction.")
        return

    effective_source_url = st.session_state.last_effective_source_url
    loaded_label = st.session_state.last_loaded_label
    source_type = st.session_state.last_source_type
    pdf_source_url = st.session_state.last_pdf_source_url
    pdf_file_name = st.session_state.last_pdf_file_name
    row = result.final_row
    review_meta = result.review_meta

    if loaded_label:
        st.info(loaded_label)

    if result.llm_error:
        st.error(friendly_llm_error(result.llm_error))

    filled = sum(1 for v in row.values() if str(v).strip().lower() != "not specified")
    total = len(DISPLAY_COLUMNS)
    confs = [meta.get("confidence_pct", 0) for meta in review_meta.values()]
    avg_conf = int(sum(confs) / len(confs)) if confs else 0
    needs_review = sum(1 for meta in review_meta.values() if meta.get("needs_review", True))
    ocr_used = bool((result.llm_debug or {}).get("ocr_used", False))

    status_default = compute_default_status(needs_review)
    quality_default = compute_source_quality(row, avg_conf)

    metadata = {
        "PDF Source URL": pdf_source_url,
        "PDF File Name": pdf_file_name,
        "Source Type": source_type,
        "OCR Used": ocr_used,
        "Gemini Used": bool(result.llm_used),
        "Confidence Score": avg_conf,
        "Needs Review Count": needs_review,
        "Status": status_default,
        "Source Quality": quality_default,
        "Usefulness": generate_default_usefulness(row, {
            "Source Type": source_type,
            "Confidence Score": avg_conf,
            "Needs Review Count": needs_review,
        }),
        "Reviewer Notes": "",
    }

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Fields extracted", f"{filled} / {total}")
    with m2:
        st.metric("Avg. confidence", f"{avg_conf}%")
    with m3:
        st.metric("Needs review", str(needs_review))
    with m4:
        st.metric("OCR used", "Yes" if ocr_used else "No")

    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        [
            "Review & send",
            "Field-by-field",
            "Spreadsheet row",
            "Field review",
            "Raw preview",
            "Debug",
        ]
    )

    with tab1:
        edited_row = render_editable_review(row, metadata)

        duplicate = None
        if teable_token and teable_table_id:
            with st.spinner("Checking for duplicates in Teable..."):
                duplicate = find_duplicate_in_teable(edited_row, effective_source_url)

        if duplicate:
            st.warning("Possible duplicate found in Teable. Same title or source URL already exists.")
            with st.expander("Duplicate record details"):
                st.json(duplicate)
            st.session_state.send_anyway_duplicate = st.checkbox(
                "Send anyway",
                value=st.session_state.send_anyway_duplicate,
            )

        st.divider()
        send_disabled = bool(duplicate and not st.session_state.send_anyway_duplicate)
        send_to_teable = st.button(
            "Send reviewed result to Teable",
            use_container_width=True,
            disabled=send_disabled,
        )

        if st.session_state.last_sent_teable_record_id:
            st.success(f"Already sent to Teable. Record ID: {st.session_state.last_sent_teable_record_id}")
        elif not teable_token or not teable_table_id:
            st.warning("Teable token or table ID is missing in Streamlit Secrets.")

        if send_to_teable:
            try:
                teable_response = append_result_to_teable(edited_row, effective_source_url)

                record_id = ""
                records = teable_response.get("records") if isinstance(teable_response, dict) else None
                if isinstance(records, list) and records:
                    record_id = str(records[0].get("id", ""))

                st.session_state.last_sent_teable_record_id = record_id or "sent"
                st.success(f"Result sent to Teable{f' — Record ID: {record_id}' if record_id else ''}.")
                with st.expander("Teable API response"):
                    st.json(teable_response)

            except Exception as e:
                st.error(f"Could not send to Teable: {e}")

    with tab2:
        df_field = review_to_dataframe(row)
        st.dataframe(style_not_specified(df_field), width="stretch", hide_index=True)

    with tab3:
        df_row = row_to_dataframe(row)
        st.dataframe(df_row, width="stretch", hide_index=True)

        csv_bytes = df_row.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download CSV row",
            data=csv_bytes,
            file_name="research_extraction_row.csv",
            mime="text/csv",
        )

        json_bytes = pd.Series(row).to_json(force_ascii=False, indent=2).encode("utf-8")
        st.download_button(
            "Download JSON row",
            data=json_bytes,
            file_name="research_extraction_row.json",
            mime="application/json",
        )

    with tab4:
        df_review = review_meta_to_dataframe(review_meta)
        st.dataframe(df_review, width="stretch", hide_index=True)

    with tab5:
        st.text_area(
            "Raw text preview",
            value=result.raw_text_preview or "",
            height=500,
        )

    with tab6:
        debug_payload = {
            "gemini_key_loaded": bool(gemini_key),
            "gemini_model": gemini_model,
            "gemini_fallback_model": gemini_fallback_model,
            "teable_token_loaded": bool(teable_token),
            "teable_table_id_loaded": bool(teable_table_id),
            "source_type": source_type,
            "pdf_source_url": pdf_source_url,
            "pdf_file_name": pdf_file_name,
            "ocr_used": ocr_used,
            "llm_used": result.llm_used,
            "llm_model_used": result.llm_model_used,
            "llm_error_raw": result.llm_error,
            "llm_error_friendly": friendly_llm_error(result.llm_error) if result.llm_error else "",
            "llm_debug": result.llm_debug,
        }
        st.json(debug_payload)


if __name__ == "__main__":
    main()