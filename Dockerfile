FROM python:3.12

COPY requirements.txt ./
COPY app /app/

WORKDIR /app

RUN pip install --no-cache-dir -r ../requirements.txt

RUN pip freeze > frozen-requirements.txt

CMD [ "python", "main.py" ]