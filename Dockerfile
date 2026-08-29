FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Keeps the container running so any team member can exec into it and run
# whichever script they need (script.py, confidence_framework.py, etc.)
# without the image needing a fixed entrypoint.
CMD ["bash"]
