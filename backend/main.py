"""
FileFolio - Local-first document organization system with AI-powered tagging.

This application processes PDF documents through the following pipeline:
1. Upload & Deduplication: PDFs are uploaded and checked for duplicates via SHA-256 hashing
2. Text Extraction: Extract text using PyPDF with OCR fallback for scanned documents
3. AI Analysis: Local LLM (via Ollama) analyzes content to suggest categories, tags, and filenames
4. Storage: Documents stored locally with metadata in SQLite + full-text search index
5. Retrieval: Fast search across content, metadata, and tags with thumbnail previews

Key design decisions:
- Privacy-first: All processing happens locally, no external API calls
- SQLite FTS5: Enables fast full-text search across document content
- Ollama integration: Uses local LLMs (llama3.2-vision) for document analysis
"""

import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import urllib.parse
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Literal, Optional

import ollama
import pypdf
import pytesseract
import uvicorn
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pdf2image import convert_from_path
from PIL import Image
from pydantic import BaseModel

app = FastAPI()

# File size limits
MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB — single PDF upload
MAX_RESTORE_SIZE = (
    2 * 1024 * 1024 * 1024
)  # 2 GB — backup ZIP (may contain full library)

# Setup directories
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
DATA_DIR = BASE_DIR / "data"
THUMBNAILS_DIR = BASE_DIR / "thumbnails"
FRONTEND_DIR = BASE_DIR / "frontend"

UPLOAD_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)
THUMBNAILS_DIR.mkdir(exist_ok=True)

# Database setup
DB_PATH = DATA_DIR / "documents.db"


