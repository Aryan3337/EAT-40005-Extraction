FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Small English model for check_subject_specificity.py's dependency-parse
# subject audit (~12MB download, ~50MB installed).
RUN python -m spacy download en_core_web_sm

COPY . .

# Keeps the container running so any team member can exec into it and run
# whichever script they need (script.py, confidence_framework.py, etc.)
# without the image needing a fixed entrypoint.
CMD ["bash"]
