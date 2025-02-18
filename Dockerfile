FROM python:3.12

COPY requirements.txt ./
COPY app /app/
COPY data /app/data/

WORKDIR /app

RUN pip install --no-cache-dir -r ../requirements.txt && python -m spacy download en_core_web_sm

EXPOSE 8888

ENV NAME World

CMD [ "jupyter", "notebook", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root" ]