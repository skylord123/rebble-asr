# rebble-asr
asr.rebble.io: speech recognition for rebble

## Overview

Rebble ASR provides automatic speech recognition services for Pebble smartwatches.

## Configuration Options

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `ASR_API_KEY` | API key for ElevenLabs or Groq | None | Required for cloud providers |
| `ASR_API_PROVIDER` | Speech recognition provider (`elevenlabs`, `groq`, `wyoming-whisper`, or `vosk`) | `vosk` | No |
| `PORT` | Port for the HTTP server | 9039 | No |
| `WYOMING_HOST` | Host address for Wyoming service | `localhost` | Required for wyoming-whisper |
| `WYOMING_PORT` | Port for Wyoming service | `10300` | Required for wyoming-whisper |
| `DEBUG` | Enable detailed debug logging | `false` | No |

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

#### Wyoming-Whisper

Uses a local Wyoming-compatible speech recognition service (like [Home Assistant's Whisper](https://hub.docker.com/r/rhasspy/wyoming-whisper) integration).

```bash
export ASR_API_PROVIDER=wyoming-whisper
export WYOMING_HOST=your_wyoming_host  # IP address or hostname
export WYOMING_PORT=10300  # Default Wyoming port
```

#### Vosk (Offline)

Uses Vosk for offline speech recognition. No API key required.

```bash
export ASR_API_PROVIDER=vosk
```

## Debug Mode

Enable detailed logging for troubleshooting:

```bash
export DEBUG=true
```

Debug mode provides information about:
- Request details and headers
- Audio processing metrics
- Transcription timing and performance
- Service communication details

## Fallback Behavior

- If no API key is provided, falls back to Vosk offline recognition
- If an invalid provider is specified, falls back to Vosk
- If Wyoming-Whisper is selected but the Wyoming package is not installed, falls back to Vosk
- If Wyoming-Whisper fails to connect to the Wyoming service, falls back to Vosk
- Gracefully handles errors by attempting alternative recognition methods