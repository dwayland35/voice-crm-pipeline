"""
Voice-to-CRM Pipeline - Main Application

FastAPI backend that:
1. Polls Google Calendar for recently ended meetings
2. Sends Slack prompts with recording links
3. Receives audio uploads from the recording page
4. Transcribes, processes with Claude, and distributes outputs
"""

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from config import Config
from database import (
    Meeting,
    MeetingStatus,
    ProcessedResult,
    VoiceNote,
    create_db_engine,
    create_session_factory,
    init_db,
)
from calendar_service import CalendarService
from transcription import transcribe_audio
from ai_processor import process_voice_note
from slack_service import (
    send_batch_reminder,
    send_combined_output,
    send_recording_prompt,
)
from sheets_service import ensure_headers, log_to_sheet

# --- Logging setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# --- Global state ---
config: Config = None
engine = None
SessionFactory = None
calendar_service: CalendarService = None
scheduler: AsyncIOScheduler = None


# --- Lifecycle ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    global config, engine, SessionFactory, calendar_service, scheduler

    # Load configuration
    config = Config.from_env()
    missing = config.validate()
    if missing:
        logger.warning(f"Missing configuration: {', '.join(missing)}")
        logger.warning("Some features will be unavailable until these are set.")

    # Initialize database
    engine = create_db_engine(config.DATABASE_URL)
    init_db(engine)
    SessionFactory = create_session_factory(engine)
    logger.info("Database initialized.")

    # Create audio upload directory
    Path(config.AUDIO_UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

    # Initialize services
    calendar_service = CalendarService(config)

    # Ensure Google Sheet headers exist
    try:
        if config.GOOGLE_SHEETS_SPREADSHEET_ID:
            await ensure_headers(config)
    except Exception as e:
        logger.warning(f"Could not verify sheet headers: {e}")

    # Start scheduler
    scheduler = AsyncIOScheduler()

    # Calendar polling job - every 5 minutes on the clock (:00, :05, :10, etc.)
    scheduler.add_job(
        poll_calendar,
        CronTrigger(minute="*/5", timezone=config.TARGET_TIMEZONE),
        id="poll_calendar",
        name="Poll Google Calendar",
        replace_existing=True,
    )

    # End-of-day batch reminder
    scheduler.add_job(
        send_eod_reminder,
        CronTrigger(
            hour=config.BATCH_REMINDER_HOUR,
            minute=0,
            timezone=config.TARGET_TIMEZONE,
        ),
        id="eod_reminder",
        name="End-of-day batch reminder",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        f"Scheduler started: polling at :00, :05, :10 etc., "
        f"EOD reminder at {config.BATCH_REMINDER_HOUR}:00 {config.TARGET_TIMEZONE}"
    )

    yield

    # Shutdown
    scheduler.shutdown()
    engine.dispose()
    logger.info("Application shut down.")


app = FastAPI(
    title="Voice-to-CRM Pipeline",
    description="Post-meeting voice capture and AI processing for Sideline Group",
    lifespan=lifespan,
)


# =====================================================================
# Scheduled Jobs
# =====================================================================


async def poll_calendar():
    """
    Check Google Calendar for meetings that recently ended.
    For qualifying meetings, create a Meeting record and send a Slack prompt.
    """
    try:
        # Look back far enough to catch meetings we might have missed
        events = await calendar_service.get_recent_meetings(lookback_minutes=30)

        session = SessionFactory()
        try:
            new_prompts = 0
            for event in events:
                # Check if we should prompt for this meeting
                if not calendar_service.should_prompt(event):
                    continue

                # Check if meeting ended long enough ago (delay for wrap-up time)
                if not calendar_service.has_ended_recently(
                    event, config.POST_MEETING_DELAY_MINUTES
                ):
                    continue

                # Check if we've already tracked this event
                existing = (
                    session.query(Meeting)
                    .filter_by(calendar_event_id=event["calendar_event_id"])
                    .first()
                )
                if existing:
                    continue

                # Create meeting record
                meeting = calendar_service.event_to_meeting_record(event)
                session.add(meeting)
                session.flush()  # Get the ID for the recording URL

                # Send Slack prompt
                try:
                    success = await send_recording_prompt(meeting, config)
                    if success:
                        meeting.status = MeetingStatus.PROMPT_SENT
                        meeting.prompt_sent_at = datetime.now(timezone.utc)
                        new_prompts += 1
                except Exception as e:
                    logger.error(f"Failed to send Slack prompt: {e}")
                    # Keep the meeting record even if Slack fails

            session.commit()

            if new_prompts > 0:
                logger.info(f"Sent {new_prompts} new recording prompt(s).")

        except Exception as e:
            session.rollback()
            logger.error(f"Database error in poll_calendar: {e}")
            raise
        finally:
            session.close()

    except Exception as e:
        logger.error(f"Calendar polling error: {e}")


async def send_eod_reminder():
    """
    At end of day, find all meetings that were prompted but never received
    a voice note, and send one consolidated reminder.
    """
    try:
        session = SessionFactory()
        try:
            # Find meetings from today that are still awaiting notes
            today_start = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

            pending_meetings = (
                session.query(Meeting)
                .filter(
                    Meeting.status == MeetingStatus.PROMPT_SENT,
                    Meeting.end_time >= today_start,
                )
                .all()
            )

            if pending_meetings:
                success = await send_batch_reminder(pending_meetings, config)
                if success:
                    for m in pending_meetings:
                        m.status = MeetingStatus.BATCH_REMINDED
                        m.batch_reminded_at = datetime.now(timezone.utc)
                    session.commit()
            else:
                logger.info("No pending meetings for EOD reminder.")

        except Exception as e:
            session.rollback()
            logger.error(f"EOD reminder error: {e}")
        finally:
            session.close()

    except Exception as e:
        logger.error(f"EOD reminder error: {e}")


# =====================================================================
# Routes - Recording Page
# =====================================================================


@app.get("/record/{meeting_id}", response_class=HTMLResponse)
async def recording_page(meeting_id: int):
    """Serve the voice recording page for a specific meeting."""
    template_path = Path(__file__).parent / "templates" / "recorder.html"
    if not template_path.exists():
        raise HTTPException(status_code=500, detail="Recording template not found.")
    return HTMLResponse(content=template_path.read_text())


# =====================================================================
# Routes - API
# =====================================================================


@app.get("/api/meetings/{meeting_id}")
async def get_meeting(meeting_id: int):
    """Get meeting details for the recording page."""
    session = SessionFactory()
    try:
        meeting = session.query(Meeting).filter_by(id=meeting_id).first()
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found.")

        return {
            "id": meeting.id,
            "title": meeting.title,
            "start_time": meeting.start_time.isoformat(),
            "end_time": meeting.end_time.isoformat(),
            "attendee_names": meeting.attendee_names,
            "attendee_emails": meeting.attendee_emails,
            "description": meeting.description,
            "status": meeting.status,
        }
    finally:
        session.close()


@app.post("/api/meetings/{meeting_id}/upload")
async def upload_audio(meeting_id: int, audio: UploadFile = File(...)):
    """
    Receive an audio file upload from the recording page.
    Triggers the transcription → AI processing → distribution pipeline.
    """
    session = SessionFactory()
    try:
        meeting = session.query(Meeting).filter_by(id=meeting_id).first()
        if not meeting:
            raise HTTPException(status_code=404, detail="Meeting not found.")

        # Check if already recorded
        if meeting.status in (MeetingStatus.NOTE_RECEIVED, MeetingStatus.PROCESSED):
            raise HTTPException(
                status_code=400,
                detail="A voice note has already been recorded for this meeting.",
            )

        # Save audio file
        file_ext = Path(audio.filename or "recording.m4a").suffix or ".m4a"
        file_id = uuid.uuid4().hex[:12]
        file_name = f"meeting_{meeting_id}_{file_id}{file_ext}"
        file_path = os.path.join(config.AUDIO_UPLOAD_DIR, file_name)

        content = await audio.read()
        with open(file_path, "wb") as f:
            f.write(content)

        file_size_kb = len(content) / 1024
        logger.info(
            f"Audio uploaded for meeting {meeting_id}: {file_name} ({file_size_kb:.1f} KB)"
        )

        # Create voice note record
        voice_note = VoiceNote(
            meeting_id=meeting.id,
            audio_file_path=file_path,
        )
        session.add(voice_note)
        meeting.status = MeetingStatus.NOTE_RECEIVED
        session.commit()

        # Trigger async processing pipeline (don't make the user wait)
        asyncio.create_task(
            process_pipeline(meeting.id, voice_note.id)
        )

        return {"status": "success", "message": "Voice note received. Processing..."}

    except HTTPException:
        raise
    except Exception as e:
        session.rollback()
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail="Failed to save audio file.")
    finally:
        session.close()


