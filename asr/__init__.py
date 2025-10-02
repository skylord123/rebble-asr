import gevent.monkey
gevent.monkey.patch_all()
from email.mime.multipart import MIMEMultipart
from email.message import Message
from .model_map import get_model_for_lang
import json
import os
import struct
import requests
import io
import wave
import time
import audioop
import logging
import asyncio
from datetime import datetime
from speex import SpeexDecoder
from flask import Flask, request, Response, abort

# Wyoming imports
try:
    import wyoming
    from wyoming.asr import Transcribe, Transcript
    from wyoming.audio import AudioChunk, AudioStart, AudioStop
    from wyoming.client import AsyncTcpClient
    HAS_WYOMING = True
except ImportError:
    HAS_WYOMING = False
    print("[WARNING] Wyoming package not installed, wyoming-whisper provider will not be available")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('rebble-asr')

# Set up debug mode from environment variable
DEBUG = os.environ.get('DEBUG', 'false').lower() in ('true', '1', 't', 'yes')
if DEBUG:
    logger.setLevel(logging.DEBUG)
    logger.debug("Debug mode enabled")
else:
    logger.setLevel(logging.INFO)

decoder = SpeexDecoder(1)
app = Flask(__name__)

# Get API key from environment, or None if not set
API_KEY = os.environ.get('ASR_API_KEY')

# Get Wyoming connection details from environment
WYOMING_HOST = os.environ.get('WYOMING_HOST', 'localhost')
WYOMING_PORT = int(os.environ.get('WYOMING_PORT', '10300'))

# Audio recording configuration
SAVE_RECORDINGS = os.environ.get('SAVE_RECORDINGS', 'false').lower() in ('true', '1', 't', 'yes')
AUDIO_RECORDINGS_DIR = os.environ.get('AUDIO_RECORDINGS_DIR')
MAX_AUDIO_RECORDINGS = int(os.environ.get('MAX_AUDIO_RECORDINGS', '10'))

# Audio settings for Wyoming
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
SAMPLE_CHANNELS = 1

# Determine which provider to use
try:
    # If API key is not set, use Vosk
    if not API_KEY and os.environ.get('ASR_API_PROVIDER') != 'wyoming-whisper':
        ASR_API_PROVIDER = 'vosk'
        print("[INFO] No API key set, using Vosk for transcription")
    else:
        # Get the provider from environment and strip any quotes
        ASR_API_PROVIDER = os.environ.get('ASR_API_PROVIDER', 'groq')
        # Remove quotes if they exist
        ASR_API_PROVIDER = ASR_API_PROVIDER.strip('"\'')
except Exception:
    # Fallback to Vosk if there's any error in provider setup
    ASR_API_PROVIDER = 'vosk'
    print("[INFO] Error determining API provider, using Vosk as fallback")

logger.info(f"Using ASR API provider: {ASR_API_PROVIDER}")

# Check if Wyoming is available when selected
if ASR_API_PROVIDER == 'wyoming-whisper' and not HAS_WYOMING:
    logger.warning("Wyoming-whisper selected but Wyoming package not installed, falling back to Vosk")
    ASR_API_PROVIDER = 'vosk'

# Validate and initialize audio recording configuration
if SAVE_RECORDINGS:
    if not AUDIO_RECORDINGS_DIR:
        logger.warning("SAVE_RECORDINGS is enabled but AUDIO_RECORDINGS_DIR is not set. Disabling audio recording.")
        SAVE_RECORDINGS = False
    else:
        try:
            os.makedirs(AUDIO_RECORDINGS_DIR, exist_ok=True)
            logger.info(f"Audio recording enabled. Saving to: {AUDIO_RECORDINGS_DIR} (max: {MAX_AUDIO_RECORDINGS} files)")
        except (OSError, PermissionError) as e:
            logger.error(f"Failed to create audio recordings directory '{AUDIO_RECORDINGS_DIR}': {e}")
            logger.error("Disabling audio recording.")
            SAVE_RECORDINGS = False
else:
    logger.info("Audio recording disabled")


# We know gunicorn does this, but it doesn't *say* it does this, so we must signal it manually.
@app.before_request
def handle_chunking():
    request.environ['wsgi.input_terminated'] = 1


