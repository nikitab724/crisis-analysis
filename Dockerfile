FROM python:3.12

COPY requirements.txt ./

WORKDIR /app

RUN pip install --no-cache-dir -r ../requirements.txt && python -m spacy download en_core_web_sm

RUN pip install dash_bootstrap_components
RUN pip install dash_ag_grid
RUN pip install geopy
RUN pip install dash_leaflet
RUN pip install opencage

# remove this
RUN pip install requests

EXPOSE 8888

ENV NAME World

COPY app/main.py .

#CMD [ "jupyter", "notebook", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root" ]
CMD ["python", "main.py", "run", "--ip=0.0.0.0", "--port=8050"]