FROM python:3.12

WORKDIR /workspace
COPY requirements.txt requirements-demo.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m spacy download en_core_web_trf

COPY . .
EXPOSE 8051

# Development container: start the documented services with docker exec.
CMD ["sleep", "infinity"]
