# The demonstration model server: standard library only.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY mock_llm.py .
RUN useradd --create-home --uid 10001 appuser
USER appuser
EXPOSE 9000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/health', timeout=2)"
CMD ["python", "mock_llm.py"]