def get_db_connection():
    """Create a database connection with proper timeout and settings."""
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.execute("PRAGMA busy_timeout = 30000")  # 30 seconds
    conn.row_factory = sqlite3.Row  # Enable column access by name
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Main documents table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            auto_filename TEXT,
            file_path TEXT NOT NULL,
            file_hash TEXT,
            tags TEXT,
            category TEXT,
            upload_date TEXT NOT NULL,
            content_preview TEXT,
            thumbnail_path TEXT
        )
    """)

    # Sync folders table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sync_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT NOT NULL UNIQUE,
            enabled INTEGER DEFAULT 1,
            move_after_processing INTEGER DEFAULT 0,
            created_date TEXT NOT NULL,
            last_scan TEXT
        )
    """)

    # Migrate: drop old non-unique index, create unique index to prevent duplicate inserts.
    # WHERE file_hash IS NOT NULL so rows without a hash (legacy data) don't conflict.
    cursor.execute("DROP INDEX IF EXISTS idx_file_hash")
    try:
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS uq_file_hash
            ON documents(file_hash)
            WHERE file_hash IS NOT NULL
        """)
    except sqlite3.IntegrityError:
        # Existing database has duplicate hashes from a previous race condition.
        # Log a warning; the code-level IntegrityError catch still provides partial protection.
        import logging as _logging

        _logging.getLogger(__name__).warning(
            "Could not create UNIQUE index on file_hash: existing duplicate hashes detected. "
            "Deduplicate the documents table to enforce this constraint."
        )

    # Full-text search virtual table
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            original_filename,
            auto_filename,
            tags,
            category,
            content
        )
    """)

    # Triggers to keep FTS index in sync
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
            INSERT INTO documents_fts(rowid, original_filename, auto_filename, tags, category, content)
            VALUES (new.id, new.original_filename, new.auto_filename, new.tags, new.category, new.content_preview);
        END
    """)

    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
            DELETE FROM documents_fts WHERE rowid = old.id;
        END
    """)

    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
            DELETE FROM documents_fts WHERE rowid = old.id;
            INSERT INTO documents_fts(rowid, original_filename, auto_filename, tags, category, content)
            VALUES (new.id, new.original_filename, new.auto_filename, new.tags, new.category, new.content_preview);
        END
    """)

    conn.commit()
    conn.close()


init_db()


# Initialize sync service
try:
    from backend.sync_service import SyncFolderService
except ModuleNotFoundError:
    from sync_service import SyncFolderService

try:
    from backend import storage
except ModuleNotFoundError:
    import storage

sync_service = SyncFolderService(DB_PATH, UPLOAD_DIR, THUMBNAILS_DIR)


# Startup and shutdown events
@app.on_event("startup")
async def startup_event():
    """Start the sync folder service when the app starts."""
    sync_service.start()


@app.on_event("shutdown")
async def shutdown_event():
    """Stop the sync folder service when the app shuts down."""
    sync_service.stop()


def migrate_existing_documents_to_fts():
    """Migrate existing documents to FTS index if needed."""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Check if FTS table is empty
        cursor.execute("SELECT COUNT(*) FROM documents_fts")
        fts_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM documents")
        docs_count = cursor.fetchone()[0]

        # If FTS is empty but we have documents, populate it
        if fts_count == 0 and docs_count > 0:
            print(f"Migrating {docs_count} documents to FTS index...")
            cursor.execute("""
                INSERT INTO documents_fts(rowid, original_filename, auto_filename, tags, category, content)
                SELECT id, original_filename, auto_filename, tags, category, content_preview
                FROM documents
            """)
            conn.commit()
            print("Migration complete!")
    except sqlite3.OperationalError as e:
        # If schema is wrong, rebuild the FTS table
        if "no such column" in str(e):
            print("FTS table has wrong schema, rebuilding...")
            cursor.execute("DROP TABLE IF EXISTS documents_fts")
            cursor.execute("""
                CREATE VIRTUAL TABLE documents_fts USING fts5(
                    original_filename,
                    auto_filename,
                    tags,
                    category,
                    content
                )
            """)

            # Populate with existing documents
            cursor.execute("SELECT COUNT(*) FROM documents")
            docs_count = cursor.fetchone()[0]

            if docs_count > 0:
                print(f"Populating FTS index with {docs_count} documents...")
                cursor.execute("""
                    INSERT INTO documents_fts(rowid, original_filename, auto_filename, tags, category, content)
                    SELECT id, original_filename, auto_filename, tags, category, content_preview
                    FROM documents
                """)
                conn.commit()
                print("FTS index rebuilt successfully!")
        else:
            raise

    conn.close()


migrate_existing_documents_to_fts()


def reindex_documents_content():
    """Re-extract text from PDFs and update FTS index."""
    conn = get_db_connection()
    # Disable the driver's implicit transaction management so that DDL statements
    # (DROP/CREATE TRIGGER) participate in the explicit transaction below.
    # SQLite itself treats DDL as transactional; Python's sqlite3 module does not
    # by default, which would cause DROP TRIGGER to auto-commit and become
    # irrecoverable if a crash follows.
    conn.isolation_level = None
    cursor = conn.cursor()
    cursor.execute("BEGIN")
    try:
        # Temporarily disable triggers
        cursor.execute("DROP TRIGGER IF EXISTS documents_au")
        cursor.execute("DROP TRIGGER IF EXISTS documents_ai")
        cursor.execute("DROP TRIGGER IF EXISTS documents_ad")

        # Get all documents
        cursor.execute(
            "SELECT id, file_path, original_filename, auto_filename, tags, category FROM documents"
        )
        documents = cursor.fetchall()

        print(f"Re-indexing {len(documents)} documents...")

        # Clear and repopulate FTS index
        cursor.execute("DELETE FROM documents_fts")

        updated = 0

        for doc_id, file_path, orig_name, auto_name, tags, category in documents:
            try:
                try:
                    resolved_path = storage.resolve(file_path, UPLOAD_DIR)
                except ValueError:
                    print(f"Skipping {file_path} - path outside the upload directory")
                    continue

                if not resolved_path.exists():
                    print(f"Skipping {file_path} - file not found")
                    continue

                reader = pypdf.PdfReader(resolved_path)
                full_text = ""
                # Extract from all pages (up to 20 for performance)
                for page in reader.pages[:20]:
                    full_text += page.extract_text() + " "

                # If text extraction yielded little or no text, try OCR
                if len(full_text.strip()) < 50:
                    print(f"  Document {doc_id} appears scanned, attempting OCR...")
                    try:
                        images = convert_from_path(resolved_path, dpi=300)
                        ocr_text = ""
                        for image in images[:20]:
                            page_text = pytesseract.image_to_string(
                                image, lang="eng+deu"
                            )
                            ocr_text += page_text + " "

                        if len(ocr_text.strip()) > len(full_text.strip()):
                            full_text = ocr_text
                            print(
                                f"  OCR successful: {len(full_text)} characters extracted"
                            )
                    except Exception as ocr_error:
                        print(f"  OCR failed: {ocr_error}")

                text_preview = full_text[:2000]

                # Update documents table
                cursor.execute(
                    """
                    UPDATE documents
                    SET content_preview = ?
                    WHERE id = ?
                """,
                    (text_preview, doc_id),
                )

                # Insert into FTS index
                cursor.execute(
                    """
                    INSERT INTO documents_fts(rowid, original_filename, auto_filename, tags, category, content)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (doc_id, orig_name, auto_name, tags, category, text_preview),
                )

                updated += 1

            except Exception as e:
                print(f"Error processing document {doc_id} ({file_path}): {e}")

        # Recreate triggers
        cursor.execute("""
            CREATE TRIGGER documents_ai AFTER INSERT ON documents BEGIN
                INSERT INTO documents_fts(rowid, original_filename, auto_filename, tags, category, content)
                VALUES (new.id, new.original_filename, new.auto_filename, new.tags, new.category, new.content_preview);
            END
        """)

        cursor.execute("""
            CREATE TRIGGER documents_ad AFTER DELETE ON documents BEGIN
                DELETE FROM documents_fts WHERE rowid = old.id;
            END
        """)

        cursor.execute("""
            CREATE TRIGGER documents_au AFTER UPDATE ON documents BEGIN
                DELETE FROM documents_fts WHERE rowid = old.id;
                INSERT INTO documents_fts(rowid, original_filename, auto_filename, tags, category, content)
                VALUES (new.id, new.original_filename, new.auto_filename, new.tags, new.category, new.content_preview);
            END
        """)

        cursor.execute("COMMIT")
    except BaseException:
        cursor.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    print(f"Successfully re-indexed {updated}/{len(documents)} documents")


# Reindex documents content with cryptography support (run once, then comment out)
# reindex_documents_content()


# Mount static files
app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")
app.mount("/thumbnails", StaticFiles(directory=THUMBNAILS_DIR), name="thumbnails")


# ── Request / response models ────────────────────────────────────────────────

ValidCategory = Literal[
    "Invoice",
    "Receipt",
    "Contract",
    "Letter",
    "Report",
    "Form",
    "Statement",
    "Legal",
    "Medical",
    "Tax",
    "Insurance",
    "Other",
]


class UpdateRequest(BaseModel):
    auto_filename: Optional[str] = None
    tags: Optional[List[str]] = None
    category: Optional[ValidCategory] = None


