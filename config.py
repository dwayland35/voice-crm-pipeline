"""
Configuration management for Voice-to-CRM Pipeline.
All settings are loaded from environment variables.
"""

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    # --- Google OAuth & Calendar ---
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REFRESH_TOKEN: str = ""
    GOOGLE_CALENDAR_ID: str = "primary"  # "primary" uses the authenticated user's main calendar

    # --- Target user (whose calendar to watch) ---
    TARGET_USER_EMAIL: str = "daniel@sidelinegroup.co"
    TARGET_TIMEZONE: str = "America/New_York"

    # --- Internal domain for filtering ---
    INTERNAL_DOMAIN: str = "sidelinegroup.co"

    # --- Excluded email addresses (personal contacts, coach, etc.) ---
    # Comma-separated in the env var
    EXCLUDED_EMAILS: List[str] = field(default_factory=list)

    # --- Excluded calendar event title keywords ---
    EXCLUDED_TITLE_KEYWORDS: List[str] = field(
        default_factory=lambda: ["Personal", "Block", "Hold", "OOO", "Lunch", "Gym"]
    )

    # --- Deepgram ---
    DEEPGRAM_API_KEY: str = ""

    # --- Anthropic (Claude) ---
    ANTHROPIC_API_KEY: str = ""

    # --- Slack ---
    SLACK_WEBHOOK_GREG_PROMPT: str = ""  # Webhook for prompting Greg/Daniel to record
    SLACK_WEBHOOK_DANIEL_OUTPUT: str = ""  # Webhook for Daniel's tag proposals + summaries
    SLACK_WEBHOOK_JUSTINE_OUTPUT: str = ""  # Webhook for Justine's action items

    # --- Google Sheets ---
    GOOGLE_SHEETS_SPREADSHEET_ID: str = ""  # The ID from the Google Sheets URL

    # --- Application ---
    APP_BASE_URL: str = "https://your-app.railway.app"  # Set to your Railway URL after deploy
    POLL_INTERVAL_MINUTES: int = 3  # How often to check the calendar
    POST_MEETING_DELAY_MINUTES: int = 3  # How long after meeting ends to send prompt
    BATCH_REMINDER_HOUR: int = 18  # 6 PM for end-of-day batch reminder
    AUDIO_UPLOAD_DIR: str = "uploads/audio"

    # --- Database ---
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/voicecrm"

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        config = cls()

        # Load all string fields from env
        for field_name in [
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "GOOGLE_REFRESH_TOKEN",
            "GOOGLE_CALENDAR_ID",
            "TARGET_USER_EMAIL",
            "TARGET_TIMEZONE",
            "INTERNAL_DOMAIN",
            "DEEPGRAM_API_KEY",
            "ANTHROPIC_API_KEY",
            "SLACK_WEBHOOK_GREG_PROMPT",
            "SLACK_WEBHOOK_DANIEL_OUTPUT",
            "SLACK_WEBHOOK_JUSTINE_OUTPUT",
            "GOOGLE_SHEETS_SPREADSHEET_ID",
            "APP_BASE_URL",
            "AUDIO_UPLOAD_DIR",
            "DATABASE_URL",
        ]:
            env_val = os.getenv(field_name)
            if env_val is not None:
                setattr(config, field_name, env_val)

        # Load integer fields
        for field_name in [
            "POLL_INTERVAL_MINUTES",
            "POST_MEETING_DELAY_MINUTES",
            "BATCH_REMINDER_HOUR",
        ]:
            env_val = os.getenv(field_name)
            if env_val is not None:
                setattr(config, field_name, int(env_val))

        # Load comma-separated list fields
        excluded_emails = os.getenv("EXCLUDED_EMAILS", "")
        if excluded_emails:
            config.EXCLUDED_EMAILS = [
                e.strip() for e in excluded_emails.split(",") if e.strip()
            ]

        excluded_keywords = os.getenv("EXCLUDED_TITLE_KEYWORDS")
        if excluded_keywords:
            config.EXCLUDED_TITLE_KEYWORDS = [
                k.strip() for k in excluded_keywords.split(",") if k.strip()
            ]

        return config

    def validate(self) -> List[str]:
        """Check for missing required configuration. Returns list of missing field names."""
        required = [
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "GOOGLE_REFRESH_TOKEN",
            "DEEPGRAM_API_KEY",
            "ANTHROPIC_API_KEY",
            "SLACK_WEBHOOK_GREG_PROMPT",
            "DATABASE_URL",
        ]
        missing = []
        for field_name in required:
            val = getattr(self, field_name, "")
            if not val:
                missing.append(field_name)
        return missing
