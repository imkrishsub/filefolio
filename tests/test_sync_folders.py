"""
Tests for sync folder functionality.
"""

import pytest
from pathlib import Path
from backend.main import app
import tempfile
import shutil


class TestSyncFoldersAPI:
    """Test sync folder REST API endpoints."""

    def test_get_empty_sync_folders(self, client):
        """Test getting sync folders when none exist."""
        response = client.get("/sync-folders")
        assert response.status_code == 200
        folders = response.json()
        assert isinstance(folders, list)

    def test_create_sync_folder(self, client):
        """Test creating a new sync folder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            response = client.post(
                "/sync-folders",
                json={
                    "source_path": tmpdir,
                    "enabled": True,
                    "move_after_processing": False
                }
            )
            assert response.status_code == 200
            data = response.json()
            assert "id" in data
            assert data["message"] == "Sync folder added successfully"

    def test_create_sync_folder_nonexistent_path(self, client):
        """Test creating sync folder with nonexistent path fails."""
        response = client.post(
            "/sync-folders",
            json={
                "source_path": "/nonexistent/path/that/does/not/exist",
                "enabled": True,
                "move_after_processing": False
            }
        )
        assert response.status_code == 400
        assert "does not exist" in response.json()["detail"]

    def test_create_duplicate_sync_folder(self, client):
        """Test creating duplicate sync folder fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create first folder
            response1 = client.post(
                "/sync-folders",
                json={"source_path": tmpdir, "enabled": True, "move_after_processing": False}
            )
            assert response1.status_code == 200

            # Try to create duplicate
            response2 = client.post(
                "/sync-folders",
                json={"source_path": tmpdir, "enabled": True, "move_after_processing": False}
            )
            assert response2.status_code == 400
            assert "already being synced" in response2.json()["detail"]

    def test_update_sync_folder(self, client):
        """Test updating sync folder settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create folder
            create_response = client.post(
                "/sync-folders",
                json={"source_path": tmpdir, "enabled": True, "move_after_processing": False}
            )
            folder_id = create_response.json()["id"]

            # Update folder - disable it
            update_response = client.put(
                f"/sync-folders/{folder_id}",
                json={"enabled": False}
            )
            assert update_response.status_code == 200
            assert update_response.json()["success"] is True

            # Verify update
            folders = client.get("/sync-folders")
            folder = next((f for f in folders.json() if f["id"] == folder_id), None)
            assert folder is not None
            assert folder["enabled"] is False

    def test_delete_sync_folder(self, client):
        """Test deleting a sync folder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create folder
            create_response = client.post(
                "/sync-folders",
                json={"source_path": tmpdir, "enabled": True, "move_after_processing": False}
            )
            folder_id = create_response.json()["id"]

            # Delete folder
            delete_response = client.delete(f"/sync-folders/{folder_id}")
            assert delete_response.status_code == 200
            assert delete_response.json()["success"] is True

            # Verify deletion
            folders = client.get("/sync-folders")
            folder = next((f for f in folders.json() if f["id"] == folder_id), None)
            assert folder is None

    def test_scan_sync_folder(self, client):
        """Test manual scan of sync folder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create folder
            create_response = client.post(
                "/sync-folders",
                json={"source_path": tmpdir, "enabled": True, "move_after_processing": False}
            )
            folder_id = create_response.json()["id"]

            # Scan folder
            scan_response = client.post(f"/sync-folders/{folder_id}/scan")
            assert scan_response.status_code == 200
            assert scan_response.json()["message"] == "Folder scan started"

    def test_update_nonexistent_folder(self, client):
        """Test updating nonexistent folder returns 404."""
        response = client.put(
            "/sync-folders/99999",
            json={"enabled": False}
        )
        assert response.status_code == 404

    def test_delete_nonexistent_folder(self, client):
        """Test deleting nonexistent folder returns 404."""
        response = client.delete("/sync-folders/99999")
        assert response.status_code == 404

    def test_scan_nonexistent_folder(self, client):
        """Test scanning nonexistent folder returns 404."""
        response = client.post("/sync-folders/99999/scan")
        assert response.status_code == 404
