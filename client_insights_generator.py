from typing import Any, Dict, List, Set, Tuple


PLANNING_BOOKING_KEYWORDS = [
    "planning",
    "booking",
    "travel planning",
    "booking behavior",
    "travel planning & booking",
    "conversion",
    "decision",
    "direct bookings",
    "website",
    "google search",
    "κρατηση",
    "κράτηση",
    "κρατησεις",
    "κρατήσεις",
    "σχεδιασμ",
    "οργανώνει",
    "αγορά",
    "απόφαση",
    "ευκολία",
]


# -----------------------------------------------------------------------------
# Normalization and scoring helpers
# -----------------------------------------------------------------------------


def normalize_values(values: Any) -> Set[str]:
    """
    Convert a string/list/dict value into a normalized lowercase set.
    Used to make matching between client profile fields and research tags stable.
    """
    if not values:
        return set()

    if isinstance(values, dict):
        values = list(values.values())
    elif isinstance(values, str):
        values = [values]

    return {
        str(value).strip().lower()
        for value in values
        if str(value).strip()
    }


def calculate_overlap_score(
    client_values: Any,
    research_values: Any,
    max_points: int,
) -> Tuple[int, List[str]]:
    """
    Calculate overlap between client profile values and research tags.

    Returns:
    - score: int
    - matched values: list[str]
    """
    client_set = normalize_values(client_values)
    research_set = normalize_values(research_values)

    if not client_set or not research_set:
        return 0, []

    matched = client_set.intersection(research_set)

    if not matched:
        return 0, []

    score = int((len(matched) / len(research_set)) * max_points)
    score = min(score, max_points)

    return score, sorted(matched)


def relevance_label(score: int) -> str:
    """Convert a numeric relevance score into a client-friendly label."""
    if score >= 70:
        return "High relevance"
    if score >= 40:
        return "Medium relevance"
    return "Supporting context"


def contains_context(value: Any, keywords: List[str]) -> bool:
    """Return True if a value/list/dict contains any of the supplied keywords."""
    if not value:
        return False

    if isinstance(value, dict):
        text = " ".join(str(item) for item in value.values())
    elif isinstance(value, list):
        text = " ".join(str(item) for item in value)
    else:
        text = str(value)

    text = text.lower()
    return any(keyword.lower() in text for keyword in keywords)


# -----------------------------------------------------------------------------
# Research insight matching
# -----------------------------------------------------------------------------


def generate_reason(
    client_profile: Dict[str, Any],
    research_block: Dict[str, Any],
    matched_tags: Dict[str, List[str]],
) -> str:
    """Generate a human-readable reason for why a research block matched."""
    client_name = client_profile.get("client_name", "Το brand")
    research_title = research_block.get("research_title", "η συγκεκριμένη έρευνα")

    reasons = []

    if matched_tags.get("vertical"):
        reasons.append("την κατηγορία της επιχείρησης")
    if matched_tags.get("products"):
        reasons.append("τα προϊόντα ή τις υπηρεσίες")
    if matched_tags.get("audience"):
        reasons.append("το κοινό-στόχο")
    if matched_tags.get("goals"):
        reasons.append("τους επιχειρησιακούς στόχους")
    if matched_tags.get("channels"):
        reasons.append("τα κανάλια επικοινωνίας")
    if matched_tags.get("campaigns"):
        reasons.append("τις ανάγκες καμπάνιας")
    if matched_tags.get("needs"):
        reasons.append("τις ανάγκες / προτιμήσεις του κοινού")

    if not reasons:
        return f"Η έρευνα «{research_title}» έχει γενική συνάφεια με το προφίλ του brand."

    return (
        f"Η έρευνα «{research_title}» είναι σχετική με το {client_name}, "
        f"επειδή συνδέεται με {', '.join(reasons)}."
    )


def create_strategic_context(
    client_profile: Dict[str, Any],
    research_block: Dict[str, Any],
) -> str:
    """
    Create a supporting context paragraph.
    This is secondary to the statistics, not the main output.
    """
    client_name = client_profile.get("client_name", "Το brand")
    key_finding = research_block.get("key_finding", "")
    suggested_usage = research_block.get("suggested_usage", [])
    usage_text = ", ".join(suggested_usage[:2]) if suggested_usage else "στρατηγική επικοινωνία"

    if key_finding:
        return (
            f"Για το {client_name}, το εύρημα «{key_finding}» μπορεί να αξιοποιηθεί σε "
            f"{usage_text}, ως υποστηρικτικό context για τη συμπεριφορά και τις προτιμήσεις "
            f"του πιθανού κοινού."
        )

    return (
        f"Για το {client_name}, το συγκεκριμένο research block μπορεί να αξιοποιηθεί ως "
        f"υποστηρικτικό context, καθώς συνδέεται με βασικά στοιχεία του client profile."
    )