def parse_chunks(stream):
    boundary = b'--' + request.headers['content-type'].split(';')[1].split('=')[1].encode('utf-8').strip()  # super lazy/brittle parsing.
    this_frame = b''
    while True:
        content = stream.read(4096)
        this_frame += content
        end = this_frame.find(boundary)
        if end > -1:
            frame = this_frame[:end]
            this_frame = this_frame[end + len(boundary):]
            if frame != b'':
                try:
                    header, content = frame.split(b'\r\n\r\n', 1)
                except ValueError:
                    continue
                yield content[:-2]
        if content == b'':
            print("End of input.")
            break

def elevenlabs_transcribe(wav_buffer):
    try:
        if DEBUG:
            logger.debug("Starting ElevenLabs transcription")
            api_start_time = time.time()

        # Create transcription via the ElevenLabs API
        TRANSCIPTION_URL = "https://api.elevenlabs.io/v1/speech-to-text"

        files = {
            "file": ("audio.wav", wav_buffer, "audio/wav")
        }
        data = {
            "model_id": "scribe_v1",
            "tag_audio_events": "false",
            "timestamps_granularity": "none"
        }
        headers = {
            "xi-api-key": API_KEY
        }

        response_api = requests.post(TRANSCIPTION_URL, files=files, data=data, headers=headers)
        response_api.raise_for_status()
        transcription = response_api.json()

        if DEBUG:
            api_time = time.time() - api_start_time
            logger.debug(f"ElevenLabs API request completed in {api_time:.3f}s")

        return transcription.get("text", "")

    except requests.exceptions.RequestException as e:
        logger.error(f"ElevenLabs transcription error: {e}")
        return None

def groq_transcribe(wav_buffer):
    try:
        if DEBUG:
            logger.debug("Starting Groq transcription")
            api_start_time = time.time()

        # Create transcription via the Groq API
        TRANSCIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

        files = {
            "file": ("audio.wav", wav_buffer, "audio/wav")
        }
        data = {
            "model": "whisper-large-v3",
            "response_format": "json"
        }
        headers = {
            "Authorization": f"Bearer {API_KEY}"
        }

        response_api = requests.post(TRANSCIPTION_URL, files=files, data=data, headers=headers)
        response_api.raise_for_status()
        transcription = response_api.json()

        if DEBUG:
            api_time = time.time() - api_start_time
            logger.debug(f"Groq API request completed in {api_time:.3f}s")

        return transcription.get("text", "")

    except requests.exceptions.RequestException as e:
        logger.error(f"Groq transcription error: {e}")
        return None

def wyoming_whisper_transcribe(wav_buffer):
    try:
        if not HAS_WYOMING:
            logger.error("Wyoming package not installed, cannot use wyoming-whisper")
            return None

        if DEBUG:
            logger.debug(f"Starting Wyoming-whisper transcription")
            logger.debug(f"Wyoming host: {WYOMING_HOST}, port: {WYOMING_PORT}")
            wyoming_start_time = time.time()

        # Reset buffer position and read the audio data
        wav_buffer.seek(0)

        # Parse the WAV file to get just the PCM data
        with wave.open(wav_buffer, 'rb') as wav_file:
            audio_data = wav_file.readframes(wav_file.getnframes())
            if DEBUG:
                logger.debug(f"Extracted {len(audio_data)} bytes of PCM data from WAV")

        # Since we need to use asyncio, we need to create and run an async function
        async def process_with_wyoming():
            connection_start_time = time.time() if DEBUG else 0
            try:
                # Connect to Wyoming service
                async with AsyncTcpClient(WYOMING_HOST, WYOMING_PORT) as client:
                    if DEBUG:
                        connection_time = time.time() - connection_start_time
                        logger.debug(f"Connected to Wyoming service in {connection_time:.3f}s")

                    # Set transcription language (using default as we don't have language info)
                    await client.write_event(Transcribe(language=None).event())

                    # Begin audio stream
                    await client.write_event(
                        AudioStart(
                            rate=SAMPLE_RATE,
                            width=SAMPLE_WIDTH,
                            channels=SAMPLE_CHANNELS,
                        ).event()
                    )

                    if DEBUG:
                        logger.debug(f"Sending {len(audio_data)} bytes to Wyoming service")

                    # Send audio data
                    chunk = AudioChunk(
                        rate=SAMPLE_RATE,
                        width=SAMPLE_WIDTH,
                        channels=SAMPLE_CHANNELS,
                        audio=audio_data,
                    )
                    await client.write_event(chunk.event())

                    # End audio stream
                    await client.write_event(AudioStop().event())

                    if DEBUG:
                        logger.debug("Waiting for transcription result")

                    # Wait for transcription result
                    while True:
                        event = await client.read_event()
                        if event is None:
                            logger.error("Wyoming connection lost")
                            return None

                        if Transcript.is_type(event.type):
                            transcript = Transcript.from_event(event)
                            if DEBUG:
                                logger.debug(f"Received transcript from Wyoming service: '{transcript.text}'")
                            return transcript.text
            except Exception as e:
                logger.error(f"Wyoming transcription error: {e}")
                if DEBUG:
                    import traceback
                    logger.debug(traceback.format_exc())
                return None

        # Run the async function in an event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(process_with_wyoming())
            if DEBUG:
                wyoming_time = time.time() - wyoming_start_time
                logger.debug(f"Wyoming-whisper transcription completed in {wyoming_time:.3f}s")
            return result
        finally:
            loop.close()

    except Exception as e:
        logger.error(f"Wyoming-whisper transcription error: {e}")
        if DEBUG:
            import traceback
            logger.debug(traceback.format_exc())
        return None

