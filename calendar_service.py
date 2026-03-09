"""
Google Calendar polling service.

Checks the target user's calendar for recently ended meetings,
filters out internal/excluded events, and creates Meeting records.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from config import Config
from database import Meeting, MeetingStatus

logger = logging.getLogger(__name__)


class CalendarService:
    """Polls Google Calendar and identifies meetings that need voice note prompts."""

    TOKEN_URL = "https://oauth2.googleapis.com/token"
    CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"

    def __init__(self, config: Config):
        self.config = config
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    async def _get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        now = datetime.now(timezone.utc)

        if self._access_token and self._token_expires_at and now < self._token_expires_at:
            return self._access_token

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "client_id": self.config.GOOGLE_CLIENT_ID,
                    "client_secret": self.config.GOOGLE_CLIENT_SECRET,
                    "refresh_token": self.config.GOOGLE_REFRESH_TOKEN,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            data = response.json()

        self._access_token = data["access_token"]
        # Expire 5 minutes early to avoid edge cases
        expires_in = data.get("expires_in", 3600)
        self._token_expires_at = now + timedelta(seconds=expires_in - 300)

        logger.info("Refreshed Google OAuth access token.")
        return self._access_token

    async def get_recent_meetings(
        self, lookback_minutes: int = 30
    ) -> list[dict]:
        """
        Fetch calendar events that ended within the last `lookback_minutes`.

        Returns a list of event dicts with parsed attendee info.
        """
        token = await self._get_access_token()
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(minutes=lookback_minutes)

        params = {
            "timeMin": window_start.isoformat(),
            "timeMax": now.isoformat(),
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 50,
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.CALENDAR_API_BASE}/calendars/{self.config.GOOGLE_CALENDAR_ID}/events",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            response.raise_for_status()
            data = response.json()

        events = data.get("items", [])
        parsed = []

        for event in events:
            parsed_event = self._parse_event(event)
            if parsed_event:
                parsed.append(parsed_event)

        logger.info(f"Found {len(parsed)} calendar events in the last {lookback_minutes} minutes.")
        return parsed

    def _parse_event(self, event: dict) -> Optional[dict]:
        """Parse a Google Calendar event into our internal format."""
        # Skip all-day events (no dateTime, only date)
        start_raw = event.get("start", {})
        end_raw = event.get("end", {})

        if "dateTime" not in start_raw or "dateTime" not in end_raw:
            return None

        # Skip cancelled events
        if event.get("status") == "cancelled":
            return None

        # Parse attendees
        attendees = event.get("attendees", [])
        attendee_names = []
        attendee_emails = []

        for att in attendees:
            email = att.get("email", "")
            display_name = att.get("displayName", email.split("@")[0])

            # Skip the calendar owner (resource calendars, self)
            if att.get("self", False):
                continue
            # Skip resource rooms
            if att.get("resource", False):
                continue

            attendee_names.append(display_name)
            attendee_emails.append(email)

        return {
            "calendar_event_id": event["id"],
            "title": event.get("summary", "Untitled Meeting"),
            "start_time": datetime.fromisoformat(start_raw["dateTime"]),
            "end_time": datetime.fromisoformat(end_raw["dateTime"]),
            "attendee_names": attendee_names,
            "attendee_emails": attendee_emails,
            "description": event.get("description", ""),
            "organizer_email": event.get("organizer", {}).get("email", ""),
        }

    def should_prompt(self, event: dict) -> bool:
        """
        Determine if this meeting should trigger a voice note prompt.

        Filters:
        1. Must have ended (end_time < now)
        2. Must not be an all-internal meeting
        3. Must not match excluded email addresses
        4. Must not match excluded title keywords
        5. Must have at least one attendee besides the user
        """
        now = datetime.now(timezone.utc)

        # Must have ended
        end_time = event["end_time"]
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)
        if end_time > now:
            return False

        # Must have attendees
        if not event["attendee_emails"]:
            return False

        # Check excluded title keywords (case-insensitive)
        title_lower = event["title"].lower()
        for keyword in self.config.EXCLUDED_TITLE_KEYWORDS:
            if keyword.lower() in title_lower:
                logger.debug(f"Skipping '{event['title']}': matched excluded keyword '{keyword}'")
                return False

        # Check if ALL attendees are internal
        external_found = False
        for email in event["attendee_emails"]:
            email_lower = email.lower()

            # Check excluded emails list
            if email_lower in [e.lower() for e in self.config.EXCLUDED_EMAILS]:
                continue

            # Check if external
            if not email_lower.endswith(f"@{self.config.INTERNAL_DOMAIN}"):
                external_found = True
                break

        if not external_found:
            logger.debug(f"Skipping '{event['title']}': all attendees are internal or excluded")
            return False

        return True

    def has_ended_recently(self, event: dict, delay_minutes: int) -> bool:
        """
        Check if the meeting ended at least `delay_minutes` ago
        (so we don't prompt Greg while he's still wrapping up).
        """
        now = datetime.now(timezone.utc)
        end_time = event["end_time"]
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)

        time_since_end = now - end_time
        return time_since_end >= timedelta(minutes=delay_minutes)

    def event_to_meeting_record(self, event: dict) -> Meeting:
        """Convert a parsed calendar event dict into a Meeting database record."""
        return Meeting(
            calendar_event_id=event["calendar_event_id"],
            title=event["title"],
            start_time=event["start_time"],
            end_time=event["end_time"],
            attendee_names=", ".join(event["attendee_names"]),
            attendee_emails=", ".join(event["attendee_emails"]),
            description=event.get("description", ""),
            organizer_email=event.get("organizer_email", ""),
            status=MeetingStatus.DETECTED,
        )