def extract_planning_booking_points(research_block: Dict[str, Any]) -> List[str]:
    """
    Extract planning & booking related points from a research block.
    These are shown separately in the app/report.
    """
    points: List[str] = []

    fields_to_check = [
        research_block.get("key_finding", ""),
        research_block.get("evidence", ""),
        " ".join(research_block.get("topic_tags", [])),
        " ".join(research_block.get("need_tags", [])),
        " ".join(research_block.get("channel_tags", [])),
        " ".join(research_block.get("campaign_tags", [])),
        " ".join(research_block.get("suggested_usage", [])),
    ]

    for field_value in fields_to_check:
        if contains_context(field_value, PLANNING_BOOKING_KEYWORDS):
            cleaned = str(field_value).strip()
            if cleaned and cleaned not in points:
                points.append(cleaned)

    for statistic in research_block.get("statistics", []):
        stat_text = statistic.get("stat", "")
        evidence_text = statistic.get("evidence", "")
        topic_tags = statistic.get("topic_tags", [])
        behavior_type = statistic.get("behavior_type", "")
        journey_stage = statistic.get("journey_stage", "")

        if (
            contains_context(stat_text, PLANNING_BOOKING_KEYWORDS)
            or contains_context(evidence_text, PLANNING_BOOKING_KEYWORDS)
            or contains_context(topic_tags, PLANNING_BOOKING_KEYWORDS)
            or contains_context(behavior_type, PLANNING_BOOKING_KEYWORDS)
            or contains_context(journey_stage, PLANNING_BOOKING_KEYWORDS)
        ):
            if stat_text and stat_text not in points:
                points.append(stat_text)

    return points[:6]


def match_research_to_client(
    client_profile: Dict[str, Any],
    research_blocks: List[Dict[str, Any]],
    min_score: int = 15,
) -> List[Dict[str, Any]]:
    """Match a client profile with research blocks and return ranked supporting context."""
    matches = []

    client_verticals = [client_profile.get("main_vertical", "")] + client_profile.get("secondary_verticals", [])
    client_products = client_profile.get("products_services", [])
    client_audience = client_profile.get("target_audiences", [])
    client_goals = client_profile.get("business_goals", [])
    client_channels = client_profile.get("channels", [])
    client_campaigns = client_profile.get("campaign_needs", [])
    client_needs = client_profile.get("audience_needs", [])
    client_research_needs = client_profile.get("research_needs", [])

    for block in research_blocks:
        vertical_score, vertical_matches = calculate_overlap_score(client_verticals, block.get("vertical_tags", []), 18)
        product_score, product_matches = calculate_overlap_score(client_products, block.get("product_tags", []), 18)
        audience_score, audience_matches = calculate_overlap_score(client_audience, block.get("audience_tags", []), 18)
        goal_score, goal_matches = calculate_overlap_score(client_goals, block.get("business_goal_tags", []), 16)
        channel_score, channel_matches = calculate_overlap_score(client_channels, block.get("channel_tags", []), 8)
        campaign_score, campaign_matches = calculate_overlap_score(
            client_campaigns,
            block.get("campaign_tags", []) + block.get("channel_tags", []) + block.get("suggested_usage", []),
            8,
        )
        needs_score, needs_matches = calculate_overlap_score(
            client_needs + client_research_needs,
            block.get("need_tags", []) + block.get("topic_tags", []) + block.get("suggested_usage", []),
            8,
        )

        source_quality_score = int(block.get("source_quality_score", 0))

        relevance_score = (
            vertical_score
            + product_score
            + audience_score
            + goal_score
            + channel_score
            + campaign_score
            + needs_score
            + source_quality_score
        )

        matched_tags = {
            "vertical": vertical_matches,
            "products": product_matches,
            "audience": audience_matches,
            "goals": goal_matches,
            "channels": channel_matches,
            "campaigns": campaign_matches,
            "needs": needs_matches,
        }

        if relevance_score >= min_score:
            matches.append({
                "research_id": block.get("id", ""),
                "research_title": block.get("research_title", ""),
                "relevance_score": relevance_score,
                "relevance_label": relevance_label(relevance_score),
                "supporting_context": create_strategic_context(client_profile, block),
                "why_it_matches": generate_reason(client_profile, block, matched_tags),
                "planning_booking_points": extract_planning_booking_points(block),
                "key_finding": block.get("key_finding", ""),
                "evidence": block.get("evidence", ""),
                "suggested_usage": block.get("suggested_usage", []),
                "matched_tags": matched_tags,
                "score_breakdown": {
                    "vertical_score": vertical_score,
                    "product_score": product_score,
                    "audience_score": audience_score,
                    "goal_score": goal_score,
                    "channel_score": channel_score,
                    "campaign_score": campaign_score,
                    "needs_score": needs_score,
                    "source_quality_score": source_quality_score,
                },
                "source": {
                    "source_name": block.get("source_name", ""),
                    "source_report": block.get("source_report", ""),
                    "source_year": block.get("source_year", ""),
                    "source_file": block.get("source_file", ""),
                },
            })

    return sorted(matches, key=lambda item: item["relevance_score"], reverse=True)