def vosk_transcribe(wav_buffer):
    try:
        if DEBUG:
            logger.debug("Starting Vosk transcription")
            vosk_start_time = time.time()

        from vosk import Model, KaldiRecognizer
        import json

        # Check if model directory exists
        model_path = os.environ.get('VOSK_MODEL_PATH', '/code/model')
        if not os.path.exists(model_path):
            logger.error(f"Vosk model directory not found at {model_path}")
            return None

        # Check for model files
        model_files = os.listdir(model_path)
        if DEBUG:
            logger.debug(f"Files in model directory: {model_files}")

        required_files = ['am', 'conf', 'ivector']
        missing_files = [f for f in required_files if not any(f in file for file in model_files)]

        if missing_files:
            logger.error(f"Missing required Vosk model files: {missing_files}")
            return None

        try:
            # Initialize model
            model_init_start = time.time() if DEBUG else 0
            model = Model(model_path)
            rec = KaldiRecognizer(model, 16000)

            if DEBUG:
                model_init_time = time.time() - model_init_start
                logger.debug(f"Vosk model initialized in {model_init_time:.3f}s")

            # Reset buffer position
            wav_buffer.seek(0)
            # Read the WAV data
            wav_data = wav_buffer.read()

            if DEBUG:
                logger.debug(f"Processing {len(wav_data)} bytes with Vosk")
                process_start_time = time.time()

            # Process audio
            if len(wav_data) > 0:
                if rec.AcceptWaveform(wav_data):
                    result = json.loads(rec.Result())
                else:
                    result = json.loads(rec.FinalResult())

                if DEBUG:
                    process_time = time.time() - process_start_time
                    logger.debug(f"Vosk processing completed in {process_time:.3f}s")
                    logger.debug(f"Vosk result: {result}")

                transcript = result.get("text", "")

                if DEBUG:
                    vosk_total_time = time.time() - vosk_start_time
                    logger.debug(f"Vosk transcription completed in {vosk_total_time:.3f}s")

                return transcript
            return ""

        except Exception as inner_e:
            logger.error(f"Failed to initialize Vosk model: {inner_e}")
            if DEBUG:
                import traceback
                logger.debug(traceback.format_exc())
            return None

    except Exception as e:
        logger.error(f"Vosk transcription error: {e}")
        if DEBUG:
            import traceback
            logger.debug(traceback.format_exc())
        return None