# ── Routes ───────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def read_root():
    html_file = FRONTEND_DIR / "templates" / "index.html"
    return FileResponse(html_file)


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    """
    Upload and process a PDF document.

    This endpoint handles the complete document ingestion pipeline:
    1. Validates the file is a PDF
    2. Saves with timestamped filename and calculates SHA-256 hash
    3. Checks for duplicates using the hash
    4. Extracts text using PyPDF, falls back to OCR for scanned documents
    5. Generates thumbnail from first page
    6. Uses local LLM to suggest category and tags
    7. Stores metadata in SQLite with full-text search index

    Returns: Document metadata including suggested tags and category
    """
    # Strip any directory components from the browser-supplied filename
    raw_filename = file.filename or ""
    safe_filename = Path(raw_filename.replace("\\", "/")).name
    if not safe_filename or "\x00" in safe_filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not safe_filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    # Stage the upload: the category, and therefore the destination folder, is not
    # known until the text has been extracted and processed.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stored_filename = f"{timestamp}_{safe_filename}"
    staging = storage.staging_dir(UPLOAD_DIR)
    staging.mkdir(parents=True, exist_ok=True)
    file_path = staging / stored_filename

    # Stream to disk, enforcing size limit and calculating SHA-256 hash in one pass
    sha256_hash = hashlib.sha256()
    bytes_written = 0
    first_chunk = True
    with file_path.open("wb") as buffer:
        while chunk := await file.read(8192):
            if first_chunk:
                if chunk[:4] != b"%PDF":
                    file_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=400, detail="File is not a valid PDF"
                    )
                first_chunk = False
            bytes_written += len(chunk)
            if bytes_written > MAX_UPLOAD_SIZE:
                file_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum upload size is {MAX_UPLOAD_SIZE // (1024 * 1024)} MB.",
                )
            sha256_hash.update(chunk)
            buffer.write(chunk)

    file_hash = sha256_hash.hexdigest()

    if bytes_written == 0:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400, detail="Empty file. Please upload a non-empty PDF."
        )

    # Check for duplicates
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, original_filename, upload_date FROM documents WHERE file_hash = ?",
        (file_hash,),
    )
    duplicate = cursor.fetchone()
    conn.close()

    if duplicate:
        # Delete the newly uploaded file since it's a duplicate
        file_path.unlink()
        raise HTTPException(
            status_code=409,
            detail=(
                f"Duplicate file detected. This file was already uploaded as"
                f" '{duplicate[1]}' on {duplicate[2][:10]}"
            ),
        )

    # Extract text from PDF for search indexing
    try:
        reader = pypdf.PdfReader(file_path)
        full_text = ""
        # Extract from all pages (up to 20 for performance)
        for page in reader.pages[:20]:
            full_text += page.extract_text() + " "

        # If text extraction yielded little or no text, try OCR
        if len(full_text.strip()) < 50:
            print("PDF appears to be scanned or has minimal text, attempting OCR...")
            try:
                # Convert PDF pages to images and run OCR
                images = convert_from_path(file_path, dpi=300)
                ocr_text = ""
                for i, image in enumerate(images[:20]):  # Limit to 20 pages
                    page_text = pytesseract.image_to_string(image, lang="eng+deu")
                    ocr_text += page_text + " "
                    print(f"OCR extracted {len(page_text)} chars from page {i+1}")

                if len(ocr_text.strip()) > len(full_text.strip()):
                    full_text = ocr_text
                    print(
                        f"OCR successful: extracted {len(full_text)} total characters"
                    )
            except Exception as ocr_error:
                print(f"OCR failed: {ocr_error}")

        # Store first 2000 chars for preview and full text for search
        text_preview = full_text[:2000]
    except pypdf.errors.FileNotDecryptedError:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail="PDF is password-protected and cannot be processed.",
        )
    except pypdf.errors.PyPdfError:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail="File appears to be corrupted or is not a valid PDF.",
        )
    except Exception as e:
        text_preview = f"Error extracting text: {str(e)}"

    # Process document for AI tagging (but don't rename)
    tags, category = process_document(text_preview, safe_filename)

    # Move out of staging into uploads/<Category>/<Year>/. The filename may be
    # uniquified here, so the thumbnail is generated afterwards from the final name.
    upload_date = datetime.now().isoformat()
    try:
        file_path, stored_filename = storage.place(
            file_path, UPLOAD_DIR, category, upload_date, stored_filename
        )
    except OSError as exc:
        Path(file_path).unlink(missing_ok=True)
        raise HTTPException(
            status_code=500, detail=f"Could not store the uploaded file: {exc}"
        )

    # Generate thumbnail
    thumbnail_path = generate_thumbnail(file_path, stored_filename)

    # Save to database
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO documents
            (original_filename, stored_filename, auto_filename, file_path, file_hash,
             tags, category, upload_date, content_preview, thumbnail_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                safe_filename,
                stored_filename,
                None,  # No auto-renaming
                file_path.relative_to(UPLOAD_DIR).as_posix(),
                file_hash,
                json.dumps(tags),
                category,
                upload_date,
                text_preview,
                thumbnail_path,
            ),
        )
        doc_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        # A concurrent upload of the same file beat us to the INSERT after our pre-check.
        conn.close()
        file_path.unlink(missing_ok=True)
        if thumbnail_path:
            (THUMBNAILS_DIR / Path(thumbnail_path).name).unlink(missing_ok=True)
        lookup = get_db_connection()
        row = lookup.execute(
            "SELECT original_filename, upload_date FROM documents WHERE file_hash = ?",
            (file_hash,),
        ).fetchone()
        lookup.close()
        raise HTTPException(
            status_code=409,
            detail=(
                (
                    f"Duplicate file detected. This file was already uploaded as"
                    f" '{row['original_filename']}' on {row['upload_date'][:10]}"
                )
                if row
                else "Duplicate file detected."
            ),
        )
    conn.close()

    return {
        "id": doc_id,
        "original_filename": safe_filename,
        "auto_filename": None,
        "tags": tags,
        "category": category,
        "preview": text_preview[:200],
    }


