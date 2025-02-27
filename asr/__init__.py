import gevent.monkey
gevent.monkey.patch_all()
from email.mime.multipart import MIMEMultipart
from email.message import Message
from .model_map import get_model_for_lang
import json
import os
import struct
import requests
from io import BytesIO
from pydub import AudioSegment
import audioop
from speex import SpeexDecoder
from flask import Flask, request, Response, abort


decoder = SpeexDecoder(1)
app = Flask(__name__)

#AUTH_URL = "https://auth.rebble.io"
API_KEY = os.environ['ELEVENLABS_API_KEY']


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


@app.route('/heartbeat')
def heartbeat():
    return 'asr'

@app.route('/NmspServlet/', methods=["POST"])
def recognise():
    stream = request.stream
    
    chunks = list(parse_chunks(stream))[3:]
    full_audio = AudioSegment.empty()

    if len(chunks) > 15:
        chunks = chunks[12:-3]
    for chunk in chunks:
        decoded = decoder.decode(chunk)
        # Boosting the audio volume
        decoded = audioop.mul(decoded, 2, 7)
        audio = AudioSegment(decoded, sample_width=2, frame_rate=16000, channels=1)
        full_audio += audio

    # After concatenating full_audio, export it as m4a in-memory.
    out_buffer = BytesIO()
    # Export using ffmpeg; ensure ffmpeg is installed in your container.
    full_audio.export(out_buffer, format="mp4", codec="aac")
    out_buffer.seek(0)
    audio_bytes = out_buffer.getvalue()
    #save the audio file

    transcription = None

    try:
        # Create transcription via the ElevenLabs API
        TRANSCIPTION_URL = "https://api.elevenlabs.io/v1/speech-to-text"
    
        files = {
            "file": ("audio.m4a", audio_bytes, "audio/mp4")
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

    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
    #print(f"[DEBUG] transcription received: {transcription}")
    if transcription is None:
        abort
    
    transcript = transcription.get("text", "")
    #print(f"[DEBUG] Transcript: {transcript}")
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

