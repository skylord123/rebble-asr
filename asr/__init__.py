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
from speex import SpeexDecoder
from flask import Flask, request, Response, abort


decoder = SpeexDecoder(1)
app = Flask(__name__)

#AUTH_URL = "https://auth.rebble.io"
API_KEY = os.environ['ASR_API_KEY']
try:
    ASR_API_PROVIDER = os.environ.get('ASR_API_PROVIDER', 'groq')
except Exception:
    ASR_API_PROVIDER = 'groq'


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
        return transcription.get("text", "")

    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return None

def groq_transcribe(wav_buffer):
    try:
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
        return transcription.get("text", "")

    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return None


@app.route('/heartbeat')
def heartbeat():
    return 'asr'

@app.route('/NmspServlet/', methods=["POST"])
def recognise():
    stream = request.stream
    
    chunks = list(parse_chunks(stream))
    chunks = chunks[3:]
    pcm_data = bytearray()

    if len(chunks) > 15:
        chunks = chunks[12:-3]
    for i, chunk in enumerate(chunks):
        decoded = decoder.decode(chunk)
        # Boosting the audio volume
        decoded = audioop.mul(decoded, 2, 7)
        # Directly append decoded audio bytes
        pcm_data.extend(decoded)

    # Create WAV file in memory
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, 'wb') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(pcm_data)

    wav_buffer.seek(0)

    # Initialize transcript variable
    transcript = None
    
    if ASR_API_PROVIDER == 'elevenlabs':
        transcript = elevenlabs_transcribe(wav_buffer)
    elif ASR_API_PROVIDER == 'groq':  # Changed from 'if' to 'elif'
        transcript = groq_transcribe(wav_buffer)
    else:
        print(f"[ERROR] Invalid ASR API provider: {ASR_API_PROVIDER}")
        abort(400)  # Added status code and actually call abort()
    
    # Check if transcript is valid
    if transcript is None:
        print("[ERROR] Transcription failed or returned None")
        abort(500)
        
    print(f"[DEBUG] Transcript: {transcript}")
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
    #print(f"[DEBUG] Final response text prepared with boundary: {parts.get_boundary()}")
    response = Response(response_text)
    response.headers['Content-Type'] = f'multipart/form-data; boundary={parts.get_boundary()}'
    #print("[DEBUG] Sending response")
    return response