def generate_thumbnail(pdf_path: Path, stored_filename: str):
    """
    Generate a thumbnail image from the first page of a PDF.

    Args:
        pdf_path: Path to the PDF file
        stored_filename: Filename to use for the thumbnail (replaces .pdf with .jpg)

    Returns:
        URL path to the thumbnail (/thumbnails/filename.jpg) or None on failure
    """
    try:
        # Convert first page to image
        images = convert_from_path(pdf_path, first_page=1, last_page=1, dpi=150)
        if images:
            img = images[0]
            # Resize to thumbnail
            img.thumbnail((300, 400), Image.Resampling.LANCZOS)

            # Save as JPEG
            thumbnail_filename = Path(stored_filename).with_suffix(".jpg").name
            thumbnail_path = THUMBNAILS_DIR / thumbnail_filename
            img.save(thumbnail_path, "JPEG", quality=85)

            return f"/thumbnails/{thumbnail_filename}"
    except Exception as e:
        print(f"Error generating thumbnail: {e}")

    return None


def get_existing_tags():
    """Get all existing tags from the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT tags FROM documents WHERE tags IS NOT NULL AND tags != ''")
    rows = cursor.fetchall()
    conn.close()

    all_tags = set()
    for row in rows:
        try:
            tags = json.loads(row[0])
            all_tags.update(tags)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    return list(all_tags)


def process_document(text: str, filename: str):
    """
    Extract metadata from document using local LLM via Ollama.

    Uses llama3.2-vision model to analyze document content and suggest:
    - Category: High-level classification (Invoice, Contract, Receipt, etc.)
    - Tags: Relevant keywords for organization and search

    Falls back to rule-based extraction if Ollama is unavailable.

    Args:
        text: Extracted text content from the PDF
        filename: Original filename for context

    Returns:
        Tuple of (tags: list[str], category: str)
    """
    # Get existing tags to encourage reuse
    existing_tags = get_existing_tags()
    existing_tags_str = ", ".join(existing_tags) if existing_tags else "none yet"

    # Fallback to rule-based if Ollama fails
    def fallback_processing():
        text_lower = text.lower()
        filename_lower = filename.lower()

        # Determine category
        if "invoice" in text_lower or "bill" in text_lower or "rechnung" in text_lower:
            category = "Invoice"
        elif (
            "contract" in text_lower
            or "agreement" in text_lower
            or "vertrag" in text_lower
        ):
            category = "Contract"
        elif "receipt" in text_lower or "quittung" in text_lower:
            category = "Receipt"
        else:
            category = "Other"

        # Extract meaningful tags from filename and text
        tags = []

        # Common document types in filename
        if (
            "payroll" in filename_lower
            or "gehalt" in filename_lower
            or "lohn" in filename_lower
        ):
            tags.extend(["payroll", "salary"])
        if "birth" in filename_lower or "geburt" in filename_lower:
            tags.extend(["birth certificate"])
        if "passport" in filename_lower or "reisepass" in filename_lower:
            tags.append("passport")
        if "visa" in filename_lower:
            tags.append("visa")
        if "dental" in text_lower or "zahn" in text_lower:
            tags.append("dental care")
        if "medical" in text_lower or "arzt" in text_lower:
            tags.append("medical")
        if "insurance" in text_lower or "versicherung" in text_lower:
            tags.append("insurance policy")
        if "rent" in text_lower or "miete" in text_lower:
            tags.append("rental")
        if "employment" in text_lower or "arbeit" in text_lower:
            tags.append("employment")

        # If no specific tags found, use generic but not useless ones
        if not tags:
            tags = ["unclassified"]

        # Add urgent if detected
        if "urgent" in text_lower:
            tags.append("urgent")

        return tags, category

    # Try Ollama AI processing
    try:
        prompt = f"""Analyze this document excerpt and provide metadata.

CRITICAL REQUIREMENT - TAGS MUST BE IN ENGLISH AND PROPERLY FORMATTED:
- Even if the document is in German, French, or any other language, tags MUST be in English
- TRANSLATE concepts to English tags (e.g., "Lohnabrechnung" → "payroll" or "salary", "Brutto" → "gross")
- Do NOT copy German words directly into tags
- Do NOT use years as tags (e.g., avoid "2024", "2023", etc.)
- Do NOT use very short tags (minimum 3 characters)
- Use spaces, NOT underscores (e.g., "birth certificate" not "birth_certificate")
- Keep tags lowercase and simple (e.g., "payroll", "salary", "dental care", "reimbursement")
- DO NOT use generic category names as tags (e.g., do NOT use "invoice", "receipt", "contract",
  "letter", "report", "form", "statement", "tax", "insurance", "document" as tags)
- Tags should be SPECIFIC descriptors (e.g., "dental care", "teeth cleaning", "reimbursement"
  instead of just "invoice" or "document")
- Existing tags in the system: {existing_tags_str}
- STRONGLY PREFER to reuse existing tags when they are relevant
- Only create new English tags if existing tags don't apply

Provide:
1. A category - YOU MUST choose EXACTLY ONE from this list (use the exact spelling):
   Invoice, Receipt, Contract, Letter, Report, Form, Statement, Legal, Medical, Tax, Insurance, Other
