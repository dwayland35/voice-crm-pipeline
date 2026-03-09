"""
AI processing engine using Claude API.

Takes a voice note transcript + meeting context and produces structured outputs:
- Summary
- Action items with owners
- Follow-up meeting suggestions
- Proposed Affinity CRM tags
- Relationship signals
- Contact note for CRM
"""

import json
import logging
from typing import Optional

import httpx

from config import Config
from database import Meeting

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """You are an AI assistant for Sideline Group, a growth equity firm focused on the leisure economy (active lifestyles, healthy lifestyles, and live events & experiences). Your job is to process voice note transcripts from the firm's founder after his meetings and extract structured, actionable information.

The firm backs culture-setting offline/physical-world brands. Key investment themes: endurance sports, wellness, music, live events, youth sports, college sports infrastructure.

You will receive:
1. A transcript of a 30-60 second voice note recorded after a meeting
2. Meeting metadata (title, attendees, time)

Your output must be a valid JSON object with exactly these fields:

{
  "summary": "2-3 sentence plain-English summary of the meeting's substance and outcome",
  "action_items": [
    {
      "task": "Specific task description",
      "owner": "Greg | Daniel | Justine | [Other name]",
      "urgency": "this_week | next_two_weeks | this_month | no_rush",
      "context": "Brief context for why this matters"
    }
  ],
  "follow_ups": [
    {
      "description": "What follow-up meeting or call to schedule",
      "with_whom": "Person/people name(s)",
      "timeframe": "Suggested timing (e.g., 'in 2 weeks', 'after they review materials')",
      "purpose": "What the follow-up should accomplish"
    }
  ],
  "proposed_tags": [
    {
      "field": "Tag field name (e.g., 'LP Likelihood', 'Check Size Range', 'Sector Interest')",
      "value": "Proposed value",
      "confidence": "high | medium | low",
      "reasoning": "Why this tag is appropriate based on what was said"
    }
  ],
  "relationship_signals": [
    {
      "signal": "Description of the relationship or connection mentioned",
      "contacts_involved": "Names of people/firms connected"
    }
  ],
  "contact_note": "A cleaned-up, professional version of the voice note content suitable for adding to a CRM contact record. Written in third person past tense."
}

Tag taxonomy to map against:

FOR POTENTIAL LPs / INVESTORS:
- LP Likelihood: High / Medium / Low / Passed
- Check Size Range: Free text (e.g., "$500K", "$1-2M")
- Fund Type: Family Office / Endowment / Foundation / HNW Individual / Fund of Funds / Institutional
- Sector Interest: Multi-select keywords mapping to Sideline's themes
- Relationship Warmth: Hot / Warm / Cool / Cold
- Referral Source: Contact name or channel

FOR INVESTOR PEERS / CO-INVESTORS:
- Check Size Range: Free text
- Sector Focus: Keywords
- Deal Preference: Lead / Co-Lead / Follow
- Co-Investment Interest: High / Medium / Low

FOR ALL CONTACTS:
- Contact Type: Potential LP / Investor Peer / Portfolio / Operator / Advisor / Service Provider
- Network Connections: Names of connected contacts/firms
- Key Topics Discussed: Keywords
- Introduction Path: How the relationship formed

Rules:
- Only propose tags you have evidence for in the transcript. Do not guess.
- For ambiguous names, use the meeting attendee info to determine the correct person.
- Action items should have clear owners. Default to "Justine" for scheduling tasks, "Daniel" for analytical/research tasks, and "Greg" for relationship/decision tasks.
- Keep the summary concise. The reader is busy.
- If the transcript is too vague to extract meaningful tags, say so in the reasoning and set confidence to "low".
- Output ONLY the JSON object, no markdown formatting, no code fences, no explanation before or after."""


async def process_voice_note(
    transcript: str,
    meeting: Meeting,
    config: Config,
) -> dict:
    """
    Send transcript + meeting context to Claude and get structured extraction.

    Args:
        transcript: The transcribed text from the voice note.
        meeting: The Meeting record with attendee and event metadata.
        config: Application configuration.

    Returns:
        Parsed JSON dict with structured outputs.
    """
    # Build the user message with meeting context
    attendee_info = ""
    names = [n.strip() for n in meeting.attendee_names.split(",") if n.strip()]
    emails = [e.strip() for e in meeting.attendee_emails.split(",") if e.strip()]
    for i, email in enumerate(emails):
        name = names[i] if i < len(names) else "Unknown"
        attendee_info += f"  - {name} ({email})\n"

    user_message = f"""Meeting context:
- Title: {meeting.title}
- Date/Time: {meeting.start_time.strftime('%B %d, %Y at %I:%M %p')} - {meeting.end_time.strftime('%I:%M %p')}
- Attendees:
{attendee_info}
- Event description: {meeting.description or 'None provided'}

Voice note transcript:
\"\"\"{transcript}\"\"\"

Extract the structured information and return as JSON."""

    logger.info(
        f"Sending transcript to Claude for processing ({len(transcript)} chars)"
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": config.ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 2000,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_message}],
            },
        )

        if response.status_code != 200:
            logger.error(
                f"Claude API error: {response.status_code} - {response.text}"
            )
            response.raise_for_status()

        data = response.json()

    # Extract text from response
    content_blocks = data.get("content", [])
    raw_text = ""
    for block in content_blocks:
        if block.get("type") == "text":
            raw_text += block.get("text", "")

    # Parse JSON from response, handling potential markdown fences
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse Claude response as JSON: {e}")
        logger.error(f"Raw response: {raw_text[:500]}")
        # Return a minimal valid structure so the pipeline doesn't break
        result = {
            "summary": f"[AI processing error - raw transcript]: {transcript[:500]}",
            "action_items": [],
            "follow_ups": [],
            "proposed_tags": [],
            "relationship_signals": [],
            "contact_note": transcript,
        }

    logger.info("Claude processing complete.")
    return result
