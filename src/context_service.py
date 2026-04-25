import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from src.config import (
    SUPABASE_CONSULTATION_TABLE,
    SUPABASE_FOODS_TABLE,
    SUPABASE_PROFILE_TABLE,
    SUPABASE_QUESTION_TABLE,
    SUPABASE_QUIZ_SESSION_TABLE,
    SUPABASE_RESPONSE_TABLE,
    SUPABASE_RESULT_TABLE,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
    SUPABASE_USER_ACTIVITY_CREATED_AT_COLUMN,
    SUPABASE_USER_ACTIVITY_TABLE,
    SUPABASE_OPTION_TABLE,
)


def _to_iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, str):
        try:
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized).astimezone(timezone.utc).isoformat()
        except ValueError:
            return value
    return value


def _normalize_value(value: Any) -> Any:
    if isinstance(value, str):
        if value.isdigit():
            return int(value)
        try:
            return float(value)
        except ValueError:
            return _to_iso(value)
    if isinstance(value, dict):
        return {k: _normalize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_value(v) for v in value]
    return value


def _normalize_key(key: str) -> str:
    sanitized = key.strip()
    sanitized = sanitized.replace("µ", "micro")
    sanitized = sanitized.replace("%", "pct")
    sanitized = re.sub(r"[^0-9a-zA-Z]+", "_", sanitized)
    return sanitized.strip("_").lower()


def _normalize_record(record: Any) -> Any:
    if isinstance(record, dict):
        return {_normalize_key(k): _normalize_record(v) for k, v in record.items()}
    if isinstance(record, list):
        return [_normalize_record(v) for v in record]
    return _normalize_value(record)


def _parse_quantity(quantity: Any) -> float:
    if quantity is None:
        return 1.0
    if isinstance(quantity, (int, float)):
        return float(quantity)
    if isinstance(quantity, str):
        try:
            return float(quantity)
        except ValueError:
            digits = re.findall(r"\d+\.?\d*", quantity)
            if digits:
                return float(digits[0])
    return 1.0


def _scale_nutrition_by_quantity(food_record: Dict[str, Any], quantity: Any) -> Dict[str, Any]:
    factor = _parse_quantity(quantity)
    scaled = {}
    for key, value in food_record.items():
        if isinstance(value, (int, float)) and key not in {"id", "user_id", "food_id", "quantity"}:
            scaled[key] = round(value * factor, 3)
        else:
            scaled[key] = value
    scaled["quantity"] = quantity
    scaled["quantity_factor"] = factor
    return scaled