2. Relevant tags (3-5 SPECIFIC English keywords that describe what the document is about, NOT generic category names)

Document excerpt:
{text[:1000]}

Original filename: {filename}

Respond in JSON format:
{{
  "category": "category name",
  "tags": ["specific_tag1", "specific_tag2", "specific_tag3"]
}}"""

        response = ollama.chat(
            model="llama3.2", messages=[{"role": "user", "content": prompt}]
        )

        # Parse response
        response_text = response["message"]["content"]

        # Define valid categories
        VALID_CATEGORIES = [
            "Invoice",
            "Receipt",
            "Contract",
            "Letter",
            "Report",
            "Form",
            "Statement",
            "Legal",
            "Medical",
            "Tax",
            "Insurance",
            "Other",
        ]

        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r"\{[\s\S]*\}", response_text)
        if json_match:
            result = json.loads(json_match.group())
            raw_category = result.get("category", "Other")
            tags = result.get("tags", [])

            # Normalize and validate category (strict matching)
            category = "Other"  # default fallback

            # First try exact match (case-insensitive)
            for valid_cat in VALID_CATEGORIES:
                if valid_cat.lower() == raw_category.lower().strip():
                    category = valid_cat
                    break

            # If no exact match, try partial match as fallback
            if category == "Other":
                for valid_cat in VALID_CATEGORIES:
                    if valid_cat.lower() in raw_category.lower():
                        category = valid_cat
                        break

            # Filter out non-English tags and unwanted patterns
            filtered_tags = []
            for tag in tags:
                # Normalize: lowercase, strip, replace underscores with spaces
                tag_normalized = tag.lower().strip().replace("_", " ")

                # Remove extra spaces
                tag_normalized = re.sub(r"\s+", " ", tag_normalized)

                # Skip empty tags
                if not tag_normalized:
                    continue

                # Skip tags with non-ASCII characters (German umlauts, etc.)
                if not tag_normalized.isascii():
                    continue

                # Skip year tags (4-digit numbers)
                if re.match(r"^\d{4}$", tag_normalized):
                    continue

                # Skip very short tags (less than 3 characters)
                if len(tag_normalized) < 3:
                    continue

                # Skip if tag is same as category (case-insensitive)
                if tag_normalized == category.lower():
                    continue

                # Skip generic useless tags
                if tag_normalized in ["document", "file", "pdf"]:
                    continue

                # Skip duplicate tags
                if tag_normalized not in filtered_tags:
                    filtered_tags.append(tag_normalized)

            # If all tags were filtered out or empty, use fallback to rule-based processing
            if not filtered_tags:
                print(
                    f"AI generated no valid tags for {filename}, falling back to rule-based"
                )
                return fallback_processing()

            return filtered_tags, category
        else:
            return fallback_processing()

    except Exception as e:
        print(f"Ollama processing failed: {e}, falling back to rule-based")
        return fallback_processing()


def _sanitize_fts_query(raw: str) -> str:
    if not raw or not raw.strip():
        return ""

    # Split on "..." quoted phrase tokens (capturing group keeps them in the list)
    parts = re.split(r'("(?:[^"]|"")*")', raw)

    sanitized = []
    last_is_bare = False

    for part in parts:
        if part.startswith('"') and part.endswith('"') and len(part) >= 2:
            sanitized.append(part)
            last_is_bare = False
        else:
            segment = (
                part.replace(":", " ")
                .replace("(", " ")
                .replace(")", " ")
                .replace('"', " ")
                .replace("*", " ")
                .replace("-", " ")
                .replace(",", " ")
            )
            segment = re.sub(r"\b(AND|OR|NOT)\b", lambda m: m.group().lower(), segment)
            segment = " ".join(segment.split())
            if segment:
                tokens = segment.split()
                has_real_token = any(t not in {"and", "or", "not"} for t in tokens)
                sanitized.append(segment)
                last_is_bare = has_real_token

    if not sanitized:
        return ""

    result = " ".join(sanitized)
    if last_is_bare:
        result += "*"
    return result


@app.get("/documents")
async def list_documents(
    search: str = None,
    category: str = None,
    tags: str = None,
    date_from: str = None,
    date_to: str = None,
):
    """
    Retrieve and search documents.

    Supports full-text search across document content, filenames, tags, and categories
    using SQLite FTS5 index for fast queries.

    Args:
        search: Optional search query string (searches content, filename, tags, category)
        category: Optional category filter
        tags: Optional tag filter
        date_from: Optional start date filter
        date_to: Optional end date filter

    Returns:
        List of documents with metadata, thumbnails, and search snippets
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    fts_query = _sanitize_fts_query(search) if search else ""

    # Use FTS5 for search if search term provided
    if fts_query:
        query = """
            SELECT d.* FROM documents d
            INNER JOIN documents_fts fts ON d.id = fts.rowid
            WHERE documents_fts MATCH ?
        """
        params = [fts_query]

        # Add additional filters
        if category:
            query += " AND d.category = ?"
            params.append(category)

        if tags:
            tag_list = [t.strip() for t in tags.split(",")]
            tag_conditions = []
            for tag in tag_list:
                tag_conditions.append("d.tags LIKE ?")
                params.append(f"%{tag}%")
            if tag_conditions:
                query += " AND (" + " OR ".join(tag_conditions) + ")"

        if date_from:
            query += " AND d.upload_date >= ?"
            params.append(date_from)

        if date_to:
            query += " AND d.upload_date <= ?"
            params.append(date_to)

        # Order by FTS5 relevance rank
        query += " ORDER BY rank, d.upload_date DESC"

    else:
        # No search term - use regular query
        query = "SELECT * FROM documents WHERE 1=1"
        params = []

        if category:
            query += " AND category = ?"
            params.append(category)

        if tags:
            tag_list = [t.strip() for t in tags.split(",")]
            tag_conditions = []
            for tag in tag_list:
                tag_conditions.append("tags LIKE ?")
                params.append(f"%{tag}%")
            if tag_conditions:
                query += " AND (" + " OR ".join(tag_conditions) + ")"

        if date_from:
            query += " AND upload_date >= ?"
            params.append(date_from)

        if date_to:
            query += " AND upload_date <= ?"
            params.append(date_to)

        query += " ORDER BY upload_date DESC"

    try:
        cursor.execute(query, params)
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()

    documents = []
    for row in rows:
        # Handle tags JSON parsing with empty string check
        tags = []
        tags_field = row["tags"] if "tags" in row.keys() else None
        if tags_field and tags_field.strip():
            try:
                tags = json.loads(tags_field)
            except (json.JSONDecodeError, ValueError):
                tags = []

        documents.append(
            {
                "id": row["id"],
                "original_filename": row["original_filename"],
                "stored_filename": row["stored_filename"],
                "auto_filename": row["auto_filename"],
                "tags": tags,
                "category": row["category"],
                "upload_date": row["upload_date"],
                "preview": (
                    row["content_preview"][:200] if row["content_preview"] else ""
                ),
                "thumbnail": row["thumbnail_path"],
            }
        )

    return documents


