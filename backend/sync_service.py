"""
Sync folder service for FileFolio.

Watches configured folders for new PDF files and automatically processes them
using the existing document processing pipeline.
"""

import hashlib
import json
import logging
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class PDFHandler(FileSystemEventHandler):
    """Handles file system events for PDF files."""

    def __init__(
        self,
        folder_id: int,
        source_path: str,
        process_callback,
        move_after: bool = False,
    ):
        """
        Initialize PDF handler.

        Args:
            folder_id: Database ID of the sync folder
            source_path: Path to the watched folder
            process_callback: Function to process PDF files
            move_after: Whether to move files after processing
        """
        self.folder_id = folder_id
        self.source_path = Path(source_path)
        self.process_callback = process_callback
        self.move_after = move_after
        self.processing = set()  # Track files currently being processed

    def on_created(self, event):
        """Called when a file is created."""
        if event.is_directory:
            return

        file_path = Path(event.src_path)

        # Only process PDF files
        if file_path.suffix.lower() != ".pdf":
            return

        # Wait a bit to ensure file is fully written
        time.sleep(1)

        # Check if file is accessible and not locked
        if not self._is_file_ready(file_path):
            logger.warning(f"File not ready or locked: {file_path}")
            return

        # Avoid processing the same file multiple times
        if str(file_path) in self.processing:
            return

        logger.info(f"New PDF detected: {file_path}")
        self.processing.add(str(file_path))

        try:
            self._process_file(file_path)
        finally:
            self.processing.discard(str(file_path))

    def _is_file_ready(self, file_path: Path, timeout: int = 5) -> bool:
        """
        Check if file is ready to be processed (not locked/being written).

        Args:
            file_path: Path to the file
            timeout: Maximum seconds to wait

        Returns:
            True if file is ready, False otherwise
        """
        if not file_path.exists():
            return False

        # Try to open file exclusively
        for _ in range(timeout):
            try:
                # Try to open in append mode to check if file is locked
                with file_path.open("rb") as f:
                    # Try to read first byte to ensure it's accessible
                    f.read(1)
                return True
            except (IOError, OSError, PermissionError):
                time.sleep(1)

        return False

    def _process_file(self, file_path: Path):
        """
        Process a PDF file using the callback.

        Args:
            file_path: Path to the PDF file
        """
        try:
            success = self.process_callback(file_path, self.folder_id)

            if success and self.move_after:
                # Move file to processed folder
                processed_dir = self.source_path / "processed"
                processed_dir.mkdir(exist_ok=True)

                dest_path = processed_dir / file_path.name
                # Handle name conflicts
                counter = 1
                while dest_path.exists():
                    dest_path = (
                        processed_dir / f"{file_path.stem}_{counter}{file_path.suffix}"
                    )
                    counter += 1

                file_path.rename(dest_path)
                logger.info(f"Moved processed file to: {dest_path}")

        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}", exc_info=True)


