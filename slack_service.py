"""
Slack messaging service using incoming webhooks.

Sends three types of messages:
1. Prompt to Greg/Daniel after a meeting ends (with recording link)
2. Processed results to Daniel (summaries + tag proposals)
3. Action items and follow-ups to Justine
"""

import json
import logging
from datetime import datetime

import httpx

from config import Config
from database import Meeting

logger = logging.getLogger(__name__)


async def _send_webhook(webhook_url: str, payload: dict) -> bool:
    """Send a message to a Slack incoming webhook. Returns True on success."""
    if not webhook_url:
        logger.warning("Slack webhook URL not configured, skipping message.")
        return False

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(webhook_url, json=payload)

        if response.status_code != 200:
            logger.error(
                f"Slack webhook error: {response.status_code} - {response.text}"
            )
            return False

    return True


async def send_recording_prompt(meeting: Meeting, config: Config) -> bool:
    """
    Send Greg/Daniel a Slack message prompting them to record a voice note.

    The message includes meeting context and a link to the recording page.
    """
    # Build attendee display string
    names = [n.strip() for n in meeting.attendee_names.split(",") if n.strip()]
    emails = [e.strip() for e in meeting.attendee_emails.split(",") if e.strip()]

    # Show external attendees prominently
    external_display = []
    for i, email in enumerate(emails):
        if not email.endswith(f"@{config.INTERNAL_DOMAIN}"):
            name = names[i] if i < len(names) else email.split("@")[0]
            external_display.append(name)

    attendee_str = ", ".join(external_display) if external_display else "Unknown"

    # Recording page URL
    record_url = f"{config.APP_BASE_URL}/record/{meeting.id}"

    # Format meeting time
    time_str = meeting.end_time.strftime("%-I:%M %p")

    payload = {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":microphone: *Meeting just ended at {time_str}*",
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*With:*\n{attendee_str}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Meeting:*\n{meeting.title}",
                    },
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":red_circle: *<{record_url}|Record Voice Note>*",
                },
            },
        ],
    }

    success = await _send_webhook(config.SLACK_WEBHOOK_GREG_PROMPT, payload)
    if success:
        logger.info(f"Sent recording prompt for meeting '{meeting.title}'")
    return success


async def send_batch_reminder(
    meetings: list[Meeting], config: Config
) -> bool:
    """
    Send an end-of-day reminder with all unrecorded meetings.
    """
    if not meetings:
        return True

    meeting_lines = []
    for m in meetings:
        names = [n.strip() for n in m.attendee_names.split(",") if n.strip()]
        emails = [e.strip() for e in m.attendee_emails.split(",") if e.strip()]
        external = []
        for i, email in enumerate(emails):
            if not email.endswith(f"@{config.INTERNAL_DOMAIN}"):
                name = names[i] if i < len(names) else email
                external.append(name)

        attendee_str = ", ".join(external) if external else "Unknown"
        record_url = f"{config.APP_BASE_URL}/record/{m.id}"
        time_str = m.end_time.strftime("%-I:%M %p")
        meeting_lines.append(
            f"• *{attendee_str}* - {m.title} ({time_str}) - <{record_url}|Record>"
        )

    meetings_text = "\n".join(meeting_lines)

    payload = {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":bell: *You have {len(meetings)} meeting(s) from today without notes:*",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": meetings_text,
                },
            },
        ],
    }

    success = await _send_webhook(config.SLACK_WEBHOOK_GREG_PROMPT, payload)
    if success:
        logger.info(f"Sent batch reminder for {len(meetings)} meetings")
    return success


async def send_combined_output(
    meeting: Meeting, processed: dict, config: Config
) -> bool:
    """
    Send all processed results to a single Slack channel:
    summary, action items, follow-ups, proposed tags, keywords,
    relationship signals, and CRM note.
    """
    # Build attendee display
    names = [n.strip() for n in meeting.attendee_names.split(",") if n.strip()]
    emails = [e.strip() for e in meeting.attendee_emails.split(",") if e.strip()]
    external = []
    for i, email in enumerate(emails):
        if not email.endswith(f"@{config.INTERNAL_DOMAIN}"):
            name = names[i] if i < len(names) else email
            external.append(name)
    attendee_str = ", ".join(external)

    # Summary
    summary = processed.get("summary", "No summary available.")

    # Action items
    actions = processed.get("action_items", [])
    action_lines = []
    for a in actions:
        urgency_emoji = {
            "this_week": ":rotating_light:",
            "next_two_weeks": ":calendar:",
            "this_month": ":hourglass_flowing_sand:",
            "no_rush": ":turtle:",
        }.get(a.get("urgency", "no_rush"), ":clipboard:")
        action_lines.append(
            f"{urgency_emoji} *{a.get('owner', 'TBD')}:* {a.get('task', '')} — _{a.get('context', '')}_"
        )
    actions_text = "\n".join(action_lines) if action_lines else "_No action items._"

    # Follow-ups
    follow_ups = processed.get("follow_ups", [])
    followup_lines = []
    for f in follow_ups:
        followup_lines.append(
            f":date: *{f.get('with_whom', '')}* — {f.get('description', '')} ({f.get('timeframe', 'TBD')}) — _{f.get('purpose', '')}_"
        )
    followups_text = "\n".join(followup_lines) if followup_lines else "_No follow-ups needed._"

    # Proposed tags
    tags = processed.get("proposed_tags", [])
    if tags:
        tag_lines = []
        for tag in tags:
            confidence_emoji = {"high": ":large_green_circle:", "medium": ":large_yellow_circle:", "low": ":red_circle:"}.get(
                tag.get("confidence", "low"), ":white_circle:"
            )
            tag_lines.append(
                f"{confidence_emoji} *{tag.get('field', '')}:* {tag.get('value', '')} — _{tag.get('reasoning', '')}_"
            )
        tags_text = "\n".join(tag_lines)
    else:
        tags_text = "_No tags proposed from this note._"

    # Keywords
    keywords = processed.get("keywords", [])
    keywords_text = ", ".join(keywords) if keywords else "_No keywords identified._"

    # Relationship signals
    signals = processed.get("relationship_signals", [])
    signals_text = ""
    if signals:
        signal_lines = [
            f":link: {s.get('signal', '')} ({s.get('contacts_involved', '')})"
            for s in signals
        ]
        signals_text = "\n".join(signal_lines)

    # Contact note
    contact_note = processed.get("contact_note", "")

    # Build blocks
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Voice Note Processed: {attendee_str}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Meeting:* {meeting.title}\n*Summary:* {summary}",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Action Items:*\n{actions_text}",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Follow-Up Meetings to Schedule:*\n{followups_text}",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Proposed Affinity Tags:*\n{tags_text}",
            },
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Keywords:* {keywords_text}",
            },
        },
    ]

    if signals_text:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Relationship Signals:*\n{signals_text}",
                },
            }
        )

    if contact_note:
        blocks.append({"type": "divider"})
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*CRM Note (copy to Affinity):*\n{contact_note}",
                },
            }
        )

    payload = {"blocks": blocks}
    success = await _send_webhook(config.SLACK_WEBHOOK_DANIEL_OUTPUT, payload)
    if success:
        logger.info(f"Sent combined output for '{meeting.title}'")
    return success
