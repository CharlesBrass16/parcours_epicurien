FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .

CMD ["sh", "-c", "python prototype_extract/extract.py && python prototype_extract/transform.py && python prototype_extract/load.py && python app.py"]
