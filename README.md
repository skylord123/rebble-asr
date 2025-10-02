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
| `PORT` | Port for the HTTP server | `9039` | No |
| `WYOMING_HOST` | Host address for Wyoming service | `localhost` | Required for wyoming-whisper |
| `WYOMING_PORT` | Port for Wyoming service | `10300` | Required for wyoming-whisper |
| `VOSK_MODEL_PATH` | Path to custom Vosk model directory | `/code/model` | No |
| `DEBUG` | Enable detailed debug logging | `false` | No |
| `SAVE_RECORDINGS` | Enable saving audio files and transcripts to disk | `false` | No |
| `AUDIO_RECORDINGS_DIR` | Directory path for saved recordings | None | Required when `SAVE_RECORDINGS=true` |
| `MAX_AUDIO_RECORDINGS` | Maximum number of recordings to keep (auto-rotation) | `10` | No |

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

## Audio Recording

Rebble ASR can save audio files and their transcriptions to disk for debugging, quality assurance, or analysis purposes.

### Enable Audio Recording

```bash
export SAVE_RECORDINGS=true
export AUDIO_RECORDINGS_DIR=/path/to/recordings
export MAX_AUDIO_RECORDINGS=10  # Optional, defaults to 10
```

### How It Works

When enabled, each transcription request will save:
- **WAV file**: The audio data sent for transcription (e.g., `recording_20251002_143022.wav`)
- **TXT file**: The transcribed text (e.g., `recording_20251002_143022.txt`)

Files are automatically rotated to keep only the most recent recordings based on `MAX_AUDIO_RECORDINGS`.

### Docker Setup

When using Docker Compose, map a host directory to persist recordings:

```yaml
volumes:
  - ./recordings:/recordings
```

Then set the environment variable to the container path:

```bash
export AUDIO_RECORDINGS_DIR=/recordings
```

### Use Cases

- **Debugging**: Analyze failed or incorrect transcriptions
- **Quality Assurance**: Review transcription accuracy
- **Model Training**: Collect real-world audio samples
- **Troubleshooting**: Identify issues with audio quality or format

## Fallback Behavior

- If no API key is provided, falls back to Vosk offline recognition
- If an invalid provider is specified, falls back to Vosk
- If Wyoming-Whisper is selected but the Wyoming package is not installed, falls back to Vosk
- If Wyoming-Whisper fails to connect to the Wyoming service, falls back to Vosk
- Gracefully handles errors by attempting alternative recognition methods