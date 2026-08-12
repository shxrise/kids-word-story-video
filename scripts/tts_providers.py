#!/usr/bin/env python3
"""TTS provider adapters returning a common word-boundary contract."""

from __future__ import annotations

import asyncio
import html
import os
from pathlib import Path


def _seconds(value) -> float:
    if hasattr(value, "total_seconds"):
        return float(value.total_seconds())
    return float(value) / 10_000_000


async def _edge_synthesize(text: str, voice: str, rate: str, out_path: Path) -> list[dict]:
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError("edge-tts is not installed; run doctor.py --project <project> --repair") from exc
    communicate = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    words: list[dict] = []
    with out_path.open("wb") as handle:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                handle.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 10_000_000
                words.append({
                    "text": chunk["text"],
                    "start": round(start, 3),
                    "end": round(start + chunk["duration"] / 10_000_000, 3),
                })
    return words


def _azure_synthesize(text: str, voice: str, rate: str, out_path: Path) -> list[dict]:
    try:
        import azure.cognitiveservices.speech as speechsdk
    except ImportError as exc:
        raise RuntimeError(
            "Azure Speech SDK is not installed; run doctor.py --project <project> --repair --tts-provider azure"
        ) from exc
    key = os.environ.get("AZURE_SPEECH_KEY") or os.environ.get("SPEECH_KEY")
    region = os.environ.get("AZURE_SPEECH_REGION") or os.environ.get("SPEECH_REGION")
    if not key or not region:
        raise RuntimeError("Azure TTS requires AZURE_SPEECH_KEY and AZURE_SPEECH_REGION")
    config = speechsdk.SpeechConfig(subscription=key, region=region)
    config.speech_synthesis_voice_name = voice
    config.set_speech_synthesis_output_format(
        speechsdk.SpeechSynthesisOutputFormat.Audio24Khz96KBitRateMonoMp3
    )
    audio = speechsdk.audio.AudioOutputConfig(filename=str(out_path))
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=audio)
    words: list[dict] = []

    def on_boundary(event) -> None:
        if getattr(event, "boundary_type", None) != speechsdk.SpeechSynthesisBoundaryType.Word:
            return
        token = str(getattr(event, "text", ""))
        if not token.strip():
            return
        start = float(event.audio_offset) / 10_000_000
        duration = _seconds(event.duration)
        words.append({"text": token, "start": round(start, 3), "end": round(start + duration, 3)})

    synthesizer.synthesis_word_boundary.connect(on_boundary)
    ssml = (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="zh-CN">'
        f'<voice name="{html.escape(voice, quote=True)}"><prosody rate="{html.escape(rate, quote=True)}">'
        f"{html.escape(text)}</prosody></voice></speak>"
    )
    result = synthesizer.speak_ssml_async(ssml).get()
    if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        details = speechsdk.SpeechSynthesisCancellationDetails.from_result(result)
        raise RuntimeError(f"Azure Speech synthesis failed: {details.reason}; {details.error_details}")
    return words


def synthesize(provider: str, text: str, voice: str, rate: str, out_path: Path) -> list[dict]:
    if provider == "edge":
        words = asyncio.run(_edge_synthesize(text, voice, rate, out_path))
    elif provider == "azure":
        words = _azure_synthesize(text, voice, rate, out_path)
    else:
        raise ValueError(f"unsupported TTS provider: {provider}")
    if not words:
        raise RuntimeError(f"{provider} returned no word boundaries for: {text[:20]}…")
    return words
