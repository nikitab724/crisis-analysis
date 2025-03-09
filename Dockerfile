FROM python:3.12

COPY requirements.txt ./

RUN pip install --no-cache-dir -r requirements.txt && python -m spacy download en_core_web_sm

EXPOSE 8888 8050

ENV NAME World

COPY app/main.py .
COPY data/crisis_counts.csv data/crisis_counts.csv

#CMD [ "jupyter", "notebook", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root" ]
CMD ["python", "main.py", "run", "--ip=0.0.0.0", "--port=8050"]
