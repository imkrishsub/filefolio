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

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from pathlib import Path
import shutil
from datetime import datetime
import pypdf
import sqlite3
import json
import ollama
import re
from pdf2image import convert_from_path
from PIL import Image
import io
import base64
import pytesseract
import hashlib
import zipfile
from typing import List
from pydantic import BaseModel
import os

app = FastAPI()

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

    # Create index on file_hash for fast duplicate detection
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_file_hash ON documents(file_hash)
    """)

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
    cursor = conn.cursor()

    # Temporarily disable triggers
    cursor.execute("DROP TRIGGER IF EXISTS documents_au")
    cursor.execute("DROP TRIGGER IF EXISTS documents_ai")
    cursor.execute("DROP TRIGGER IF EXISTS documents_ad")

    # Get all documents
    cursor.execute("SELECT id, file_path, original_filename, auto_filename, tags, category FROM documents")
    documents = cursor.fetchall()

    print(f"Re-indexing {len(documents)} documents...")

    # Clear and repopulate FTS index
    cursor.execute("DELETE FROM documents_fts")

    updated = 0

    for doc_id, file_path, orig_name, auto_name, tags, category in documents:
        try:
            if not Path(file_path).exists():
                print(f"Skipping {file_path} - file not found")
                continue

            reader = pypdf.PdfReader(file_path)
            full_text = ""
            # Extract from all pages (up to 20 for performance)
            for page in reader.pages[:20]:
                full_text += page.extract_text() + " "

            # If text extraction yielded little or no text, try OCR
            if len(full_text.strip()) < 50:
                print(f"  Document {doc_id} appears scanned, attempting OCR...")
                try:
                    images = convert_from_path(file_path, dpi=300)
                    ocr_text = ""
                    for image in images[:20]:
                        page_text = pytesseract.image_to_string(image, lang='eng+deu')
                        ocr_text += page_text + " "

                    if len(ocr_text.strip()) > len(full_text.strip()):
                        full_text = ocr_text
                        print(f"  OCR successful: {len(full_text)} characters extracted")
                except Exception as ocr_error:
                    print(f"  OCR failed: {ocr_error}")

            text_preview = full_text[:2000]

            # Update documents table
            cursor.execute("""
                UPDATE documents
                SET content_preview = ?
                WHERE id = ?
            """, (text_preview, doc_id))

            # Insert into FTS index
            cursor.execute("""
                INSERT INTO documents_fts(rowid, original_filename, auto_filename, tags, category, content)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (doc_id, orig_name, auto_name, tags, category, text_preview))

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

    conn.commit()
    conn.close()
    print(f"Successfully re-indexed {updated}/{len(documents)} documents")


# Reindex documents content with cryptography support (run once, then comment out)
# reindex_documents_content()


