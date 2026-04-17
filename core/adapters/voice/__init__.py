"""Voice / TTS adapters.

  * ``elevenlabs`` — ElevenLabs text-to-speech API

Bootstrap::

    from core.adapters.voice.bootstrap import register_all
    register_all()
"""
from ._base import VoiceBaseAdapter

__all__ = ["VoiceBaseAdapter"]
