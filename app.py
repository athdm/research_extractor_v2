import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

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
    "Field-by-field extraction for unseen PDFs and URLs. "
    "Upload a PDF, paste a direct PDF link, or paste a research page URL."
)


def get_secret(name: str, default: str = "") -> str:
    env_value = os.getenv(name, "").strip()
    if env_value:
        return env_value

    try:
        value = st.secrets.get(name, default)
        return str(value).strip() if value is not None else default
    except Exception:
        return default


# App fields are now CRM-normalized. Teable currently uses friendly column names,
# so this map sends the new app fields into your existing Teable columns.
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
    "Conclusion": "Conclusion",
}



def _clean_teable_value(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "not specified":
        return ""
    return text


def build_teable_fields(final_row: Dict[str, str], source_url: str = "") -> Dict[str, Any]:
    """Return only the useful fields that should be stored in Teable."""
    fields: Dict[str, Any] = {}

    for teable_field, app_field in TEABLE_FIELD_MAP.items():
        fields[teable_field] = _clean_teable_value(final_row.get(app_field, ""))

    fields["Source URL"] = source_url.strip()
    fields["Created At"] = datetime.now(timezone.utc).isoformat()
    return fields


def append_result_to_teable(final_row: Dict[str, str], source_url: str = "") -> Dict[str, Any]:
    api_url = get_secret("TEABLE_API_URL", "https://app.teable.ai").rstrip("/")
    api_token = get_secret("TEABLE_API_TOKEN")
    table_id = get_secret("TEABLE_TABLE_ID")

    if not api_token:
        raise RuntimeError("TEABLE_API_TOKEN is missing from .env")
    if not table_id:
        raise RuntimeError("TEABLE_TABLE_ID is missing from .env")

    endpoint = f"{api_url}/api/table/{table_id}/record"
    payload = {
        "fieldKeyType": "name",
        "typecast": True,
        "records": [
            {
                "fields": build_teable_fields(final_row, source_url),
            }
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    response = requests.post(endpoint, json=payload, headers=headers, timeout=30)

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


def review_to_dataframe(final_row: Dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"Field": field, "Value": final_row.get(field, "Not specified")} for field in DISPLAY_COLUMNS]
    )


def row_to_dataframe(final_row: Dict[str, str]) -> pd.DataFrame:
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
    """Convert manually pasted article text into the same page structure used by URL text."""
    cleaned = article_text.strip()
    if not cleaned:
        raise ValueError("Pasted article text is empty.")
    return extract_html_pages(cleaned)


def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    st.title(APP_TITLE)
    st.caption(APP_SUBTITLE)

    if "last_extraction_result" not in st.session_state:
        st.session_state.last_extraction_result = None
    if "last_effective_source_url" not in st.session_state:
        st.session_state.last_effective_source_url = ""
    if "last_loaded_label" not in st.session_state:
        st.session_state.last_loaded_label = ""
    if "last_sent_teable_record_id" not in st.session_state:
        st.session_state.last_sent_teable_record_id = ""

    gemini_key = get_secret("GEMINI_API_KEY")
    gemini_model = get_secret("GEMINI_MODEL", "gemini-2.5-flash-lite")
    gemini_fallback_model = get_secret("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")
    teable_token = get_secret("TEABLE_API_TOKEN")
    teable_table_id = get_secret("TEABLE_TABLE_ID")

    info_col1, info_col2, info_col3 = st.columns(3)
    with info_col1:
        if gemini_key:
            st.success("Gemini API key detected")
        else:
            st.warning("Gemini API key not detected")
    with info_col2:
        st.info(f"Primary model: {gemini_model}")
    with info_col3:
        st.info(f"Fallback model: {gemini_fallback_model}")

    with st.sidebar:
        st.header("Input")
        uploaded_pdf = st.file_uploader("Upload PDF", type=["pdf"])
        source_url = st.text_input("Or paste a URL (page or direct PDF link)")
        pasted_article_text = st.text_area(
            "Or paste article text",
            height=180,
            placeholder="Use this when a website blocks automated access. Copy the article text from your browser and paste it here.",
        )
        run = st.button("Run extraction", use_container_width=True)

        st.divider()
        if teable_token and teable_table_id:
            st.success("Teable connection settings detected")
        else:
            st.warning("Teable token or table ID missing")

        st.caption("Rule-based extraction still works if Gemini is unavailable.")

    if run:
        if not uploaded_pdf and not source_url and not pasted_article_text.strip():
            st.warning("Upload a PDF, paste article text, or enter a URL, then click Run extraction.")
            st.stop()

        pages = []
        loaded_label = ""
        effective_source_url = source_url.strip()

        try:
            if uploaded_pdf is not None:
                pages = extract_pdf_pages(uploaded_pdf)
                loaded_label = f"Loaded: {uploaded_pdf.name} ({len(pages)} pages)"
            elif pasted_article_text.strip():
                pages = extract_pasted_article_pages(pasted_article_text)
                effective_source_url = source_url.strip()
                loaded_label = "Loaded: pasted article text"
            else:
                with st.spinner("Fetching URL..."):
                    fetched = fetch_url(effective_source_url)

                effective_source_url = fetched.get("source_url", effective_source_url)

                if fetched["type"] == "pdf":
                    pages = extract_pdf_pages(fetched["content"])
                    loaded_label = f"Loaded: {effective_source_url} ({len(pages)} pages)"
                else:
                    pages = extract_html_pages(fetched["content"])
                    loaded_label = f"Loaded: {effective_source_url} (web page)"

            st.info(loaded_label)

        except FetchBlockedError as e:
            st.error(str(e))
            st.info("This website blocks automated access. Open the article in your browser, copy the article text, paste it into 'Or paste article text', then run extraction again. You can also save the page as a PDF and upload it.")
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
        st.session_state.last_sent_teable_record_id = ""

    result = st.session_state.last_extraction_result

    if result is None:
        st.info("Upload a PDF, paste article text, or paste a URL, then click Run extraction.")
        return

    effective_source_url = st.session_state.last_effective_source_url
    loaded_label = st.session_state.last_loaded_label
    row = result.final_row
    review_meta = result.review_meta

    if loaded_label:
        st.info(loaded_label)

    st.success("Extraction complete")

    if result.llm_used and result.llm_model_used:
        st.success(f"Gemini was used for this extraction ({result.llm_model_used})")
    elif gemini_key:
        st.warning("Gemini key is present, but this run completed without Gemini.")
    else:
        st.info("Extraction ran without Gemini.")

    if result.llm_error:
        st.error(friendly_llm_error(result.llm_error))

    filled = sum(1 for v in row.values() if str(v).strip().lower() != "not specified")
    total = len(DISPLAY_COLUMNS)
    confs = [meta.get("confidence_pct", 0) for meta in review_meta.values()]
    avg_conf = int(sum(confs) / len(confs)) if confs else 0
    needs_review = sum(1 for meta in review_meta.values() if meta.get("needs_review", True))

    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("Fields extracted", f"{filled} / {total}")
    with m2:
        st.metric("Avg. confidence", f"{avg_conf}%")
    with m3:
        st.metric("Needs review", str(needs_review))

    st.divider()
    send_col, status_col = st.columns([1, 2])
    with send_col:
        send_to_teable = st.button("Send result to Teable", use_container_width=True)
    with status_col:
        if st.session_state.last_sent_teable_record_id:
            st.success(f"Already sent to Teable. Record ID: {st.session_state.last_sent_teable_record_id}")
        elif not teable_token or not teable_table_id:
            st.warning("Add TEABLE_API_TOKEN and TEABLE_TABLE_ID to .env before sending.")

    if send_to_teable:
        try:
            teable_response = append_result_to_teable(row, effective_source_url)

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

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "Field-by-field",
            "Spreadsheet row",
            "Field review",
            "Raw preview",
            "LLM debug",
        ]
    )

    with tab1:
        df_field = review_to_dataframe(row)
        st.dataframe(style_not_specified(df_field), width="stretch", hide_index=True)

    with tab2:
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

    with tab3:
        df_review = review_meta_to_dataframe(review_meta)
        st.dataframe(df_review, width="stretch", hide_index=True)

    with tab4:
        st.text_area(
            "Raw text preview",
            value=result.raw_text_preview or "",
            height=500,
        )

    with tab5:
        debug_payload = {
            "gemini_key_loaded": bool(gemini_key),
            "gemini_key_length": len(gemini_key),
            "teable_token_loaded": bool(teable_token),
            "teable_token_length": len(teable_token),
            "teable_table_id_loaded": bool(teable_table_id),
            "teable_table_id": teable_table_id,
            "llm_used": result.llm_used,
            "llm_model_used": result.llm_model_used,
            "llm_error_raw": result.llm_error,
            "llm_error_friendly": friendly_llm_error(result.llm_error) if result.llm_error else "",
            "llm_debug": result.llm_debug,
        }
        st.json(debug_payload)


if __name__ == "__main__":
    main()