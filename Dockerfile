FROM python:3

WORKDIR .

COPY requirements.txt ./
RUN apt-get update && \
    apt-get install -y ffmpeg libffi-dev libnacl-dev python3-dev && \
    pip install -r requirements.txt

COPY . .

CMD [ "python", "./bot.py" ]
