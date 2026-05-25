# KG Extractor – Local Knowledge Graph from PDFs

Extract (subject, predicate, object) triples from academic PDFs using a free local LLM (Ollama + Mistral 7B). No API keys, no cloud costs.

## Requirements

- macOS / Linux / Windows
- Python 3.8+
- Ollama installed ([ollama.com](https://ollama.com))
- At least 8GB RAM (16GB recommended)

## Installation

1. **Install Ollama**  
   macOS/Linux: `curl -fsSL https://ollama.com/install.sh | sh`  
   Windows: Download from ollama.com

2. **Start the Ollama server** (keep this terminal open)  
   `ollama serve`

3. **Pull the Mistral model** (in a new terminal, ~4GB download)  
   `ollama pull mistral:7b`

4. **Install Python dependencies**  
   `pip install pdfplumber requests`

5. **Get the script**  
   Save the provided `script.py` in a folder (see the repository for the full code).

## Usage

Place your PDF file in the same folder as `script.py`. Then run:

```bash
python script.py your_paper.pdf mistral:7b