def save_audio_recording(wav_buffer, transcript):
    """
    Save audio recording and transcript to disk with automatic rotation.

    Args:
        wav_buffer: BytesIO object containing the WAV file
        transcript: The transcribed text string
    """
    try:
        # Generate timestamp-based filename
        timestamp = datetime.now().strftime('recording_%Y%m%d_%H%M%S')
        wav_filename = f"{timestamp}.wav"
        txt_filename = f"{timestamp}.txt"

        wav_path = os.path.join(AUDIO_RECORDINGS_DIR, wav_filename)
        txt_path = os.path.join(AUDIO_RECORDINGS_DIR, txt_filename)

        # Save WAV file
        try:
            wav_buffer.seek(0)
            with open(wav_path, 'wb') as f:
                f.write(wav_buffer.read())

            if DEBUG:
                wav_size = os.path.getsize(wav_path)
                logger.debug(f"Saved audio recording: {wav_path} ({wav_size} bytes)")
        except (IOError, OSError) as e:
            logger.error(f"Failed to save WAV file '{wav_path}': {e}")
            return

        # Save transcript file
        try:
            with open(txt_path, 'w', encoding='utf-8') as f:
                f.write(transcript)

            if DEBUG:
                logger.debug(f"Saved transcript: {txt_path}")
        except (IOError, OSError) as e:
            logger.error(f"Failed to save transcript file '{txt_path}': {e}")

        # Rotate old recordings if limit exceeded
        try:
            # Get all WAV files sorted by modification time (oldest first)
            wav_files = []
            for filename in os.listdir(AUDIO_RECORDINGS_DIR):
                if filename.endswith('.wav'):
                    filepath = os.path.join(AUDIO_RECORDINGS_DIR, filename)
                    wav_files.append((filepath, os.path.getmtime(filepath)))

            # Sort by modification time
            wav_files.sort(key=lambda x: x[1])

            # Delete oldest files if we exceed the limit
            files_to_delete = len(wav_files) - MAX_AUDIO_RECORDINGS
            if files_to_delete > 0:
                for i in range(files_to_delete):
                    old_wav_path = wav_files[i][0]
                    old_txt_path = old_wav_path.replace('.wav', '.txt')

                    # Delete WAV file
                    try:
                        os.remove(old_wav_path)
                        if DEBUG:
                            logger.debug(f"Deleted old recording: {old_wav_path}")
                    except OSError as e:
                        logger.error(f"Failed to delete old WAV file '{old_wav_path}': {e}")

                    # Delete corresponding TXT file if it exists
                    if os.path.exists(old_txt_path):
                        try:
                            os.remove(old_txt_path)
                            if DEBUG:
                                logger.debug(f"Deleted old transcript: {old_txt_path}")
                        except OSError as e:
                            logger.error(f"Failed to delete old TXT file '{old_txt_path}': {e}")

            if DEBUG:
                remaining_files = len(wav_files) - max(0, files_to_delete)
                logger.debug(f"Audio recordings in directory: {remaining_files}/{MAX_AUDIO_RECORDINGS}")

        except (IOError, OSError) as e:
            logger.error(f"Failed to rotate old recordings: {e}")

        # Reset buffer position for any subsequent use
        wav_buffer.seek(0)

    except Exception as e:
        logger.error(f"Unexpected error in save_audio_recording: {e}")
        if DEBUG:
            import traceback
            logger.debug(traceback.format_exc())

@app.route('/heartbeat')
def heartbeat():
    return 'asr'

