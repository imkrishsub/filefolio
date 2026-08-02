# FileFolio

FileFolio helps privacy-conscious professionals keep large PDF collections searchable and organized using local AI. No cloud, no telemetry, all on your machine.

[![Support me on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/krishsub)

![FileFolio Preview](preview.png)

**Status:** Actively maintained, used on my own 1,000+ PDF collection. Expect breaking changes before v1.0, but I'm responsive to issues and feedback.

## Why FileFolio?

- You have hundreds of PDF bills, reports, or research papers scattered in folders.
- You care about privacy and do not want to upload them to cloud AI services.
- You still want smart search, auto-tagging, and reasonable file names.

FileFolio watches a folder, uses a local LLM via Ollama to analyze each PDF, and keeps everything searchable in one interface.

## FileFolio vs Paperless-ngx

Paperless-ngx is the most popular self-hosted alternative. Here's how they compare:

| Feature | FileFolio | Paperless-ngx |
|---|---|---|
| AI tagging and naming | 🟢 Local LLM via Ollama, zero config | 🔴 ML classifier available, but requires manual training; no LLM-level understanding |
| Setup | 🟢 Single Python process + SQLite | 🔴 Docker Compose: web, worker, Redis, PostgreSQL |
| Resource footprint | 🟢 Single process + Ollama | 🔴 Multi-service, heavier |
| Multi-user | 🔴 No | 🟢 Yes |
| Feature scope | 🔴 Focused: upload, search, tag, organize | 🟢 Broader: email ingestion, custom fields, workflow automation |
| Best for | 🟢 Personal libraries, privacy-first, low setup | 🟢 Power users, teams, complex workflows |

## Features

- **Automatic organization** – drop PDFs in a watched folder and Ollama names, tags, and categorizes them automatically
- **Privacy-first** – every byte stays on your machine, no cloud calls, no telemetry
- **Fast retrieval** – full-text search across content and metadata with thumbnail previews
- **Disaster-proof** – back up and restore your entire library as a single ZIP

## Prerequisites

- Python 3.10+
- [Ollama](https://ollama.ai) installed locally
- Poppler (for PDF processing)
  - macOS: `brew install poppler`
  - Ubuntu/Debian: `apt-get install poppler-utils`
  - Windows: Download from [poppler releases](https://github.com/oschwartz10612/poppler-windows/releases/)
- Tesseract (for OCR on scanned documents)
  - macOS: `brew install tesseract`
  - Ubuntu/Debian: `apt-get install tesseract-ocr`
  - Windows: Download from [Tesseract releases](https://github.com/UB-Mannheim/tesseract/wiki)

## How files are stored

Uploaded PDFs are filed by category and year:

```
uploads/
  Invoice/
    2026/
      20260731_101500_bill.pdf
  Receipt/
    2025/
      20251102_090000_lidl.pdf
```

Changing a document's category in the interface moves the file to the matching folder.
An existing flat `uploads/` directory is reorganised automatically the next time FileFolio
starts.

Thumbnails stay flat in `thumbnails/` — they are generated artifacts, not files you browse.

## Quick start

### Docker (recommended)

1. **Clone the repository**
```bash
git clone https://github.com/imkrishsub/filefolio.git
cd filefolio
```

2. **Start Ollama** (if not already running)
```bash
ollama serve
```

3. **Start FileFolio**
```bash
docker compose up
```

4. **Open your browser**
Navigate to: http://localhost:8000

Ollama runs on your host machine; the container connects to it automatically via `host.docker.internal`. On Linux, set `OLLAMA_HOST=http://172.17.0.1:11434` if `host.docker.internal` is not available.

### Manual setup

1. **Clone the repository**
```bash
git clone https://github.com/imkrishsub/filefolio.git
cd filefolio
```

2. **Create and activate virtual environment**
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Start Ollama** (in a separate terminal)
```bash
ollama serve
```

5. **Run the application**
```bash
python backend/main.py
```

6. **Open your browser**
Navigate to: http://127.0.0.1:8000

## Configuration

### Custom port

Set a custom port using the `PORT` environment variable:

```bash
PORT=8080 python backend/main.py
# or with Docker:
PORT=8080 docker compose up
```

### Custom Ollama URL

```bash
OLLAMA_HOST=http://192.168.1.10:11434 docker compose up
```

## Testing

```bash
pytest
```

Full API and functionality coverage including unit tests, integration tests, and frontend tests.

## Project structure

```
filefolio/
├── backend/
│   ├── main.py          # FastAPI server
│   └── sync_service.py  # Folder sync service
├── frontend/
│   ├── static/
│   │   ├── app.js       # Frontend JavaScript
│   │   ├── style.css    # Styles
│   │   └── i18n.json    # Translations
│   └── templates/
│       └── index.html   # Main interface
├── tests/               # Test suite
├── uploads/             # PDF storage (created on first run)
├── thumbnails/          # Document thumbnails (created on first run)
├── data/                # Database (created on first run)
├── setup.cfg            # Linting and tool configuration
├── pytest.ini           # Test configuration
└── requirements.txt
```

## How it works

1. **Upload** - Drag and drop a PDF file into the web interface, or sync a local folder to automatically import new files
2. **Extract** - Text is extracted from the PDF (with OCR fallback for scanned documents)
3. **Analyze** - A local LLM analyzes the content to determine category, tags, and suggest a filename
4. **Organize** - The document is saved with metadata in a local SQLite database
5. **Search** - Find documents by content, category, tags, or filename

## Tech stack

- **Backend**: FastAPI (Python)
- **Frontend**: Vanilla JavaScript
- **Database**: SQLite
- **AI/LLM**: Ollama
- **PDF Processing**: PyPDF, pdf2image, pytesseract
- **Styling**: Custom CSS

## Contributing

Contributions are welcome! Please feel free to submit a pull request or open an issue.

## License

MIT License - see [LICENSE](LICENSE) file for details.
