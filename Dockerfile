FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

RUN useradd --create-home --uid 10001 app

COPY . .

# config.py creates patient_data/ on import, so the app user owns that folder and nothing else.
RUN mkdir -p patient_data && chown app:app patient_data

USER app

CMD exec streamlit run streamlit_app.py \
    --server.port=$PORT \
    --server.address=0.0.0.0 \
    --server.headless=true
