"""
Audio transcription using the Deepgram Nova-2 API.
"""

import logging
from pathlib import Path

import httpx

from config import Config

logger = logging.getLogger(__name__)

DEEPGRAM_API_URL = "https://api.deepgram.com/v1/listen"


async def transcribe_audio(audio_file_path: str, config: Config) -> str:
    """
    Send an audio file to Deepgram for transcription.

    Args:
        audio_file_path: Path to the audio file on disk.
        config: Application configuration with Deepgram API key.

    Returns:
        The transcribed text as a string.
    """
    file_path = Path(audio_file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_file_path}")

    # Determine content type from extension
    extension = file_path.suffix.lower()
    content_type_map = {
        ".mp4": "audio/mp4",
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".webm": "audio/webm",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
    }
    content_type = content_type_map.get(extension, "audio/mp4")

    # Read the audio file
    audio_data = file_path.read_bytes()
    file_size_kb = len(audio_data) / 1024
    logger.info(f"Transcribing {file_path.name} ({file_size_kb:.1f} KB, {content_type})")

    # Call Deepgram API
    params = {
        "model": "nova-2",
        "language": "en",
        "smart_format": "true",  # Adds punctuation and formatting
        "punctuate": "true",
        "diarize": "false",  # Single speaker (Greg), no need for diarization
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            DEEPGRAM_API_URL,
            headers={
                "Authorization": f"Token {config.DEEPGRAM_API_KEY}",
                "Content-Type": content_type,
            },
            params=params,
            content=audio_data,
        )

        if response.status_code != 200:
            logger.error(
                f"Deepgram API error: {response.status_code} - {response.text}"
            )
            response.raise_for_status()

        result = response.json()

    # Extract transcript from response
    channels = result.get("results", {}).get("channels", [])
    if not channels:
        logger.warning("Deepgram returned no channels in response.")
        return ""

    alternatives = channels[0].get("alternatives", [])
    if not alternatives:
        logger.warning("Deepgram returned no alternatives in response.")
        return ""

    transcript = alternatives[0].get("transcript", "")
    confidence = alternatives[0].get("confidence", 0)

    logger.info(
        f"Transcription complete: {len(transcript)} chars, confidence={confidence:.2f}"
    )
    return transcript