# -----------------------------------------------------------------------------
# Statistic matching
# -----------------------------------------------------------------------------


def infer_behavior_type(statistic: Dict[str, Any]) -> str:
    """Infer a behavior type if the statistic does not explicitly provide one."""
    explicit = str(statistic.get("behavior_type", "")).strip()
    if explicit:
        return explicit

    topic_text = " ".join(statistic.get("topic_tags", []))
    stat_text = statistic.get("stat", "")

    if contains_context(topic_text + " " + stat_text, ["social", "instagram", "tiktok", "content"]):
        return "Inspiration / Social Media"
    if contains_context(topic_text + " " + stat_text, PLANNING_BOOKING_KEYWORDS):
        return "Planning & Booking"
    if contains_context(topic_text + " " + stat_text, ["spending", "budget", "premium", "luxury"]):
        return "Spending / Value"
    if contains_context(topic_text + " " + stat_text, ["trust", "credibility", "reliability", "εμπιστοσύνη"]):
        return "Trust / Decision Factors"
    if contains_context(topic_text + " " + stat_text, ["sustainability", "authentic", "local", "αυθεν"]):
        return "Authenticity / Local Experience"

    return "Audience Behavior"


def infer_what_this_shows(statistic: Dict[str, Any]) -> str:
    """Fallback explanation for what a statistic shows."""
    explicit = str(statistic.get("what_this_shows", "")).strip()
    if explicit:
        return explicit

    behavior_type = infer_behavior_type(statistic)

    if behavior_type == "Planning & Booking":
        return "Το κοινό δίνει σημασία στην ευκολία, τη σαφήνεια και την ψηφιακή εμπειρία κατά τον σχεδιασμό ή την κράτηση."
    if behavior_type == "Inspiration / Social Media":
        return "Το κοινό επηρεάζεται από ψηφιακά και social touchpoints όταν εμπνέεται ή επιλέγει εμπειρίες."
    if behavior_type == "Spending / Value":
        return "Το κοινό αξιολογεί την αξία, την ποιότητα και το perceived value πριν προχωρήσει σε αγορά ή κράτηση."
    if behavior_type == "Trust / Decision Factors":
        return "Η εμπιστοσύνη, η αξιοπιστία και η καθαρή πληροφορία επηρεάζουν την τελική απόφαση."
    if behavior_type == "Authenticity / Local Experience":
        return "Το κοινό αναζητά πιο ουσιαστική σύνδεση με τον προορισμό, την τοπική κουλτούρα και αυθεντικές εμπειρίες."

    return "Το στατιστικό δείχνει συμπεριφορά ή προτίμηση κοινού που μπορεί να επηρεάσει τη στρατηγική επικοινωνίας και conversion."


