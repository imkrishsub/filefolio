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

If you've looked at Paperless-ngx, here's how they compare:

| | FileFolio | Paperless-ngx |
|---|---|---|
| AI tagging & naming | 🟢 Local LLM via Ollama, zero config | 🔴 Rule-based; define tags, types, and correspondents manually |
| Setup | 🟢 Single Python process + SQLite | 🔴 Docker Compose: web, worker, Redis, PostgreSQL |
| Resource footprint | 🟢 Lightweight | 🔴 Multi-service, heavier |
| Multi-user | 🔴 No | 🟢 Yes |
| Feature scope | 🔴 Focused: upload, search, tag, organize | 🟢 Broader: email ingestion, custom fields, workflow automation |
| Best for | 🟢 Personal libraries, privacy-first, low setup | 🟢 Power users, teams, complex workflows |

## Features

- **Automatic organization** – watches a folder and imports new PDFs, extracting text (with OCR), then generating categories and tags
- **Privacy-first** – all processing happens locally with Ollama, no cloud services, no telemetry or analytics
- **Fast retrieval** – full-text search across content and metadata, plus thumbnail previews
- **Disaster-proof** – backup and restore your entire library via ZIP
- **Multi-language support** – UI available in multiple languages
- **Dark mode** – toggle between light and dark themes

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

## Quick start

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
