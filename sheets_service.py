"""
Google Sheets logging service.

Appends a row to a master Google Sheet for every processed voice note,
creating a searchable running record of meeting intelligence.
"""

import json
import logging
from datetime import datetime, timezone

import httpx

from config import Config
from database import Meeting

logger = logging.getLogger(__name__)

SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"

# Column headers for the master log sheet
SHEET_HEADERS = [
    "Date",
    "Time",
    "Meeting Title",
    "External Attendees",
    "Attendee Emails",
    "Summary",
    "Action Items",
    "Follow-Ups",
    "Proposed Tags",
    "Keywords",
    "Relationship Signals",
    "Contact Note",
    "Processed At",
]


async def _get_access_token(config: Config) -> str:
    """Get a fresh Google OAuth access token using the refresh token."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": config.GOOGLE_CLIENT_ID,
                "client_secret": config.GOOGLE_CLIENT_SECRET,
                "refresh_token": config.GOOGLE_REFRESH_TOKEN,
                "grant_type": "refresh_token",
            },
        )
        response.raise_for_status()
        return response.json()["access_token"]


async def ensure_headers(config: Config) -> None:
    """
    Check if the sheet has headers in row 1. If not, add them.
    This is idempotent and safe to call on every app startup.
    """
    if not config.GOOGLE_SHEETS_SPREADSHEET_ID:
        logger.warning("Google Sheets spreadsheet ID not configured, skipping.")
        return

    token = await _get_access_token(config)

    # Read row 1 to check for existing headers
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{SHEETS_API_BASE}/{config.GOOGLE_SHEETS_SPREADSHEET_ID}/values/Sheet1!A1:M1",
            headers={"Authorization": f"Bearer {token}"},
        )

    if response.status_code == 200:
        data = response.json()
        existing_values = data.get("values", [])
        if existing_values and len(existing_values[0]) > 0:
            logger.info("Sheet headers already exist.")
            return

    # Write headers
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.put(
            f"{SHEETS_API_BASE}/{config.GOOGLE_SHEETS_SPREADSHEET_ID}/values/Sheet1!A1:M1",
            headers={"Authorization": f"Bearer {token}"},
            params={"valueInputOption": "RAW"},
            json={"values": [SHEET_HEADERS]},
        )
        if response.status_code == 200:
            logger.info("Sheet headers written successfully.")
        else:
            logger.error(f"Failed to write sheet headers: {response.status_code}")


async def log_to_sheet(
    meeting: Meeting, processed: dict, config: Config
) -> bool:
    """
    Append a row to the master Google Sheet with processed meeting data.

    Returns True on success.
    """
    if not config.GOOGLE_SHEETS_SPREADSHEET_ID:
        logger.warning("Google Sheets spreadsheet ID not configured, skipping log.")
        return False

    token = await _get_access_token(config)

    # Build external attendee info
    names = [n.strip() for n in meeting.attendee_names.split(",") if n.strip()]
    emails = [e.strip() for e in meeting.attendee_emails.split(",") if e.strip()]
    external_names = []
    external_emails = []
    for i, email in enumerate(emails):
        if not email.endswith(f"@{config.INTERNAL_DOMAIN}"):
            name = names[i] if i < len(names) else email.split("@")[0]
            external_names.append(name)
            external_emails.append(email)

    # Format action items as readable text
    actions = processed.get("action_items", [])
    actions_text = "; ".join(
        f"[{a.get('owner', '?')}] {a.get('task', '')} ({a.get('urgency', '')})"
        for a in actions
    )

    # Format follow-ups
    follow_ups = processed.get("follow_ups", [])
    followups_text = "; ".join(
        f"{f.get('with_whom', '?')}: {f.get('description', '')} ({f.get('timeframe', '')})"
        for f in follow_ups
    )

    # Format proposed tags
    tags = processed.get("proposed_tags", [])
    tags_text = "; ".join(
        f"{t.get('field', '')}: {t.get('value', '')} [{t.get('confidence', '')}]"
        for t in tags
    )

    # Format relationship signals
    signals = processed.get("relationship_signals", [])
    signals_text = "; ".join(
        f"{s.get('signal', '')} ({s.get('contacts_involved', '')})"
        for s in signals
    )

    # Format keywords
    keywords = processed.get("keywords", [])
    keywords_text = ", ".join(keywords)

    row = [
        meeting.start_time.strftime("%Y-%m-%d"),
        meeting.start_time.strftime("%-I:%M %p"),
        meeting.title,
        ", ".join(external_names),
        ", ".join(external_emails),
        processed.get("summary", ""),
        actions_text,
        followups_text,
        tags_text,
        keywords_text,
        signals_text,
        processed.get("contact_note", ""),
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    ]

    # Append row to sheet
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{SHEETS_API_BASE}/{config.GOOGLE_SHEETS_SPREADSHEET_ID}/values/Sheet1!A:M:append",
            headers={"Authorization": f"Bearer {token}"},
            params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
            json={"values": [row]},
        )

        if response.status_code == 200:
            logger.info(f"Logged meeting '{meeting.title}' to Google Sheet.")
            return True
        else:
            logger.error(
                f"Failed to log to sheet: {response.status_code} - {response.text}"
            )
            return False
