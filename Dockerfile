FROM python:3.10-slim

WORKDIR /app

# Installa le dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il codice dell'applicazione, lo schema del database e i test
COPY web/ web/
COPY db/ db/
COPY tests/ tests/

# La cartella data/ viene creata automaticamente da app.py (os.makedirs)
# e resa persistente tramite il volume definito in docker-compose.yml

EXPOSE 5000

CMD ["python", "web/app.py"]
