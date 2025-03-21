FROM python:3.11-slim
ADD . /code
WORKDIR /code
RUN apt-get update && apt-get install -y build-essential git wget unzip libspeex-dev libspeexdsp-dev libpulse-dev && apt-get clean && rm -rf /var/lib/apt/lists/*
RUN pip install -r requirements.txt
RUN pip install vosk

# Download small English model - FIXED PATH HANDLING
RUN mkdir -p /code/model && \
    wget -q https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip && \
    unzip -o vosk-model-small-en-us-0.15.zip && \
    cp -r vosk-model-small-en-us-0.15/* /code/model/ && \
    rm -rf vosk-model-small-en-us-0.15 vosk-model-small-en-us-0.15.zip && \
    ls -la /code/model/

# Add verification step
RUN if [ ! -f /code/model/conf/mfcc.conf ]; then echo "Model files not correctly installed"; exit 1; fi && \
    echo "Vosk model installed successfully"

CMD exec gunicorn -k gevent -b 0.0.0.0:$PORT asr:app