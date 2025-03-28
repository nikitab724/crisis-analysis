FROM --platform=linux/amd64 python:3.12

COPY requirements.txt ./proj-dev/

WORKDIR /proj-dev

RUN pip install --no-cache-dir -r requirements.txt && python -m spacy download en_core_web_trf

EXPOSE 8888 8050

ENV NAME=World

CMD [ "sleep", "infinity" ]