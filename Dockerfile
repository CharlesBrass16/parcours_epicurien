FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .

CMD ["sh", "-c", "python ETL/extract.py && python ETL/transform.py && python ETL/load.py && python app.py"]
