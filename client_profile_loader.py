import json
from typing import Any, Dict, Optional


def load_client_profile(uploaded_file) -> Optional[Dict[str, Any]]:
    """
    Load a client profile JSON file uploaded through Streamlit.
    The expected format is a JSON object/dictionary, not a list.
    """
    if uploaded_file is None:
        return None

    try:
        client_profile = json.load(uploaded_file)
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Το αρχείο που ανέβηκε δεν είναι έγκυρο JSON. Λεπτομέρειες: {error}"
        )

    if not isinstance(client_profile, dict):
        raise ValueError(
            "Το αρχείο που ανέβηκε δεν είναι client profile JSON. "
            "Ανέβασε το JSON που παράγεται από τη φόρμα πελάτη, όχι το αρχείο αποτελεσμάτων/insights."
        )

    return client_profile


def validate_client_profile(client_profile: Dict[str, Any]) -> list[str]:
    """
    Check whether the uploaded client profile contains the basic fields
    needed for matching.
    """
    required_fields = [
        "client_name",
        "main_vertical",
        "products_services",
        "target_audiences",
        "business_goals",
        "channels",
    ]

    missing_fields = []

    if not isinstance(client_profile, dict):
        return required_fields

    for field in required_fields:
        value = client_profile.get(field)

        if value is None:
            missing_fields.append(field)
        elif isinstance(value, str) and not value.strip():
            missing_fields.append(field)
        elif isinstance(value, list) and len(value) == 0:
            missing_fields.append(field)

    return missing_fields