# Mount static files
app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")
app.mount("/thumbnails", StaticFiles(directory=THUMBNAILS_DIR), name="thumbnails")


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
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")

    # Save file temporarily
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stored_filename = f"{timestamp}_{file.filename}"
    file_path = UPLOAD_DIR / stored_filename

    # Calculate file hash while saving
    sha256_hash = hashlib.sha256()
    with file_path.open("wb") as buffer:
        while chunk := await file.read(8192):
            sha256_hash.update(chunk)
            buffer.write(chunk)

    file_hash = sha256_hash.hexdigest()

    # Check for duplicates
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, original_filename, upload_date FROM documents WHERE file_hash = ?", (file_hash,))
    duplicate = cursor.fetchone()
    conn.close()

    if duplicate:
        # Delete the newly uploaded file since it's a duplicate
        file_path.unlink()
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate file detected. This file was already uploaded as '{duplicate[1]}' on {duplicate[2][:10]}"
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
            print(f"PDF appears to be scanned or has minimal text, attempting OCR...")
            try:
                # Convert PDF pages to images and run OCR
                images = convert_from_path(file_path, dpi=300)
                ocr_text = ""
                for i, image in enumerate(images[:20]):  # Limit to 20 pages
                    page_text = pytesseract.image_to_string(image, lang='eng+deu')
                    ocr_text += page_text + " "
                    print(f"OCR extracted {len(page_text)} chars from page {i+1}")

                if len(ocr_text.strip()) > len(full_text.strip()):
                    full_text = ocr_text
                    print(f"OCR successful: extracted {len(full_text)} total characters")
            except Exception as ocr_error:
                print(f"OCR failed: {ocr_error}")

        # Store first 2000 chars for preview and full text for search
        text_preview = full_text[:2000]
    except Exception as e:
        text_preview = f"Error extracting text: {str(e)}"

    # Generate thumbnail
    thumbnail_path = generate_thumbnail(file_path, stored_filename)

    # Process document for AI tagging (but don't rename)
    tags, category = process_document(text_preview, file.filename)

    # Save to database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO documents
        (original_filename, stored_filename, auto_filename, file_path, file_hash, tags, category, upload_date, content_preview, thumbnail_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        file.filename,
        stored_filename,
        None,  # No auto-renaming
        str(file_path),
        file_hash,
        json.dumps(tags),
        category,
        datetime.now().isoformat(),
        text_preview,
        thumbnail_path
    ))
    doc_id = cursor.lastrowid
    conn.commit()
    conn.close()

    return {
        "id": doc_id,
        "original_filename": file.filename,
        "auto_filename": None,
        "tags": tags,
        "category": category,
        "preview": text_preview[:200]
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
            thumbnail_filename = stored_filename.replace('.pdf', '.jpg')
            thumbnail_path = THUMBNAILS_DIR / thumbnail_filename
            img.save(thumbnail_path, 'JPEG', quality=85)

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
        except:
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
        if "invoice" in text_lower or "bill" in text_lower:
            category = "Invoice"
            tags = ["invoice"]
        elif "contract" in text_lower or "agreement" in text_lower:
            category = "Contract"
            tags = ["contract"]
        elif "receipt" in text_lower:
            category = "Receipt"
            tags = ["receipt"]
        else:
            category = "Other"
            tags = ["document"]

        # Add year tags
        if "2024" in text:
            tags.append("2024")
        if "2025" in text:
            tags.append("2025")

        # Add urgent if detected
        if "urgent" in text_lower:
            tags.append("urgent")

        return tags, category

    # Try Ollama AI processing
    try:
        prompt = f"""Analyze this document excerpt and provide metadata.

CRITICAL REQUIREMENT - TAGS MUST BE IN ENGLISH:
- Even if the document is in German, French, or any other language, tags MUST be in English
- TRANSLATE concepts to English tags (e.g., "Lohnabrechnung" → "payroll" or "salary", "Brutto" → "gross")
- Do NOT copy German words directly into tags
- Existing tags in the system: {existing_tags_str}
- STRONGLY PREFER to reuse existing tags when they are relevant
- Only create new English tags if existing tags don't apply
- Keep tags lowercase and simple (e.g., "invoice", "payroll", "salary", "tax", "2024")

Provide:
1. A category (choose one: Invoice, Receipt, Contract, Letter, Report, Form, Statement, Legal, Medical, Tax, Insurance, Other)
2. Relevant tags (3-5 English keywords that describe the document)

Document excerpt:
{text[:1000]}

Original filename: {filename}

Respond in JSON format:
{{
  "category": "category name",
  "tags": ["english_tag1", "english_tag2", "english_tag3"]
}}"""

        response = ollama.chat(
            model='llama3.2',
            messages=[{'role': 'user', 'content': prompt}]
        )

        # Parse response
        response_text = response['message']['content']

        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            result = json.loads(json_match.group())
            category = result.get('category', 'Other')
            tags = result.get('tags', [])

            # Filter out non-English tags (basic check for common German/non-English chars)
            filtered_tags = []
            for tag in tags:
                # Remove tags with umlauts or other non-English characters
                if not re.search(r'[äöüßÄÖÜ]', tag):
                    filtered_tags.append(tag.lower())

            # If all tags were filtered out or empty, ensure we have at least one tag
            if not filtered_tags:
                if existing_tags:
                    # Use some existing tags
                    filtered_tags = existing_tags[:3]
                else:
                    # Use category as tag
                    filtered_tags = [category.lower()]

            return filtered_tags, category
        else:
            return fallback_processing()

    except Exception as e:
        print(f"Ollama processing failed: {e}, falling back to rule-based")
        return fallback_processing()


@app.get("/documents")
async def list_documents(
    search: str = None,
    category: str = None,
    tags: str = None,
    date_from: str = None,
    date_to: str = None
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

    # Use FTS5 for search if search term provided
    if search:
        # Escape FTS5 special characters and prepare fuzzy query
        fts_query = search.replace('"', '""')

        # Add wildcard suffix for prefix matching (fuzzy search)
        # This allows "payro" to match "payroll"
        fts_query = fts_query + '*'

        # Build the query using FTS5
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

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    documents = []
    for row in rows:
        documents.append({
            "id": row[0],
            "original_filename": row[1],
            "stored_filename": row[2],
            "auto_filename": row[3],
            "tags": json.loads(row[5]) if row[5] else [],
            "category": row[6],
            "upload_date": row[7],
            "preview": row[8][:200] if row[8] else "",
            "thumbnail": row[9] if len(row) > 9 else None
        })

    return documents


@app.get("/filters")
async def get_filters():
    """Get available categories and tags for filtering."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get unique categories
    cursor.execute("SELECT DISTINCT category FROM documents WHERE category IS NOT NULL ORDER BY category")
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
        except:
            pass

    return {
        "categories": categories,
        "tags": sorted(list(all_tags))
    }


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

    return FileResponse(row[0])


@app.get("/download/{doc_id}")
async def download_single_document(doc_id: int):
    """Download a single document with Content-Disposition header."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT file_path, original_filename FROM documents WHERE id = ?", (doc_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path, original_filename = row[0], row[1]

    if not Path(file_path).exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=original_filename,
        headers={
            "Content-Disposition": f"attachment; filename={original_filename}"
        }
    )


@app.put("/document/{doc_id}")
async def update_document(doc_id: int, updates: dict):
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

    if "auto_filename" in updates:
        update_fields.append("auto_filename = ?")
        params.append(updates["auto_filename"])

    if "tags" in updates:
        update_fields.append("tags = ?")
        params.append(json.dumps(updates["tags"]))

    if "category" in updates:
        update_fields.append("category = ?")
        params.append(updates["category"])

    if not update_fields:
        conn.close()
        raise HTTPException(status_code=400, detail="No valid fields to update")

    params.append(doc_id)
    query = f"UPDATE documents SET {', '.join(update_fields)} WHERE id = ?"

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
    cursor.execute("SELECT file_path, thumbnail_path FROM documents WHERE id = ?", (doc_id,))
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
        if file_path and Path(file_path).exists():
            Path(file_path).unlink()

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
    placeholders = ','.join('?' * len(request.document_ids))
    query = f"SELECT id, file_path, original_filename, stored_filename FROM documents WHERE id IN ({placeholders})"
    cursor.execute(query, request.document_ids)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        raise HTTPException(status_code=404, detail="No documents found")

    # Create ZIP file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for doc_id, file_path, original_filename, stored_filename in rows:
            if Path(file_path).exists():
                # Use original filename in the ZIP
                zip_file.write(file_path, original_filename)

    zip_buffer.seek(0)

    # Return ZIP file
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=documents_{datetime.now().strftime('%Y%m%d')}.zip"
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="127.0.0.1", port=port)