@app.get("/filters")
async def get_filters():
    """Get available categories and tags for filtering."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get unique categories
    cursor.execute(
        "SELECT DISTINCT category FROM documents WHERE category IS NOT NULL ORDER BY category"
    )
    categories = [row[0] for row in cursor.fetchall()]

    # Get all unique tags
    cursor.execute("SELECT tags FROM documents WHERE tags IS NOT NULL AND tags != ''")
    rows = cursor.fetchall()
    conn.close()

    all_tags = set()
    for row in rows:
        try:
            tags = json.loads(row[0])
            all_tags.update(tags)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    return {"categories": categories, "tags": sorted(list(all_tags))}


@app.get("/document/{doc_id}")
async def get_document(doc_id: int):
    """
    Retrieve a single document PDF file.

    Args:
        doc_id: Document ID

    Returns:
        PDF file for viewing/downloading
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT file_path FROM documents WHERE id = ?", (doc_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        resolved_path = storage.resolve(row[0], UPLOAD_DIR)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid stored path")

    if not resolved_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(resolved_path)


@app.get("/download/{doc_id}")
async def download_single_document(doc_id: int):
    """Download a single document with Content-Disposition header."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT file_path, original_filename FROM documents WHERE id = ?", (doc_id,)
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path, original_filename = row[0], row[1]

    try:
        resolved_path = storage.resolve(file_path, UPLOAD_DIR)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid stored path")

    if not resolved_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    encoded_filename = urllib.parse.quote(original_filename)
    return FileResponse(
        resolved_path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
        },
    )


@app.put("/document/{doc_id}")
async def update_document(doc_id: int, updates: UpdateRequest):
    """Update document metadata (filename, tags, category)."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if document exists
    cursor.execute("SELECT * FROM documents WHERE id = ?", (doc_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Document not found")

    # Build update query dynamically
    update_fields = []
    params = []
    new_file_path = None

    if updates.auto_filename is not None:
        update_fields.append("auto_filename = ?")
        params.append(updates.auto_filename)

    if updates.tags is not None:
        update_fields.append("tags = ?")
        params.append(json.dumps(updates.tags))

    if updates.category is not None:
        update_fields.append("category = ?")
        params.append(updates.category)

        # Keep the file where its category says it should be. The year comes from
        # the original upload date so an edit does not move it into the current year.
        try:
            new_file_path = storage.move_to_category(
                row["file_path"], UPLOAD_DIR, updates.category, row["upload_date"]
            )
        except (OSError, ValueError) as exc:
            conn.close()
            print(f"Could not move document {doc_id} to new category: {exc}")
            raise HTTPException(
                status_code=500, detail="Could not move the document file"
            )
        update_fields.append("file_path = ?")
        params.append(new_file_path)

    if not update_fields:
        conn.close()
        raise HTTPException(status_code=400, detail="No valid fields to update")

    params.append(doc_id)
    query = f"UPDATE documents SET {', '.join(update_fields)} WHERE id = ?"

    if new_file_path is not None:
        try:
            cursor.execute(query, params)
            conn.commit()
        except Exception as exc:
            # The file already moved. Put it back so the row and the disk agree.
            try:
                storage.move_to_category(
                    new_file_path, UPLOAD_DIR, row["category"], row["upload_date"]
                )
            except OSError as rollback_exc:
                print(
                    f"Rolled-back move failed for document {doc_id}; row points at "
                    f"{row['file_path']} but the file is at {new_file_path}: {rollback_exc}"
                )
            conn.close()
            print(f"Could not update document {doc_id}: {exc}")
            raise HTTPException(
                status_code=500, detail="Could not update the document"
            )
    else:
        cursor.execute(query, params)
        conn.commit()

    conn.close()

    return {"success": True, "message": "Document updated successfully"}


@app.delete("/document/{doc_id}")
async def delete_document(doc_id: int):
    """
    Delete a document and its associated files.

    Removes the document from the database, deletes the PDF file,
    and removes the thumbnail.

    Args:
        doc_id: Document ID to delete

    Returns:
        Success message
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get document details
    cursor.execute(
        "SELECT file_path, thumbnail_path FROM documents WHERE id = ?", (doc_id,)
    )
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Document not found")

    file_path, thumbnail_path = row[0], row[1]

    # Delete from database
    cursor.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()
    conn.close()

    # Delete physical files
    try:
        if file_path:
            resolved_path = storage.resolve(file_path, UPLOAD_DIR)
            if resolved_path.exists():
                resolved_path.unlink()

        if thumbnail_path:
            # Extract filename from URL path
            thumbnail_file = THUMBNAILS_DIR / Path(thumbnail_path).name
            if thumbnail_file.exists():
                thumbnail_file.unlink()
    except Exception as e:
        print(f"Error deleting files: {e}")

    return {"success": True, "message": "Document deleted successfully"}


class DownloadRequest(BaseModel):
    document_ids: List[int]


@app.post("/download/multiple")
async def download_multiple_documents(request: DownloadRequest):
    """Download multiple documents as a ZIP file."""
    if not request.document_ids:
        raise HTTPException(status_code=400, detail="No documents specified")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get document details
    placeholders = ",".join("?" * len(request.document_ids))
    query = f"SELECT id, file_path, original_filename, stored_filename FROM documents WHERE id IN ({placeholders})"
    cursor.execute(query, request.document_ids)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail="No documents found")

    # Create ZIP file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for doc_id, file_path, original_filename, stored_filename in rows:
            try:
                resolved_path = storage.resolve(file_path, UPLOAD_DIR)
            except ValueError:
                continue
            if resolved_path.exists():
                # Use original filename in the ZIP
                zip_file.write(resolved_path, original_filename)

    zip_buffer.seek(0)

    # Return ZIP file
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=documents_{datetime.now().strftime('%Y%m%d')}.zip"
        },
    )


# Sync Folder Endpoints


class SyncFolderCreate(BaseModel):
    source_path: str
    enabled: Optional[bool] = True
    move_after_processing: Optional[bool] = False


class SyncFolderUpdate(BaseModel):
    enabled: Optional[bool] = None
    move_after_processing: Optional[bool] = None


@app.get("/sync-folders")
async def list_sync_folders():
    """Get all configured sync folders."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, source_path, enabled, move_after_processing, created_date, last_scan
        FROM sync_folders
        ORDER BY created_date DESC
        """)
    rows = cursor.fetchall()
    conn.close()

    folders = []
    for row in rows:
        folders.append(
            {
                "id": row["id"],
                "source_path": row["source_path"],
                "enabled": bool(row["enabled"]),
                "move_after_processing": bool(row["move_after_processing"]),
                "created_date": row["created_date"],
                "last_scan": row["last_scan"],
                "is_watching": row["id"] in sync_service.observers,
            }
        )

    return folders


@app.post("/sync-folders")
async def create_sync_folder(folder: SyncFolderCreate):
    """Add a new sync folder."""
    # Validate path exists
    path = Path(folder.source_path)
    if not path.exists():
        raise HTTPException(status_code=400, detail="Folder does not exist")

    if not path.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    try:
        folder_id = sync_service.add_folder(
            folder.source_path, folder.enabled, folder.move_after_processing
        )
        return {"id": folder_id, "message": "Sync folder added successfully"}
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=400, detail="This folder is already being synced"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/sync-folders/{folder_id}")
async def update_sync_folder(folder_id: int, updates: SyncFolderUpdate):
    """Update sync folder settings."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check if folder exists
    cursor.execute("SELECT * FROM sync_folders WHERE id = ?", (folder_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Sync folder not found")

    # Build update query
    update_fields = []
    params = []

    if updates.enabled is not None:
        update_fields.append("enabled = ?")
        params.append(1 if updates.enabled else 0)

        # Handle starting/stopping the watcher
        if updates.enabled:
            sync_service.enable_folder(folder_id)
        else:
            sync_service.disable_folder(folder_id)

    if updates.move_after_processing is not None:
        update_fields.append("move_after_processing = ?")
        params.append(1 if updates.move_after_processing else 0)

    if update_fields:
        params.append(folder_id)
        query = f"UPDATE sync_folders SET {', '.join(update_fields)} WHERE id = ?"
        cursor.execute(query, params)
        conn.commit()

    conn.close()
    return {"success": True, "message": "Sync folder updated successfully"}


@app.delete("/sync-folders/{folder_id}")
async def delete_sync_folder(folder_id: int):
    """Remove a sync folder."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM sync_folders WHERE id = ?", (folder_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Sync folder not found")

    sync_service.remove_folder(folder_id)
    return {"success": True, "message": "Sync folder removed successfully"}


@app.post("/sync-folders/{folder_id}/scan")
async def scan_sync_folder(folder_id: int):
    """Manually scan a sync folder for existing PDFs."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sync_folders WHERE id = ?", (folder_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Sync folder not found")

    # Run scan in background
    import threading

    thread = threading.Thread(target=sync_service.scan_folder, args=(folder_id,))
    thread.start()

    return {"success": True, "message": "Folder scan started"}


# Backup and Restore Endpoints


@app.get("/backup")
async def create_backup(background_tasks: BackgroundTasks):
    """
    Create a complete backup of the system.

    This endpoint creates a compressed archive containing:
    - Database file (documents.db)
    - All uploaded PDFs
    - All thumbnails
    - System metadata

    Returns a ZIP file for download.
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"filefolio_backup_{timestamp}.zip"

        # Create a temporary file for the backup
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        temp_path = temp_file.name
        temp_file.close()

        # Create ZIP archive
        with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            # Add database using the SQLite backup API for a consistent snapshot
            # even when WAL has unflushed writes.
            if DB_PATH.exists():
                db_backup_fd, db_backup_path = tempfile.mkstemp(suffix=".db")
                os.close(db_backup_fd)
                try:
                    src_conn = sqlite3.connect(str(DB_PATH))
                    dst_conn = sqlite3.connect(db_backup_path)
                    with dst_conn:
                        src_conn.backup(dst_conn)
                    dst_conn.close()
                    src_conn.close()
                    zip_file.write(db_backup_path, "data/documents.db")
                finally:
                    os.unlink(db_backup_path)

            # Add all PDFs
            if UPLOAD_DIR.exists():
                for pdf_file in UPLOAD_DIR.glob("*.pdf"):
                    zip_file.write(pdf_file, f"uploads/{pdf_file.name}")

            # Add all thumbnails
            if THUMBNAILS_DIR.exists():
                for thumb_file in THUMBNAILS_DIR.glob("*.jpg"):
                    zip_file.write(thumb_file, f"thumbnails/{thumb_file.name}")

            # Add metadata file with backup info
            metadata = {
                "backup_date": datetime.now().isoformat(),
                "version": "1.0",
                "system": "FileFolio",
            }
            zip_file.writestr("backup_metadata.json", json.dumps(metadata, indent=2))

        # Return the backup file and clean up after sending
        def cleanup_temp_file():
            try:
                os.unlink(temp_path)
            except Exception as e:
                print(f"Error cleaning up temp file: {e}")

        background_tasks.add_task(cleanup_temp_file)
        return FileResponse(
            temp_path,
            media_type="application/zip",
            filename=backup_filename,
        )

    except Exception as e:
        print(f"Backup error: {e}")
        raise HTTPException(status_code=500, detail=f"Backup failed: {str(e)}")


def _safe_extract(zip_file: zipfile.ZipFile, entry_name: str, base_dir: Path) -> None:
    info = zip_file.getinfo(entry_name)
    if (info.external_attr >> 16) & 0xF000 == 0xA000:
        raise ValueError(f"Unsafe path in archive: {entry_name!r}")
    dest = (base_dir / entry_name).resolve()
    if not dest.is_relative_to(base_dir.resolve()):
        raise ValueError(f"Unsafe path in archive: {entry_name!r}")
    zip_file.extract(entry_name, base_dir)


@app.post("/restore")
async def restore_backup(file: UploadFile = File(...)):
    """
    Restore from a backup file.

    This endpoint restores the system from a backup ZIP file.
    WARNING: This will replace all existing data!

    Args:
        file: ZIP backup file to restore from

    Returns:
        Success message with restoration details
    """
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are allowed")

    temp_backup_path = None
    try:
        # Stream backup to a temp file, enforcing the size limit
        temp_backup = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        temp_backup_path = temp_backup.name
        bytes_written = 0
        with temp_backup as buffer:
            while chunk := await file.read(65536):
                bytes_written += len(chunk)
                if bytes_written > MAX_RESTORE_SIZE:
                    temp_backup.close()
                    os.unlink(temp_backup_path)
                    limit_gb = MAX_RESTORE_SIZE // (1024 * 1024 * 1024)
                    raise HTTPException(
                        status_code=413,
                        detail=f"Backup file too large. Maximum restore size is {limit_gb} GB.",
                    )
                buffer.write(chunk)

        # Extract and validate backup
        with zipfile.ZipFile(temp_backup_path, "r") as zip_file:
            # Check for required files
            file_list = zip_file.namelist()

            if "data/documents.db" not in file_list:
                os.unlink(temp_backup_path)
                raise HTTPException(
                    status_code=400, detail="Invalid backup: missing database file"
                )

            # Stop sync service before restore
            sync_service.stop()

            # Create backup of current data before restore
            backup_dir = (
                DATA_DIR
                / f"pre_restore_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            )
            backup_dir.mkdir(exist_ok=True)

            # Backup current database
            if DB_PATH.exists():
                shutil.copy2(DB_PATH, backup_dir / "documents.db")

            # Extract database
            _safe_extract(zip_file, "data/documents.db", BASE_DIR)

            # Extract PDFs
            pdf_files = [
                f for f in file_list if f.startswith("uploads/") and f.endswith(".pdf")
            ]
            for pdf_file in pdf_files:
                _safe_extract(zip_file, pdf_file, BASE_DIR)

            # Extract thumbnails
            thumb_files = [
                f
                for f in file_list
                if f.startswith("thumbnails/") and f.endswith(".jpg")
            ]
            for thumb_file in thumb_files:
                _safe_extract(zip_file, thumb_file, BASE_DIR)

            # Read backup metadata if available
            metadata = {}
            if "backup_metadata.json" in file_list:
                metadata_content = zip_file.read("backup_metadata.json")
                metadata = json.loads(metadata_content)

        # Clean up temp backup file
        os.unlink(temp_backup_path)

        # Restart sync service
        sync_service.start()

        return {
            "success": True,
            "message": "Backup restored successfully",
            "metadata": metadata,
            "stats": {
                "pdfs_restored": len(pdf_files),
                "thumbnails_restored": len(thumb_files),
            },
        }

    except ValueError as e:
        if temp_backup_path is not None:
            try:
                os.unlink(temp_backup_path)
            except OSError:
                pass
        try:
            sync_service.start()
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=str(e))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid ZIP file")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Restore error: {e}")
        # Try to restart sync service if it was stopped
        try:
            sync_service.start()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Restore failed: {str(e)}")


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host=host, port=port)