def infer_client_implication(client_profile: Dict[str, Any], statistic: Dict[str, Any]) -> str:
    """Fallback implication for the client based on profile and statistic context."""
    explicit = str(statistic.get("client_implication", "")).strip()
    if explicit:
        return explicit

    behavior_type = infer_behavior_type(statistic)
    channels = normalize_values(client_profile.get("channels", []))
    goals = normalize_values(client_profile.get("business_goals", []))

    if behavior_type == "Planning & Booking":
        return "Ο client πρέπει να δώσει έμφαση σε γρήγορη, ξεκάθαρη και mobile-friendly διαδικασία πληροφόρησης και κράτησης."
    if behavior_type == "Inspiration / Social Media":
        return "Ο client μπορεί να αξιοποιήσει social-first περιεχόμενο για inspiration και να οδηγεί το κοινό σε πιο ξεκάθαρα conversion touchpoints."
    if behavior_type == "Spending / Value":
        return "Ο client πρέπει να κάνει σαφές το value της υπηρεσίας, τι περιλαμβάνεται και γιατί αξίζει η επιλογή του."
    if behavior_type == "Trust / Decision Factors":
        return "Ο client πρέπει να ενισχύσει trust signals όπως reviews, testimonials, ξεκάθαρους όρους και σαφή πληροφόρηση κοντά στο CTA."
    if behavior_type == "Authenticity / Local Experience":
        return "Ο client μπορεί να αναδείξει local expertise, αυθεντικές εμπειρίες και στοιχεία που δείχνουν σύνδεση με τον προορισμό."

    if "αύξηση direct bookings" in goals or "website" in channels:
        return "Ο client μπορεί να χρησιμοποιήσει το εύρημα για βελτίωση website, messaging και conversion flow."

    return "Ο client μπορεί να αξιοποιήσει το στατιστικό για πιο στοχευμένο messaging, περιεχόμενο και campaign planning."


def generate_stat_reason(matched_tags: Dict[str, List[str]]) -> str:
    """Generate reason for why a statistic was selected."""
    reasons = []

    if matched_tags.get("audience"):
        reasons.append("το κοινό-στόχο")
    if matched_tags.get("markets"):
        reasons.append("τις αγορές / χώρες ενδιαφέροντος")
    if matched_tags.get("topics"):
        reasons.append("τις research ανάγκες ή ανάγκες κοινού")
    if matched_tags.get("products"):
        reasons.append("τα προϊόντα ή τις υπηρεσίες")
    if matched_tags.get("goals"):
        reasons.append("τους επιχειρησιακούς στόχους")

    if not reasons:
        return "Το στατιστικό έχει γενική συνάφεια με το προφίλ του πελάτη."

    return "Το στατιστικό επιλέχθηκε επειδή συνδέεται με " + ", ".join(reasons) + "."


def match_statistics_to_client(
    client_profile: Dict[str, Any],
    research_blocks: List[Dict[str, Any]],
    min_score: int = 1,
) -> List[Dict[str, Any]]:
    """
    Match client profile with individual statistics inside research blocks.
    These are the main output of the Client Audience Intelligence module.
    """
    matched_statistics = []

    client_audience = client_profile.get("target_audiences", [])
    client_markets = client_profile.get("markets", [])
    client_products = client_profile.get("products_services", [])
    client_goals = client_profile.get("business_goals", [])
    client_research_needs = client_profile.get("research_needs", [])
    client_audience_needs = client_profile.get("audience_needs", [])

    for block in research_blocks:
        for statistic in block.get("statistics", []):
            audience_score, audience_matches = calculate_overlap_score(client_audience, statistic.get("audience_tags", []), 35)
            market_score, market_matches = calculate_overlap_score(client_markets, statistic.get("market_tags", []), 20)
            topic_score, topic_matches = calculate_overlap_score(
                client_research_needs + client_audience_needs,
                statistic.get("topic_tags", []),
                20,
            )
            product_score, product_matches = calculate_overlap_score(client_products, statistic.get("product_tags", []), 15)
            goal_score, goal_matches = calculate_overlap_score(client_goals, statistic.get("business_goal_tags", []), 10)

            statistic_score = audience_score + market_score + topic_score + product_score + goal_score

            matched_tags = {
                "audience": audience_matches,
                "markets": market_matches,
                "topics": topic_matches,
                "products": product_matches,
                "goals": goal_matches,
            }

            if statistic_score >= min_score:
                behavior_type = infer_behavior_type(statistic)

                matched_statistics.append({
                    "stat": statistic.get("stat", ""),
                    "statistic_score": statistic_score,
                    "relevance_label": relevance_label(statistic_score),
                    "behavior_type": behavior_type,
                    "journey_stage": statistic.get("journey_stage", ""),
                    "what_this_shows": infer_what_this_shows(statistic),
                    "client_implication": infer_client_implication(client_profile, statistic),
                    "why_it_matches": generate_stat_reason(matched_tags),
                    "matched_tags": matched_tags,
                    "evidence": statistic.get("evidence", ""),
                    "source": {
                        "source_name": statistic.get("source_name", block.get("source_name", "")),
                        "source_report": statistic.get("source_report", block.get("source_report", "")),
                        "source_year": statistic.get("source_year", block.get("source_year", "")),
                        "source_file": statistic.get("source_file", block.get("source_file", "")),
                    },
                    "parent_research": {
                        "research_id": block.get("id", ""),
                        "research_title": block.get("research_title", ""),
                    },
                })

    return sorted(matched_statistics, key=lambda item: item["statistic_score"], reverse=True)


