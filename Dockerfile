FROM python:slim
LABEL authors="wapeety, notherealmarco"

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir -r requirements.txt


ENTRYPOINT ["python", "/app/bot.py"]