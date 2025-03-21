# rebble-asr
asr.rebble.io: speech recognition for rebble

## Overview

Rebble ASR provides automatic speech recognition services for Pebble smartwatches.

## Configuration Options

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `ASR_API_KEY` | API key for ElevenLabs or Groq | None | Required for cloud providers |
| `ASR_API_PROVIDER` | Speech recognition provider (`elevenlabs`, `groq`, or `vosk`) | `vosk` | No |
| `PORT` | Port for the HTTP server | 9039 | No |

### ASR Providers

#### ElevenLabs

Uses ElevenLabs' Scribe v1 model for high-quality transcription.

```bash
export ASR_API_PROVIDER=elevenlabs
export ASR_API_KEY=your_elevenlabs_api_key
```

#### Groq

Uses Groq API with Whisper model for fast transcription.

```bash
export ASR_API_PROVIDER=groq
export ASR_API_KEY=your_groq_api_key
```

#### Vosk (Offline)

Uses Vosk for offline speech recognition. No API key required.

```bash
export ASR_API_PROVIDER=vosk
```


## Fallback Behavior

- If no API key is provided, falls back to Vosk offline recognition
- If an invalid provider is specified, falls back to Vosk
- Gracefully handles errors by attempting alternative recognition methods