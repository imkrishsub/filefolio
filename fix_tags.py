#!/usr/bin/env python3
"""
Script to fix documents that have category names as tags.
Re-processes affected documents using the updated AI prompt.
"""

import json
import sqlite3
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from backend.main import process_document, get_db_connection, DB_PATH
import pypdf

# Category names and generic terms that shouldn't be used as tags
CATEGORY_NAMES = {
    "invoice", "receipt", "contract", "letter", "report",
    "form", "statement", "legal", "medical", "tax", "insurance", "other",
    "document", "file", "pdf"
}

def has_category_tag(tags_json):
    """Check if tags contain any category names."""
    try:
        tags = json.loads(tags_json)
        return any(tag.lower() in CATEGORY_NAMES for tag in tags)
    except (json.JSONDecodeError, TypeError):
        return False

def extract_text_from_pdf(file_path):
    """Extract text from PDF for re-processing."""
    try:
        reader = pypdf.PdfReader(file_path)
        text = ""
        for page in reader.pages[:5]:  # First 5 pages
            text += page.extract_text() + " "
        return text[:2000]  # First 2000 chars
    except Exception as e:
        print(f"Error extracting text from {file_path}: {e}")
        return ""

def fix_document_tags(doc_id, original_filename, file_path, old_tags):
    """Re-process a document to fix its tags."""
    print(f"\nProcessing: {original_filename}")
    print(f"  Old tags: {old_tags}")

    # Extract text from PDF
    text = extract_text_from_pdf(file_path)
    if not text:
        print(f"  ⚠️  Could not extract text, skipping")
        return False

    # Re-process with AI
    try:
        new_tags, new_category = process_document(text, original_filename)

        # Check if new tags are better (don't contain category names)
        if any(tag.lower() in CATEGORY_NAMES for tag in new_tags):
            print(f"  ⚠️  AI still generated category tags: {new_tags}, skipping")
            return False

        print(f"  New tags: {new_tags}")
        print(f"  Category: {new_category}")

        # Update database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE documents SET tags = ?, category = ? WHERE id = ?",
            (json.dumps(new_tags), new_category, doc_id)
        )
        conn.commit()
        conn.close()

        print(f"  ✅ Updated successfully")
        return True

    except Exception as e:
        print(f"  ❌ Error: {e}")
        return False

def main():
    """Main function to fix all affected documents."""
    print("Finding documents with category names as tags...")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Find affected documents
    cursor.execute("""
        SELECT id, original_filename, file_path, tags, category
        FROM documents
        ORDER BY id
    """)

    all_docs = cursor.fetchall()
    conn.close()

    # Filter to those with category tags
    affected_docs = []
    for doc in all_docs:
        if has_category_tag(doc["tags"]):
            affected_docs.append(doc)

    print(f"\nFound {len(affected_docs)} documents with category names as tags")

    if not affected_docs:
        print("No documents to fix!")
        return

    # Ask for confirmation
    response = input(f"\nProceed to fix {len(affected_docs)} documents? (y/n): ")
    if response.lower() != 'y':
        print("Aborted")
        return

    # Process each document
    fixed = 0
    skipped = 0

    for doc in affected_docs:
        success = fix_document_tags(
            doc["id"],
            doc["original_filename"],
            doc["file_path"],
            doc["tags"]
        )
        if success:
            fixed += 1
        else:
            skipped += 1

    print(f"\n" + "="*60)
    print(f"Summary:")
    print(f"  Fixed: {fixed}")
    print(f"  Skipped: {skipped}")
    print(f"  Total: {len(affected_docs)}")
    print("="*60)

if __name__ == "__main__":
    main()