# -----------------------------------------------------------------------------
# Action recommendations
# -----------------------------------------------------------------------------


def _unique_actions(actions: List[str], max_items: int = 6) -> List[str]:
    """Deduplicate actions while preserving order."""
    output = []
    seen = set()

    for action in actions:
        key = action.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(action.strip())

    return output[:max_items]


def generate_action_recommendations(client_profile: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Generate practical action recommendations based on the client profile.

    Returns three groups:
    - social_media_actions
    - web_development_actions
    - digital_marketing_actions
    """
    channels = normalize_values(client_profile.get("channels", []))
    campaign_needs = normalize_values(client_profile.get("campaign_needs", []))
    business_goals = normalize_values(client_profile.get("business_goals", []))
    target_audiences = normalize_values(client_profile.get("target_audiences", []))
    audience_needs = normalize_values(client_profile.get("audience_needs", []))
    products_services = normalize_values(client_profile.get("products_services", []))
    brand_positioning = normalize_values(client_profile.get("brand_positioning", []))
    main_conversion = str(client_profile.get("main_conversion", "")).strip().lower()
    main_channel = str(client_profile.get("main_channel", "")).strip().lower()

    social_media_actions: List[str] = []
    web_development_actions: List[str] = []
    digital_marketing_actions: List[str] = []

    # Social Media Actions
    if (
        "instagram organic" in channels
        or "tiktok organic" in channels
        or "facebook organic" in channels
        or "influencers / creators" in channels
        or "organic social content" in campaign_needs
        or "tiktok campaign" in campaign_needs
    ):
        social_media_actions.append(
            "Δημιουργία content pillars ανά στάδιο απόφασης: inspiration, planning και booking."
        )

    if "gen z" in target_audiences or "millennials" in target_audiences:
        social_media_actions.append(
            "Έμφαση σε short-form video περιεχόμενο για TikTok / Reels, με γρήγορα, αυθεντικά και οπτικά δυνατά concepts."
        )

    if (
        "φωτογραφικό / instagrammable περιεχόμενο" in audience_needs
        or "photography / photoshoots" in products_services
        or "proposal experiences" in products_services
        or "flying dress / fashion photoshoots" in products_services
    ):
        social_media_actions.append(
            "Αξιοποίηση visual-first και UGC-style περιεχομένου που δείχνει εμπειρίες, moments και πραγματική χρήση της υπηρεσίας."
        )

    if "αυθεντικές εμπειρίες" in audience_needs or "τοπική καθοδήγηση" in audience_needs or "local" in brand_positioning:
        social_media_actions.append(
            "Ανάδειξη local/authentic στοιχείων μέσα από storytelling, behind-the-scenes περιεχόμενο και προτάσεις από ανθρώπους της επιχείρησης."
        )

    if "αύξηση social media engagement" in business_goals:
        social_media_actions.append(
            "Χρήση interactive formats όπως polls, Q&As, carousels και saveable guides για αύξηση engagement."
        )

    if "premium" in brand_positioning or "luxury" in brand_positioning:
        social_media_actions.append(
            "Δημιουργία premium visual identity στα social με καθαρό ύφος, συνεπή αισθητική και λιγότερο discount-focused μηνύματα."
        )

    if not social_media_actions:
        social_media_actions.append(
            "Δημιουργία βασικής παρουσίας με 3-4 σταθερά content themes: υπηρεσίες, εμπειρίες πελατών, τοπικότητα και trust-building περιεχόμενο."
        )

    # Web Development Actions
    if (
        "website" in channels
        or main_channel == "website"
        or "website / landing page copy" in campaign_needs
        or main_conversion in {"booking", "αγορά προϊόντος / υπηρεσίας", "contact form"}
    ):
        web_development_actions.append(
            "Βελτίωση landing pages ώστε κάθε βασική υπηρεσία να έχει ξεκάθαρη περιγραφή, τι περιλαμβάνει, διάρκεια, τιμή ή εύρος τιμής και εμφανές CTA."
        )

    if "αύξηση direct bookings" in business_goals or main_conversion == "booking":
        web_development_actions.append(
            "Απλοποίηση του booking flow με λιγότερα βήματα, εμφανή διαθεσιμότητα, ξεκάθαρους όρους και trust elements κοντά στο CTA."
        )

    if "ευκολία στην κράτηση" in audience_needs or "γρήγορη εξυπηρέτηση" in audience_needs:
        web_development_actions.append(
            "Προσθήκη άμεσων contact options όπως WhatsApp, phone ή quick inquiry button σε εμφανή σημεία του website."
        )

    if "ασφάλεια και εμπιστοσύνη" in audience_needs or "ενίσχυση εμπιστοσύνης / credibility" in business_goals:
        web_development_actions.append(
            "Ενίσχυση trust signals στο website: reviews, testimonials, cancellation policy, secure payment indicators και σαφείς πληροφορίες παρόχου."
        )

    if "google search" in channels or "google search campaign" in campaign_needs:
        web_development_actions.append(
            "Δημιουργία SEO-friendly landing pages ανά υπηρεσία, προορισμό ή εμπειρία, ώστε να υποστηρίζονται καλύτερα Google Search campaigns."
        )

    if not web_development_actions:
        web_development_actions.append(
            "Βελτίωση βασικής δομής website με καθαρά sections για υπηρεσίες, κοινό-στόχο, λόγους επιλογής και εύκολη επικοινωνία."
        )

    # Digital Marketing Actions
    if "google search" in channels or "google search campaign" in campaign_needs:
        digital_marketing_actions.append(
            "Δημιουργία Google Search campaigns για high-intent keywords που συνδέονται με υπηρεσίες, προορισμό και booking intent."
        )

    if "meta ads" in channels or "meta ads campaign" in campaign_needs:
        digital_marketing_actions.append(
            "Χρήση Meta Ads για awareness και retargeting, με διαφορετικά creatives για inspiration, consideration και booking."
        )

    if "tiktok campaign" in campaign_needs or "tiktok ads" in channels:
        digital_marketing_actions.append(
            "Δοκιμή TikTok campaigns με short-form creatives που δείχνουν εμπειρία, συναίσθημα και άμεσο value proposition."
        )

    if "αύξηση brand awareness" in business_goals:
        digital_marketing_actions.append(
            "Διαχωρισμός awareness campaigns από conversion campaigns, ώστε να μετριούνται διαφορετικά reach, engagement και booking intent."
        )

    if "αύξηση direct bookings" in business_goals:
        digital_marketing_actions.append(
            "Στήσιμο retargeting για χρήστες που επισκέφθηκαν βασικές landing pages ή ξεκίνησαν διαδικασία κράτησης χωρίς να ολοκληρώσουν."
        )

    if "lead generation" in business_goals:
        digital_marketing_actions.append(
            "Δημιουργία lead capture μηχανισμού με φόρμα ενδιαφέροντος, newsletter signup ή downloadable guide."
        )

    if "pr / press release" in campaign_needs:
        digital_marketing_actions.append(
            "Αξιοποίηση των πιο ισχυρών research statistics ως τεκμηρίωση σε PR angles, press releases ή media pitches."
        )

    if not digital_marketing_actions:
        digital_marketing_actions.append(
            "Δημιουργία βασικού funnel με awareness content, traffic campaigns και conversion-focused landing pages."
        )

    return {
        "social_media_actions": _unique_actions(social_media_actions),
        "web_development_actions": _unique_actions(web_development_actions),
        "digital_marketing_actions": _unique_actions(digital_marketing_actions),
    }


# -----------------------------------------------------------------------------
# Enhanced strategic outputs: action cards, audience segments, content angles,
# and 30/60/90 day plan
# -----------------------------------------------------------------------------


def _source_text(source: Dict[str, Any]) -> str:
    """Return a compact source string."""
    return (
        f"{source.get('source_name', '')} — "
        f"{source.get('source_report', '')} "
        f"({source.get('source_year', '')})"
    ).strip()


def _first_relevant_statistic(
    matched_statistics: List[Dict[str, Any]],
    keywords: List[str],
) -> Dict[str, Any]:
    """
    Pick the first statistic that contains one of the supplied keywords.
    Falls back to the top statistic.
    """
    if not matched_statistics:
        return {}

    for statistic in matched_statistics:
        searchable = " ".join([
            str(statistic.get("stat", "")),
            str(statistic.get("behavior_type", "")),
            str(statistic.get("what_this_shows", "")),
            str(statistic.get("client_implication", "")),
            str(statistic.get("evidence", "")),
            " ".join(sum([
                statistic.get("matched_tags", {}).get("audience", []),
                statistic.get("matched_tags", {}).get("topics", []),
                statistic.get("matched_tags", {}).get("products", []),
                statistic.get("matched_tags", {}).get("goals", []),
            ], [])),
        ]).lower()

        if any(keyword.lower() in searchable for keyword in keywords):
            return statistic

    return matched_statistics[0]


def generate_evidence_backed_action_cards(
    client_profile: Dict[str, Any],
    matched_statistics: List[Dict[str, Any]],
    action_recommendations: Dict[str, List[str]],
) -> List[Dict[str, Any]]:
    """
    Convert action recommendations into evidence-backed action cards.
    Each card contains an action, why it matters, supporting statistic, and source.
    """
    client_name = client_profile.get("client_name", "το brand")

    action_groups = [
        ("Social Media", action_recommendations.get("social_media_actions", []), ["social", "instagram", "tiktok", "content", "inspiration", "digital"]),
        ("Web Development", action_recommendations.get("web_development_actions", []), ["website", "booking", "trust", "conversion", "digital", "ευκολία", "κράτηση"]),
        ("Digital Marketing", action_recommendations.get("digital_marketing_actions", []), ["google", "ads", "campaign", "retargeting", "booking", "awareness", "conversion"]),
    ]

    cards: List[Dict[str, Any]] = []

    for category, actions, keywords in action_groups:
        for action in actions[:4]:
            stat = _first_relevant_statistic(matched_statistics, keywords)
            source = stat.get("source", {}) if stat else {}

            if stat:
                evidence_stat = stat.get("stat", "")
                why_it_matters = (
                    f"Η ενέργεια είναι σχετική για το {client_name}, επειδή συνδέεται με "
                    f"{stat.get('behavior_type', 'audience behavior').lower()} και με το matched κοινό/στόχους του client."
                )
                source_text = _source_text(source)
            else:
                evidence_stat = "Δεν υπάρχει ακόμα άμεσα συνδεδεμένο statistic στη βάση."
                why_it_matters = (
                    f"Η ενέργεια προκύπτει από το client profile και μπορεί να χρησιμοποιηθεί ως πρακτική κατεύθυνση."
                )
                source_text = "—"

            cards.append({
                "category": category,
                "action": action,
                "why_it_matters": why_it_matters,
                "supporting_statistic": evidence_stat,
                "source": source,
                "source_text": source_text,
                "priority": "High" if category in {"Web Development", "Digital Marketing"} else "Medium",
            })

    return cards[:10]


def analyze_best_matching_audience_segments(
    client_profile: Dict[str, Any],
    matched_statistics: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Rank client target audiences based on how many matched statistics support them.
    """
    target_audiences = client_profile.get("target_audiences", []) or []
    normalized_targets = {str(a).strip().lower(): str(a).strip() for a in target_audiences if str(a).strip()}

    segment_map: Dict[str, Dict[str, Any]] = {}

    for statistic in matched_statistics:
        matched_audiences = statistic.get("matched_tags", {}).get("audience", []) or []

        for audience in matched_audiences:
            key = str(audience).strip().lower()
            label = normalized_targets.get(key, str(audience).strip())

            if not label:
                continue

            if key not in segment_map:
                segment_map[key] = {
                    "audience_segment": label,
                    "matched_statistics_count": 0,
                    "total_score": 0,
                    "top_statistics": [],
                    "behavior_types": set(),
                    "sources": [],
                }

            segment_map[key]["matched_statistics_count"] += 1
            segment_map[key]["total_score"] += int(statistic.get("statistic_score", 0))
            segment_map[key]["behavior_types"].add(statistic.get("behavior_type", "Audience Behavior"))

            if len(segment_map[key]["top_statistics"]) < 3:
                segment_map[key]["top_statistics"].append(statistic.get("stat", ""))

            source_text = _source_text(statistic.get("source", {}))
            if source_text and source_text not in segment_map[key]["sources"]:
                segment_map[key]["sources"].append(source_text)

    ranked_segments = []

    for item in segment_map.values():
        count = item["matched_statistics_count"]
        avg_score = int(item["total_score"] / count) if count else 0
        ranked_segments.append({
            "audience_segment": item["audience_segment"],
            "matched_statistics_count": count,
            "average_relevance_score": avg_score,
            "priority_label": "High priority" if count >= 3 or avg_score >= 60 else "Medium priority",
            "behavior_types": sorted(item["behavior_types"]),
            "top_statistics": item["top_statistics"],
            "sources": item["sources"][:3],
        })

    return sorted(
        ranked_segments,
        key=lambda item: (item["matched_statistics_count"], item["average_relevance_score"]),
        reverse=True,
    )


def generate_content_angles(
    client_profile: Dict[str, Any],
    matched_statistics: List[Dict[str, Any]],
    matches: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Generate content angles based on client products, destination, audience needs and matched statistics.
    """
    client_name = client_profile.get("client_name", "το brand")
    destination = client_profile.get("main_destination", "")
    products = client_profile.get("products_services", []) or []
    audience_needs = normalize_values(client_profile.get("audience_needs", []))
    target_audiences = client_profile.get("target_audiences", []) or []

    angles: List[Dict[str, Any]] = []

    def add_angle(title: str, format_type: str, rationale_keywords: List[str]):
        stat = _first_relevant_statistic(matched_statistics, rationale_keywords)
        source = stat.get("source", {}) if stat else {}

        angles.append({
            "angle": title,
            "recommended_format": format_type,
            "why_it_works": (
                stat.get("what_this_shows", "")
                if stat
                else "Το angle προκύπτει από το προφίλ του client και τις υπηρεσίες που προσφέρει."
            ),
            "supporting_statistic": stat.get("stat", "") if stat else "",
            "source": source,
            "source_text": _source_text(source) if source else "—",
        })

    if "αυθεντικές εμπειρίες" in audience_needs or "τοπική καθοδήγηση" in audience_needs:
        add_angle(
            f"How to experience {destination or 'the destination'} like a local",
            "Blog / carousel / short-form video",
            ["authentic", "local", "sustainability", "audience behavior", "αυθεν"],
        )

    if any("food" in str(product).lower() for product in products) or "γαστρονομικές εμπειρίες" in audience_needs:
        add_angle(
            f"Why food experiences are a stronger way to discover {destination or 'a destination'}",
            "Blog / social carousel / PR angle",
            ["food", "gastronomy", "local", "travel behavior"],
        )

    if any("private" in str(product).lower() for product in products):
        add_angle(
            "Why private experiences appeal to travelers looking for flexibility and personalization",
            "Landing page section / paid ad angle / blog",
            ["private", "custom", "premium", "travel behavior"],
        )

    if any(str(a).lower() in {"gen z", "millennials"} for a in target_audiences):
        add_angle(
            "What younger travelers look for before choosing an experience",
            "TikTok / Reels series / social carousel",
            ["gen z", "millennials", "digital", "social", "planning"],
        )

    if "ευκολία στην κράτηση" in audience_needs:
        add_angle(
            "What makes travelers feel ready to book",
            "Website content / FAQ / conversion-focused post",
            ["booking", "trust", "digital", "conversion"],
        )

    if not angles:
        add_angle(
            f"Why choose {client_name} for a more relevant travel experience",
            "Website section / social carousel / client presentation",
            ["travel behavior", "audience behavior", "market trends"],
        )

    return angles[:8]


def generate_30_60_90_day_plan(
    client_profile: Dict[str, Any],
    action_recommendations: Dict[str, List[str]],
    matched_statistics: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    """
    Generate a practical 30/60/90 day action plan from action recommendations.
    """
    social = action_recommendations.get("social_media_actions", [])
    web = action_recommendations.get("web_development_actions", [])
    digital = action_recommendations.get("digital_marketing_actions", [])

    plan_30 = []
    plan_60 = []
    plan_90 = []

    if web:
        plan_30.append(web[0])
    if social:
        plan_30.append(social[0])
    plan_30.append("Συγκέντρωση των πιο ισχυρών statistics/sources σε ένα internal brief για χρήση σε website, social και campaign planning.")

    if len(web) > 1:
        plan_60.append(web[1])
    if digital:
        plan_60.append(digital[0])
    if len(social) > 1:
        plan_60.append(social[1])
    plan_60.append("Δημιουργία πρώτων campaign/content tests με βάση τα strongest audience behavior findings.")

    if len(digital) > 1:
        plan_90.append(digital[1])
    if len(social) > 2:
        plan_90.append(social[2])
    plan_90.append("Αξιολόγηση αποτελεσμάτων και ανανέωση του audience intelligence report με νέα data, learnings και client feedback.")
    plan_90.append("Εμπλουτισμός της research database με νέα statistics για τα audience segments που εμφάνισαν τη μεγαλύτερη δυναμική.")

    return {
        "30_days": _unique_actions(plan_30, max_items=5),
        "60_days": _unique_actions(plan_60, max_items=5),
        "90_days": _unique_actions(plan_90, max_items=5),
    }