# =====================================================================
# Processing Pipeline
# =====================================================================


async def process_pipeline(meeting_id: int, voice_note_id: int):
    """
    Full processing pipeline:
    1. Transcribe audio
    2. Process with Claude
    3. Store results
    4. Send to Slack (Daniel + Justine)
    5. Log to Google Sheet
    """
    session = SessionFactory()
    try:
        meeting = session.query(Meeting).filter_by(id=meeting_id).first()
        voice_note = session.query(VoiceNote).filter_by(id=voice_note_id).first()

        if not meeting or not voice_note:
            logger.error(f"Pipeline: meeting {meeting_id} or voice note {voice_note_id} not found.")
            return

        logger.info(f"Pipeline started for meeting '{meeting.title}'")

        # --- Step 1: Transcribe ---
        try:
            transcript = await transcribe_audio(voice_note.audio_file_path, config)
            voice_note.transcript = transcript
            voice_note.transcription_completed_at = datetime.now(timezone.utc)
            session.commit()
            logger.info(f"Transcription complete: {len(transcript)} chars")
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            voice_note.transcript = f"[TRANSCRIPTION ERROR: {str(e)}]"
            session.commit()
            return

        if not transcript.strip():
            logger.warning("Empty transcript, skipping AI processing.")
            return

        # --- Step 2: AI Processing ---
        try:
            processed = await process_voice_note(transcript, meeting, config)
        except Exception as e:
            logger.error(f"AI processing failed: {e}")
            processed = {
                "summary": f"[Processing error] Raw transcript: {transcript[:300]}",
                "action_items": [],
                "follow_ups": [],
                "proposed_tags": [],
                "relationship_signals": [],
                "contact_note": transcript,
            }

        # --- Step 3: Store results ---
        result = ProcessedResult(
            voice_note_id=voice_note.id,
            summary=processed.get("summary", ""),
            action_items_json=json.dumps(processed.get("action_items", [])),
            follow_ups_json=json.dumps(processed.get("follow_ups", [])),
            proposed_tags_json=json.dumps(processed.get("proposed_tags", [])),
            keywords_json=json.dumps(processed.get("keywords", [])),
            relationship_signals_json=json.dumps(
                processed.get("relationship_signals", [])
            ),
            contact_note=processed.get("contact_note", ""),
        )
        session.add(result)
        session.commit()

        # --- Step 4: Slack distribution ---
        try:
            slack_success = await send_combined_output(meeting, processed, config)
            if slack_success:
                result.slack_daniel_sent_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.error(f"Failed to send Slack output: {e}")

        # --- Step 5: Google Sheets log ---
        try:
            if config.GOOGLE_SHEETS_SPREADSHEET_ID:
                sheets_success = await log_to_sheet(meeting, processed, config)
                if sheets_success:
                    result.sheets_logged_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.error(f"Failed to log to sheet: {e}")

        # Mark meeting as fully processed
        meeting.status = MeetingStatus.PROCESSED
        session.commit()

        logger.info(f"Pipeline complete for meeting '{meeting.title}'")

    except Exception as e:
        session.rollback()
        logger.error(f"Pipeline error: {e}")
    finally:
        session.close()


# =====================================================================
# Health Check
# =====================================================================


@app.get("/health")
async def health_check():
    """Health check endpoint for Railway monitoring."""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "poll_interval_minutes": config.POLL_INTERVAL_MINUTES if config else None,
    }


@app.get("/")
async def root():
    """Root endpoint - basic info."""
    return {
        "app": "Voice-to-CRM Pipeline",
        "org": "Sideline Group",
        "status": "running",
    }