@app.route('/NmspServlet/', methods=["POST"])
def recognise():
    # Track total processing time
    start_time = time.time()

    if DEBUG:
        logger.debug(f"Received request from: {request.remote_addr}")
        logger.debug(f"Request headers: {dict(request.headers)}")

    stream = request.stream

    chunks = list(parse_chunks(stream))
    chunks = chunks[3:]
    pcm_data = bytearray()

    if len(chunks) > 15:
        chunks = chunks[12:-3]

    if DEBUG:
        logger.debug(f"Received {len(chunks)} audio chunks")

    chunk_process_start = time.time()
    for i, chunk in enumerate(chunks):
        decoded = decoder.decode(chunk)
        # Boosting the audio volume
        decoded = audioop.mul(decoded, 2, 7)
        # Directly append decoded audio bytes
        pcm_data.extend(decoded)

    if DEBUG:
        chunk_process_time = time.time() - chunk_process_start
        logger.debug(f"Processed {len(chunks)} chunks in {chunk_process_time:.3f}s")
        logger.debug(f"PCM data size: {len(pcm_data)} bytes")

    # Create WAV file in memory
    wav_start_time = time.time()
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(pcm_data)

    wav_buffer.seek(0)
    wav_size = wav_buffer.getbuffer().nbytes

    if DEBUG:
        wav_process_time = time.time() - wav_start_time
        logger.debug(f"Created WAV file in {wav_process_time:.3f}s")
        logger.debug(f"WAV file size: {wav_size} bytes")
        logger.debug(f"Audio duration: ~{len(pcm_data)/16000/2:.2f}s at 16kHz")

    # Initialize transcript variable
    transcript = None

    logger.info(f"Using ASR API provider: {ASR_API_PROVIDER}")

    # Track transcription time
    transcription_start = time.time()

    if ASR_API_PROVIDER == 'elevenlabs':
        if not API_KEY:
            logger.error("ElevenLabs requires an API key, falling back to Vosk")
            transcript = vosk_transcribe(wav_buffer)
        else:
            transcript = elevenlabs_transcribe(wav_buffer)
    elif ASR_API_PROVIDER == 'groq':
        if not API_KEY:
            logger.error("Groq requires an API key, falling back to Vosk")
            transcript = vosk_transcribe(wav_buffer)
        else:
            transcript = groq_transcribe(wav_buffer)
    elif ASR_API_PROVIDER == 'wyoming-whisper':
        transcript = wyoming_whisper_transcribe(wav_buffer)
        if transcript is None:
            logger.error("Wyoming-whisper transcription failed, falling back to Vosk")
            transcript = vosk_transcribe(wav_buffer)
    elif ASR_API_PROVIDER == 'vosk':
        transcript = vosk_transcribe(wav_buffer)
    else:
        logger.error(f"Invalid ASR API provider: {ASR_API_PROVIDER}, falling back to Vosk")
        transcript = vosk_transcribe(wav_buffer)

    transcription_time = time.time() - transcription_start

    # Check if transcript is valid
    if transcript is None:
        logger.error("All transcription methods failed")
        abort(500)

    logger.info(f"Transcript: '{transcript}' (took {transcription_time:.3f}s)")

    # Save audio recording if enabled
    if SAVE_RECORDINGS and AUDIO_RECORDINGS_DIR:
        save_audio_recording(wav_buffer, transcript)

    words = []
    for word in transcript.split():
        words.append({
            'word': word,
            'confidence': 1.0
        })

    # Now create a MIME multipart response
    parts = MIMEMultipart()
    response_part = Message()
    response_part.add_header('Content-Type', 'application/JSON; charset=utf-8')

    if len(words) > 0:
        response_part.add_header('Content-Disposition', 'form-data; name="QueryResult"')
        # Append the no-space marker and uppercase the first character
        words[0]['word'] += '\\*no-space-before'
        words[0]['word'] = words[0]['word'][0].upper() + words[0]['word'][1:]
        payload = json.dumps({'words': [words]})
        #print(f"[DEBUG] Payload for QueryResult: {payload}")
    else:
        response_part.add_header('Content-Disposition', 'form-data; name="QueryRetry"')
        payload = json.dumps({
            "Cause": 1,
            "Name": "AUDIO_INFO",
            "Prompt": "Sorry, speech not recognized. Please try again."
        })
        #print(f"[DEBUG] Payload for QueryRetry: {payload}")

    response_part.set_payload(payload)
    parts.attach(response_part)

    parts.set_boundary('--Nuance_NMSP_vutc5w1XobDdefsYG3wq')
    response_text = '\r\n' + parts.as_string().split("\n", 3)[3].replace('\n', '\r\n')
    if DEBUG:
        logger.debug(f"Final response text prepared with boundary: {parts.get_boundary()}")

    response = Response(response_text)
    response.headers['Content-Type'] = f'multipart/form-data; boundary={parts.get_boundary()}'

    # Log total processing time
    total_time = time.time() - start_time
    logger.info(f"Total processing time: {total_time:.3f}s")

    if DEBUG:
        logger.debug("Sending response")

    return response