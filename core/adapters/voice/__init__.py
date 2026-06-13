"""Voice / TTS adapters.

ShopAI's cold-start ad-creative pipeline combines a stock
video clip (Pexels) with an AI-generated voiceover to
produce ~$0.20-0.50 video creatives. ElevenLabs is the
canonical voiceover source -- best-in-class voice quality,
generous free tier (10k chars/month), and a simple REST
API.

The VOICE_TEXT_TO_SPEECH capability is the primary
operator-facing entry point. Future voice adapters
(OpenAI TTS, Play.ht, etc.) join here and share the
same dispatch.
"""
