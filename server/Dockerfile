# Uses the python:3.12-slim image that is already on the server, so a deploy downloads nothing.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 DC_DB=/data/leaderboard.db PORT=8080
RUN useradd --system --uid 10001 dc && mkdir /data && chown dc /data
WORKDIR /app
COPY leaderboard.py admin.py ./
USER dc
VOLUME /data
EXPOSE 8080
CMD ["python", "leaderboard.py"]