def _build_daily_food_summary(food_logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    totals: Dict[str, float] = {}
    logs_by_date: Dict[str, int] = {}
    daily_summary: Dict[str, Dict[str, Any]] = {}

    for log in food_logs:
        consumed_at = log.get("consumed_at") or log.get("created_at")
        date_key = str(consumed_at).split("T")[0] if consumed_at else "unknown"
        daily_summary.setdefault(date_key, {"date": date_key, "meals": 0, "total_nutrition": {}, "entries": 0})
        daily_summary[date_key]["entries"] += 1
        daily_summary[date_key]["meals"] += 1

        food_info = log.get("food") or log.get(_normalize_key(SUPABASE_FOODS_TABLE)) or log.get("foods")
        if isinstance(food_info, dict):
            for field, value in food_info.items():
                if isinstance(value, (int, float)):
                    daily_summary[date_key]["total_nutrition"][field] = (
                        daily_summary[date_key]["total_nutrition"].get(field, 0.0) + float(value)
                    )

    return {
        "count": len(food_logs),
        "daily_totals": list(daily_summary.values()),
        "date_keys": list(daily_summary.keys()),
    }


# def _dict_to_text(record: Dict[str, Any], indent: int = 0) -> str:
#     lines: List[str] = []
#     prefix = "" if indent == 0 else " " * indent
#     for key, value in sorted(record.items()):
#         if isinstance(value, dict):
#             lines.append(f"{prefix}{key}:")
#             lines.append(_dict_to_text(value, indent=indent + 2))
#         elif isinstance(value, list):
#             if all(isinstance(item, dict) for item in value):
#                 lines.append(f"{prefix}{key}:")
#                 for item in value:
#                     lines.append(_dict_to_text(item, indent=indent + 2))
#             else:
#                 lines.append(f"{prefix}{key}: {json.dumps(value, default=str)}")
#         else:
#             lines.append(f"{prefix}{key}: {value}")
#     return "\n".join(lines)
def _dict_to_text(record: Any, indent: int = 0) -> str:
    lines: List[str] = []
    prefix = "" if indent == 0 else " " * indent

    # ✅ HANDLE LIST
    if isinstance(record, list):
        for item in record:
            if isinstance(item, dict):
                lines.append(_dict_to_text(item, indent=indent))
            else:
                lines.append(f"{prefix}{item}")
        return "\n".join(lines)

    # ✅ HANDLE DICT
    if isinstance(record, dict):
        for key, value in sorted(record.items()):
            if isinstance(value, dict):
                lines.append(f"{prefix}{key}:")
                lines.append(_dict_to_text(value, indent=indent + 2))
            elif isinstance(value, list):
                lines.append(f"{prefix}{key}:")
                lines.append(_dict_to_text(value, indent=indent + 2))
            else:
                lines.append(f"{prefix}{key}: {value}")
        return "\n".join(lines)

    # ✅ fallback
    return f"{prefix}{record}"


def _supabase_headers(token: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# def _supabase_get(
#     path: str,
#     params: Optional[Dict[str, str]] = None,
# ) -> Any:
#     url = f"{SUPABASE_URL}/rest/v1/{path}"
#     headers = _supabase_headers()
#     with httpx.Client(timeout=15.0) as client:
#         response = client.get(url, params=params, headers=headers)
#     response.raise_for_status()
#     return response.json()

def _supabase_get(
    path: str,
    params: Optional[Dict[str, str]] = None,
) -> Any:
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    headers = _supabase_headers()

    with httpx.Client(timeout=15.0) as client:
        response = client.get(url, params=params, headers=headers)

    # ✅ DEBUG (very useful)
    print("\n--- SUPABASE DEBUG ---")
    print("URL:", url)
    print("PARAMS:", params)
    print("STATUS:", response.status_code)
    print("RESPONSE:", response.text)
    print("----------------------\n")

    response.raise_for_status()
    return response.json()

# def _fetch_table(
#     table: str,
#     select: str = "*",
#     filters: Optional[Dict[str, Any]] = None,
#     order: Optional[str] = None,
# ) -> List[Dict[str, Any]]:
#     params: Dict[str, str] = {"select": select}
#     if filters:
#         for key, value in filters.items():
#             if key in {"eq", "neq", "lt", "lte", "gt", "gte", "like", "ilike", "in"}:
#                 if isinstance(value, str) and "." in value:
#                     column, filter_value = value.split(".", 1)
#                     params[column] = f"{key}.{filter_value}"
#                     continue
#                 if isinstance(value, (list, tuple)):
#                     params[key] = f"({','.join(str(item) for item in value)})"
#                     continue
#             params[key] = str(value)
#     if order:
#         params["order"] = order

#     data = _supabase_get(table, params=params)
#     if isinstance(data, list):
#         return [_normalize_value(_to_iso(item)) for item in data]
#     return [_normalize_value(_to_iso(data))]

def _fetch_table(
    table: str,
    select: str = "*",
    filters: Optional[Dict[str, str]] = None,
    order: Optional[str] = None,
) -> List[Dict[str, Any]]:
    params: Dict[str, str] = {"select": select}

    # ✅ Direct mapping (FIXED)
    if filters:
        params.update(filters)

    if order:
        params["order"] = order

    data = _supabase_get(table, params=params)

    if isinstance(data, list):
        return [_normalize_record(item) for item in data]
    return [_normalize_record(data)]


def fetch_user_context(user_id: str) -> Dict[str, Any]:
    # profile_rows = _fetch_table(
    #     SUPABASE_PROFILE_TABLE,
    #     select="*",
    #     filters={"eq": f"id.{user_id}"},
    # )
    profile_rows = _fetch_table(
        SUPABASE_PROFILE_TABLE,
        select="*",
        filters={"id": f"eq.{user_id}"},   # ✅ FIXED
    )
    
    profile = _normalize_record(profile_rows[0]) if profile_rows else {}

    # quiz_sessions = _fetch_table(
    #     SUPABASE_QUIZ_SESSION_TABLE,
    #     select="*",
    #     filters={"eq": f"user_id.{user_id}"},
    #     order="started_at.desc",
    # )
    quiz_sessions = _fetch_table(
        SUPABASE_QUIZ_SESSION_TABLE,
        select="*",
        filters={"user_id": f"eq.{user_id}"},   # ✅ FIXED
        order="started_at.desc",
    )

    quiz_sessions = [_normalize_record(session) for session in quiz_sessions]

    # assessment_results = _fetch_table(
    #     SUPABASE_RESULT_TABLE,
    #     select="*",
    #     filters={"eq": f"user_id.{user_id}"},
    #     order="created_at.desc",
    # )

    assessment_results = _fetch_table(
        SUPABASE_RESULT_TABLE,
        select="*",
        filters={"user_id": f"eq.{user_id}"},   # ✅ FIXED
        order="created_at.desc",
    )
    assessment_results = [_normalize_record(result) for result in assessment_results]

    # assessment_responses = _fetch_table(
    #     SUPABASE_RESPONSE_TABLE,
    #     select="*",
    #     filters={"eq": f"user_id.{user_id}"},
    #     order="created_at.desc",
    # )
    assessment_responses = _fetch_table(
        SUPABASE_RESPONSE_TABLE,
        select="*",
        filters={"user_id": f"eq.{user_id}"},   # ✅ FIXED
        order="created_at.desc",
    )
    
    assessment_responses = [_normalize_record(response) for response in assessment_responses]

    question_ids = {item.get("question_id") for item in assessment_responses if item.get("question_id")}
    option_ids = {item.get("option_id") for item in assessment_responses if item.get("option_id")}

    # questions = []
    # if question_ids:
    #     questions = _fetch_table(
    #         SUPABASE_QUESTION_TABLE,
    #         select="*",
    #         filters={"in": f"id.({','.join(question_ids)})"},
    #     )

    questions = []
    if question_ids:
        questions = _fetch_table(
            SUPABASE_QUESTION_TABLE,
            select="*",
            filters={"id": f"in.({','.join(question_ids)})"},   # ✅ FIXED
        )
    questions_by_id = {item.get("id"): _normalize_record(item) for item in questions}

    # options = []
    # if option_ids:
    #     options = _fetch_table(
    #         SUPABASE_OPTION_TABLE,
    #         select="*",
    #         filters={"in": f"id.({','.join(option_ids)})"},
    #     )
    options = []
    if option_ids:
        options = _fetch_table(
            SUPABASE_OPTION_TABLE ,
            select="*",
            filters={"id": f"in.({','.join(option_ids)})"},   # ✅ FIXED
    )
    options_by_id = {item.get("id"): _normalize_record(item) for item in options}

    quiz_sessions_by_id = {session.get("id"): session for session in quiz_sessions}

    normalized_assessment_responses: List[Dict[str, Any]] = []
    for response in assessment_responses:
        merged_response = dict(response)
        merged_response["question"] = questions_by_id.get(response.get("question_id"), {})
        merged_response["option"] = options_by_id.get(response.get("option_id"), {})
        merged_response["session"] = quiz_sessions_by_id.get(response.get("session_id"), {})
        normalized_assessment_responses.append(merged_response)

    # food_logs = _fetch_table(
    #     SUPABASE_USER_ACTIVITY_TABLE,
    #     select="*",
    #     filters={"eq": f"user_id.{user_id}"},
    #     order=f"{SUPABASE_USER_ACTIVITY_CREATED_AT_COLUMN}.desc",
    # )

    food_logs = _fetch_table(
        SUPABASE_USER_ACTIVITY_TABLE,
        select="*",
        filters={"user_id": f"eq.{user_id}"},   # ✅ FIXED
        order=f"{SUPABASE_USER_ACTIVITY_CREATED_AT_COLUMN}.desc",
    )
    normalized_food_logs: List[Dict[str, Any]] = []

    food_ids = {log.get("food_id") for log in food_logs if log.get("food_id")}
    # foods = []
    # if food_ids:
    #     foods = _fetch_table(
    #         SUPABASE_FOODS_TABLE,
    #         select="*",
    #         filters={"in": f"id.({','.join(food_ids)})"},
    #     )

    foods = []
    if food_ids:
        foods = _fetch_table(
            SUPABASE_FOODS_TABLE,
            select="*",
            filters={"id": f"in.({','.join(food_ids)})"},   # ✅ FIXED
        )
    foods_by_id = {item.get("id"): _normalize_record(item) for item in foods}

    for log in food_logs:
        normalized_log = _normalize_record(log)
        food_meta = foods_by_id.get(normalized_log.get("food_id"), {})
        if food_meta:
            normalized_log["food"] = food_meta
            normalized_log["scaled_food"] = _scale_nutrition_by_quantity(food_meta, normalized_log.get("quantity"))
        normalized_food_logs.append(normalized_log)

    # consultations = _fetch_table(
    #     SUPABASE_CONSULTATION_TABLE,
    #     select="*",
    #     filters={"eq": f"user_id.{user_id}"},
    #     order="appointment_date.desc",
    # )
    consultations = _fetch_table(
        SUPABASE_CONSULTATION_TABLE,
        select="*",
        filters={"user_id": f"eq.{user_id}"},   # ✅ FIXED
        order="appointment_date.desc",
    )
    consultations = [_normalize_record(item) for item in consultations]

    food_summary = _build_daily_food_summary(normalized_food_logs)
    artifacts = {
        "latest_assessment_pdf": _find_pdf_url(profile) or _find_pdf_url_list(assessment_responses)
    }

    return {
        "profile": profile,
        "assessment": {
            "latest": assessment_results[0] if assessment_results else {},
            "history": assessment_responses,
            "sessions": quiz_sessions,
        },
        "food": {
            "logs": normalized_food_logs,
            "summary": food_summary,
        },
        "consultations": consultations,
        "artifacts": artifacts,
        "metadata": {
            "user_id": user_id,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "sources": {
                "profile": bool(profile),
                "assessment": len(assessment_responses),
                "sessions": len(quiz_sessions),
                "food": len(normalized_food_logs),
                "consultations": len(consultations),
            },
            "version": "python-rag-supabase-1.0",
        },
    }


def _find_pdf_url(record: Dict[str, Any]) -> Optional[str]:
    for key, value in record.items():
        if isinstance(value, str) and value.lower().endswith(".pdf"):
            return value
    return None


def _find_pdf_url_list(records: List[Dict[str, Any]]) -> Optional[str]:
    for record in records:
        pdf_url = _find_pdf_url(record)
        if pdf_url:
            return pdf_url
    return None


def build_documents(context: Dict[str, Any]) -> List[Dict[str, Any]]:
    documents: List[Dict[str, Any]] = []
    user_id = context.get("metadata", {}).get("user_id", "unknown")

    food_summary = context.get("food", {}).get("summary", {})

    if food_summary:
        documents.append({
            "id": f"food-summary-{user_id}",
            "text": (
                f"Food summary:\n"
                f"Total logs: {food_summary.get('count')}\n"
                f"Days tracked: {len(food_summary.get('date_keys', []))}\n"
                f"Daily breakdown:\n{_dict_to_text(food_summary.get('daily_totals', []))}"
            ),
            "metadata": {
                "doc_type": "food_summary"
            }
        })

    profile = context.get("profile", {})
    if profile:
        documents.append(
            {
                "id": f"profile-{user_id}",
                "text": f"User profile:\n{_dict_to_text(profile)}",
                "metadata": {
                    "user_id": user_id,
                    "doc_type": "profile",
                    "source_table": SUPABASE_PROFILE_TABLE,
                    "source_id": profile.get("id", user_id),
                    "created_at": profile.get("created_at"),
                    "updated_at": profile.get("updated_at"),
                    "date_range": profile.get("created_at"),
                },
            }
        )

    assessment = context.get("assessment", {})
    latest_assessment = assessment.get("latest")
    if latest_assessment:
        documents.append(
            {
                "id": f"assessment-summary-{user_id}",
                "text": (
                    f"Latest assessment summary:\n"
                    f"Vata total: {latest_assessment.get('vata_total')}\n"
                    f"Pitta total: {latest_assessment.get('pitta_total')}\n"
                    f"Kapha total: {latest_assessment.get('kapha_total')}\n"
                    f"Dominant dosha: {latest_assessment.get('dominant_dosha')}\n"
                    f"Final assessment: {latest_assessment.get('is_final')}\n"
                    f"Created at: {latest_assessment.get('created_at')}"
                ),
                "metadata": {
                    "user_id": user_id,
                    "doc_type": "assessment_summary",
                    "source_table": SUPABASE_RESULT_TABLE,
                    "source_id": latest_assessment.get("id", "latest"),
                    "created_at": latest_assessment.get("created_at"),
                    "updated_at": latest_assessment.get("created_at"),
                    "date_range": latest_assessment.get("created_at"),
                },
            }
        )

    for idx, item in enumerate(assessment.get("history", []) or [], start=1):
        question = item.get("question") or {}
        option = item.get("option") or {}
        question_text = question.get("question_text") or item.get("question_text") or "Unknown question"
        option_text = option.get("option_text") or item.get("option_text") or "Unknown option"
        option_scores = (
            f"vata={option.get('vata_score')}, pitta={option.get('pitta_score')}, kapha={option.get('kapha_score')}"
            if option
            else "No option score available"
        )
        doc_id = item.get("id") or f"response-{idx}-{user_id}"
        documents.append(
            {
                "id": f"assessment-response-{doc_id}",
                "text": (
                    f"Assessment response:\n"
                    f"Question: {question_text}\n"
                    f"Selected option: {option_text}\n"
                    f"Option scores: {option_scores}\n"
                    f"Session ID: {item.get('session_id')}\n"
                    f"Responded at: {item.get('created_at')}"
                ),
                "metadata": {
                    "user_id": user_id,
                    "doc_type": "assessment_response",
                    "source_table": SUPABASE_RESPONSE_TABLE,
                    "source_id": doc_id,
                    "created_at": item.get("created_at"),
                    "updated_at": item.get("created_at"),
                    "date_range": item.get("created_at"),
                },
            }
        )

    for idx, log in enumerate(context.get("food", {}).get("logs", []) or [], start=1):
        log_id = log.get("id") or f"food-{idx}-{user_id}"
        food_text = _dict_to_text(log.get("food", {}) if isinstance(log.get("food"), dict) else log)
        documents.append(
            {
                "id": f"food-{log_id}",
                "text": f"Food log:\n{food_text}",
                "metadata": {
                    "user_id": user_id,
                    "doc_type": "food_log",
                    "source_table": SUPABASE_USER_ACTIVITY_TABLE,
                    "source_id": log_id,
                    "created_at": log.get(SUPABASE_USER_ACTIVITY_CREATED_AT_COLUMN) or log.get("created_at"),
                    "updated_at": log.get("updated_at") or log.get("created_at"),
                    "date_range": log.get(SUPABASE_USER_ACTIVITY_CREATED_AT_COLUMN) or log.get("consumed_at"),
                },
            }
        )

    # for idx, appointment in enumerate(context.get("consultations", []) or [], start=1):
    #     appointment_id = appointment.get("id") or f"consultation-{idx}-{user_id}"
    #     documents.append(
    #         {
    #             "id": f"consultation-{appointment_id}",
    #             "text": f"Consultation appointment:\n{_dict_to_text(appointment)}",
    #             "metadata": {
    #                 "user_id": user_id,
    #                 "doc_type": "consultation",
    #                 "source_table": SUPABASE_CONSULTATION_TABLE,
    #                 "source_id": appointment_id,
    #                 "created_at": appointment.get("created_at"),
    #                 "updated_at": appointment.get("updated_at"),
    #                 "date_range": appointment.get("appointment_date"),
    #             },
    #         }
    #     )
    for idx, appointment in enumerate(context.get("consultations", []) or [], start=1):
        appointment_id = appointment.get("id") or f"consultation-{idx}-{user_id}"

        documents.append({
            "id": f"consultation-{appointment_id}",
            "text": (
                f"Consultation appointment:\n"
                f"Doctor: {appointment.get('doctor_name')}\n"
                f"Clinic: {appointment.get('clinic_name')}\n"
                f"Date: {appointment.get('appointment_date')}\n"
                f"Time: {appointment.get('appointment_time')}\n"
                f"Type: {appointment.get('consultation_type')}\n"
                f"Location: {appointment.get('location')}\n"
                f"Notes: {appointment.get('notes')}"
            ),
            "metadata": {
                "user_id": user_id,
                "doc_type": "consultation",
                "source_table": SUPABASE_CONSULTATION_TABLE,
                "source_id": appointment_id,
                "created_at": appointment.get("created_at"),
                "date_range": appointment.get("appointment_date"),
            },
        })

    consultations = context.get("consultations", [])

    if consultations:
        documents.append({
            "id": f"consultations-summary-{user_id}",
            "text": (
                f"You have {len(consultations)} consultation appointments.\n\n"
                f"All appointments:\n"
                + "\n\n".join([
                    f"Appointment {i+1}: Doctor {c.get('doctor_name')} on {c.get('appointment_date')} at {c.get('appointment_time')}"
                    for i, c in enumerate(consultations)
                ])
            ),
            "metadata": {
                "user_id": user_id,
                "doc_type": "consultation_summary"
            }
        })

    latest_pdf = context.get("artifacts", {}).get("latest_assessment_pdf")
    if latest_pdf:
        documents.append(
            {
                "id": f"attachment-{user_id}",
                "text": f"Latest assessment PDF link: {latest_pdf}",
                "metadata": {
                    "user_id": user_id,
                    "doc_type": "artifact",
                    "source_table": "artifacts",
                    "source_id": latest_pdf,
                    "created_at": None,
                    "updated_at": None,
                    "date_range": None,
                },
            }
        )

    return documents