class SyncFolderService:
    """Service to manage folder syncing and file watching."""

    def __init__(self, db_path: Path, upload_dir: Path, thumbnails_dir: Path):
        """
        Initialize sync folder service.

        Args:
            db_path: Path to SQLite database
            upload_dir: Directory where uploaded files are stored
            thumbnails_dir: Directory where thumbnails are stored
        """
        self.db_path = db_path
        self.upload_dir = upload_dir
        self.thumbnails_dir = thumbnails_dir
        self.observers = {}  # folder_id -> Observer instance
        self.running = False

    def get_db_connection(self):
        """Create a database connection."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.row_factory = sqlite3.Row
        return conn

    def start(self):
        """Start watching all enabled sync folders."""
        if self.running:
            logger.warning("Sync service is already running")
            return

        logger.info("Starting sync folder service...")
        self.running = True

        # Load enabled folders from database
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, source_path, move_after_processing FROM sync_folders WHERE enabled = 1"
        )
        folders = cursor.fetchall()
        conn.close()

        # Start watching each folder
        for folder in folders:
            self._start_watching(
                folder["id"],
                folder["source_path"],
                bool(folder["move_after_processing"]),
            )

        logger.info(f"Started watching {len(folders)} sync folders")

    def stop(self):
        """Stop watching all folders."""
        if not self.running:
            return

        logger.info("Stopping sync folder service...")
        self.running = False

        # Stop all observers
        for observer in self.observers.values():
            observer.stop()
            observer.join(timeout=5)

        self.observers.clear()
        logger.info("Sync folder service stopped")

    def _start_watching(self, folder_id: int, source_path: str, move_after: bool):
        """
        Start watching a specific folder.

        Args:
            folder_id: Database ID of the sync folder
            source_path: Path to watch
            move_after: Whether to move files after processing
        """
        path = Path(source_path)

        if not path.exists():
            logger.error(f"Sync folder does not exist: {source_path}")
            return

        if not path.is_dir():
            logger.error(f"Sync path is not a directory: {source_path}")
            return

        # Stop existing observer if any
        if folder_id in self.observers:
            self.observers[folder_id].stop()
            self.observers[folder_id].join(timeout=5)

        # Create and start new observer
        event_handler = PDFHandler(
            folder_id, source_path, self._process_pdf, move_after
        )

        observer = Observer()
        observer.schedule(event_handler, str(path), recursive=False)
        observer.start()

        self.observers[folder_id] = observer
        logger.info(f"Started watching folder {folder_id}: {source_path}")

        # Update last_scan timestamp
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sync_folders SET last_scan = ? WHERE id = ?",
            (datetime.now().isoformat(), folder_id),
        )
        conn.commit()
        conn.close()

    def stop_watching(self, folder_id: int):
        """
        Stop watching a specific folder.

        Args:
            folder_id: Database ID of the sync folder
        """
        if folder_id in self.observers:
            self.observers[folder_id].stop()
            self.observers[folder_id].join(timeout=5)
            del self.observers[folder_id]
            logger.info(f"Stopped watching folder {folder_id}")

    def add_folder(
        self, source_path: str, enabled: bool = True, move_after: bool = False
    ) -> int:
        """
        Add a new sync folder.

        Args:
            source_path: Path to watch
            enabled: Whether to start watching immediately
            move_after: Whether to move files after processing

        Returns:
            ID of the created sync folder
        """
        conn = self.get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                INSERT INTO sync_folders (source_path, enabled, move_after_processing, created_date)
                VALUES (?, ?, ?, ?)
                """,
                (
                    source_path,
                    1 if enabled else 0,
                    1 if move_after else 0,
                    datetime.now().isoformat(),
                ),
            )
            folder_id = cursor.lastrowid
            conn.commit()

            if enabled and self.running:
                self._start_watching(folder_id, source_path, move_after)

            return folder_id

        finally:
            conn.close()

    def remove_folder(self, folder_id: int):
        """
        Remove a sync folder.

        Args:
            folder_id: Database ID of the sync folder
        """
        # Stop watching if active
        self.stop_watching(folder_id)

        # Remove from database
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sync_folders WHERE id = ?", (folder_id,))
        conn.commit()
        conn.close()

        logger.info(f"Removed sync folder {folder_id}")

    def enable_folder(self, folder_id: int):
        """Enable and start watching a folder."""
        conn = self.get_db_connection()
        cursor = conn.cursor()

        cursor.execute("UPDATE sync_folders SET enabled = 1 WHERE id = ?", (folder_id,))
        cursor.execute(
            "SELECT source_path, move_after_processing FROM sync_folders WHERE id = ?",
            (folder_id,),
        )
        row = cursor.fetchone()
        conn.commit()
        conn.close()

        if row and self.running:
            self._start_watching(
                folder_id, row["source_path"], bool(row["move_after_processing"])
            )

    def disable_folder(self, folder_id: int):
        """Disable and stop watching a folder."""
        self.stop_watching(folder_id)

        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE sync_folders SET enabled = 0 WHERE id = ?", (folder_id,))
        conn.commit()
        conn.close()

    def _process_pdf(self, file_path: Path, folder_id: int) -> bool:
        """
        Process a PDF file from a sync folder.

        This reuses the existing document processing pipeline.

        Args:
            file_path: Path to the PDF file
            folder_id: ID of the sync folder

        Returns:
            True if processing succeeded, False otherwise
        """
        try:
            # Import here to avoid circular dependencies
            try:
                from backend import storage
                from backend.main import generate_thumbnail
                from backend.main import get_db_connection as get_main_db_connection
                from backend.main import process_document
            except ModuleNotFoundError:
                import storage
                from main import (
                    generate_thumbnail,
                    process_document,
                    get_db_connection as get_main_db_connection,
                )
            import pypdf
            import pytesseract
            from pdf2image import convert_from_path

            logger.info(f"Processing PDF from sync folder {folder_id}: {file_path}")

            # Calculate file hash
            sha256_hash = hashlib.sha256()
            with file_path.open("rb") as f:
                while chunk := f.read(8192):
                    sha256_hash.update(chunk)
            file_hash = sha256_hash.hexdigest()

            # Check for duplicates
            conn = get_main_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, original_filename FROM documents WHERE file_hash = ?",
                (file_hash,),
            )
            duplicate = cursor.fetchone()
            conn.close()

            if duplicate:
                logger.warning(
                    f"Duplicate detected: {file_path.name} already exists as {duplicate['original_filename']}"
                )
                return False

            # Copy into staging; the destination folder depends on the category,
            # which is not known until the document has been processed.
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stored_filename = f"{timestamp}_{file_path.name}"
            staging = storage.staging_dir(self.upload_dir)
            staging.mkdir(parents=True, exist_ok=True)
            dest_path = staging / stored_filename

            with file_path.open("rb") as src, dest_path.open("wb") as dst:
                shutil.copyfileobj(src, dst)

            # Extract text from PDF
            try:
                reader = pypdf.PdfReader(dest_path)
                full_text = ""
                for page in reader.pages[:20]:
                    full_text += page.extract_text() + " "

                # OCR fallback for scanned documents
                if len(full_text.strip()) < 50:
                    logger.info("PDF appears scanned, attempting OCR...")
                    try:
                        images = convert_from_path(dest_path, dpi=300)
                        ocr_text = ""
                        for image in images[:20]:
                            page_text = pytesseract.image_to_string(
                                image, lang="eng+deu"
                            )
                            ocr_text += page_text + " "

                        if len(ocr_text.strip()) > len(full_text.strip()):
                            full_text = ocr_text
                            logger.info(f"OCR successful: {len(full_text)} characters")
                    except Exception as ocr_error:
                        logger.warning(f"OCR failed: {ocr_error}")

                text_preview = full_text[:2000]
            except Exception as e:
                text_preview = f"Error extracting text: {str(e)}"
                logger.error(f"Text extraction failed: {e}")

            # AI processing for tags and category
            tags, category = process_document(text_preview, file_path.name)

            # Move out of staging into uploads/<Category>/<Year>/
            upload_date = datetime.now().isoformat()
            try:
                dest_path, stored_filename = storage.place(
                    dest_path, self.upload_dir, category, upload_date, stored_filename
                )
            except OSError as exc:
                dest_path.unlink(missing_ok=True)
                logger.error(f"Could not store {file_path.name}: {exc}")
                return False

            # Generate thumbnail from the final location
            thumbnail_path = generate_thumbnail(dest_path, stored_filename)

            # Save to database
            conn = get_main_db_connection()
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
                        file_path.name,
                        stored_filename,
                        None,
                        dest_path.relative_to(self.upload_dir).as_posix(),
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
                # A concurrent sync event inserted the same hash after our pre-check.
                conn.close()
                dest_path.unlink(missing_ok=True)
                if thumbnail_path:
                    (self.thumbnails_dir / Path(thumbnail_path).name).unlink(
                        missing_ok=True
                    )
                logger.warning(
                    f"Duplicate detected (race): {file_path.name} already exists "
                    f"(hash={file_hash})"
                )
                return False
            conn.close()

            logger.info(
                f"Successfully processed {file_path.name} -> doc_id={doc_id}, "
                f"category={category}, tags={tags}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to process {file_path}: {e}", exc_info=True)
            return False

    def scan_folder(self, folder_id: int):
        """
        Manually scan a folder for existing PDF files.

        Args:
            folder_id: Database ID of the sync folder
        """
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT source_path FROM sync_folders WHERE id = ?", (folder_id,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            logger.error(f"Sync folder {folder_id} not found")
            return

        source_path = Path(row["source_path"])

        if not source_path.exists():
            logger.error(f"Folder does not exist: {source_path}")
            return

        # Find all PDF files
        pdf_files = list(source_path.glob("*.pdf"))
        logger.info(f"Found {len(pdf_files)} PDF files in {source_path}")

        # Process each file
        processed = 0
        for pdf_file in pdf_files:
            try:
                success = self._process_pdf(pdf_file, folder_id)
                if success:
                    processed += 1
            except Exception as e:
                logger.error(f"Error processing {pdf_file}: {e}")

        logger.info(
            f"Processed {processed}/{len(pdf_files)} files from folder {folder_id}"
        )

        # Update last_scan
        conn = self.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE sync_folders SET last_scan = ? WHERE id = ?",
            (datetime.now().isoformat(), folder_id),
        )
        conn.commit()
        conn.close()
