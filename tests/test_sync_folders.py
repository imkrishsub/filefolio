"""
Tests for sync folder functionality.
"""

import inspect
import pytest
from pathlib import Path
from backend.main import app
from backend.sync_service import PDFHandler, SyncFolderService
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

    # --- Create edge cases ---

    def test_create_sync_folder_path_is_file(self, client):
        """Test creating sync folder where path points to a file returns 400."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "not_a_dir.txt"
            file_path.write_text("hello")
            response = client.post(
                "/sync-folders",
                json={"source_path": str(file_path)}
            )
            assert response.status_code == 400
            assert "not a directory" in response.json()["detail"]

    def test_create_sync_folder_disabled(self, client):
        """Test creating a sync folder with enabled=False stores it disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            response = client.post(
                "/sync-folders",
                json={"source_path": tmpdir, "enabled": False, "move_after_processing": False}
            )
            assert response.status_code == 200
            folder_id = response.json()["id"]

            folders = client.get("/sync-folders").json()
            folder = next(f for f in folders if f["id"] == folder_id)
            assert folder["enabled"] is False

    def test_create_sync_folder_move_after_processing(self, client):
        """Test creating a sync folder with move_after_processing=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            response = client.post(
                "/sync-folders",
                json={"source_path": tmpdir, "enabled": True, "move_after_processing": True}
            )
            assert response.status_code == 200
            folder_id = response.json()["id"]

            folders = client.get("/sync-folders").json()
            folder = next(f for f in folders if f["id"] == folder_id)
            assert folder["move_after_processing"] is True

    # --- GET response shape ---

    def test_list_sync_folders_response_fields(self, client):
        """Test that GET /sync-folders returns all expected fields with correct types."""
        with tempfile.TemporaryDirectory() as tmpdir:
            create = client.post(
                "/sync-folders",
                json={"source_path": tmpdir, "enabled": True, "move_after_processing": False}
            )
            folder_id = create.json()["id"]

            folders = client.get("/sync-folders").json()
            folder = next(f for f in folders if f["id"] == folder_id)

            assert isinstance(folder["id"], int)
            assert folder["source_path"] == tmpdir
            assert isinstance(folder["enabled"], bool)
            assert isinstance(folder["move_after_processing"], bool)
            assert "created_date" in folder
            assert "last_scan" in folder
            assert "is_watching" in folder

    def test_list_multiple_sync_folders(self, client):
        """Test that GET /sync-folders returns all created folders."""
        with tempfile.TemporaryDirectory() as dir1, \
             tempfile.TemporaryDirectory() as dir2:
            id1 = client.post("/sync-folders", json={"source_path": dir1}).json()["id"]
            id2 = client.post("/sync-folders", json={"source_path": dir2}).json()["id"]

            folder_ids = {f["id"] for f in client.get("/sync-folders").json()}
            assert id1 in folder_ids
            assert id2 in folder_ids

    # --- Update edge cases ---

    def test_update_move_after_processing(self, client):
        """Test updating move_after_processing field."""
        with tempfile.TemporaryDirectory() as tmpdir:
            folder_id = client.post(
                "/sync-folders",
                json={"source_path": tmpdir, "enabled": True, "move_after_processing": False}
            ).json()["id"]

            response = client.put(
                f"/sync-folders/{folder_id}",
                json={"move_after_processing": True}
            )
            assert response.status_code == 200
            assert response.json()["success"] is True

            folder = next(
                f for f in client.get("/sync-folders").json() if f["id"] == folder_id
            )
            assert folder["move_after_processing"] is True

    def test_update_re_enable_folder(self, client):
        """Test re-enabling a previously disabled sync folder."""
        with tempfile.TemporaryDirectory() as tmpdir:
            folder_id = client.post(
                "/sync-folders",
                json={"source_path": tmpdir, "enabled": False}
            ).json()["id"]

            client.put(f"/sync-folders/{folder_id}", json={"enabled": False})

            response = client.put(f"/sync-folders/{folder_id}", json={"enabled": True})
            assert response.status_code == 200

            folder = next(
                f for f in client.get("/sync-folders").json() if f["id"] == folder_id
            )
            assert folder["enabled"] is True

    def test_update_both_fields(self, client):
        """Test updating enabled and move_after_processing in a single PUT."""
        with tempfile.TemporaryDirectory() as tmpdir:
            folder_id = client.post(
                "/sync-folders",
                json={"source_path": tmpdir, "enabled": True, "move_after_processing": False}
            ).json()["id"]

            response = client.put(
                f"/sync-folders/{folder_id}",
                json={"enabled": False, "move_after_processing": True}
            )
            assert response.status_code == 200

            folder = next(
                f for f in client.get("/sync-folders").json() if f["id"] == folder_id
            )
            assert folder["enabled"] is False
            assert folder["move_after_processing"] is True

    def test_update_no_fields_is_noop(self, client):
        """Test PUT with no fields set is a no-op and still returns success."""
        with tempfile.TemporaryDirectory() as tmpdir:
            folder_id = client.post(
                "/sync-folders",
                json={"source_path": tmpdir, "enabled": True, "move_after_processing": False}
            ).json()["id"]

            response = client.put(f"/sync-folders/{folder_id}", json={})
            assert response.status_code == 200
            assert response.json()["success"] is True

            folder = next(
                f for f in client.get("/sync-folders").json() if f["id"] == folder_id
            )
            assert folder["enabled"] is True
            assert folder["move_after_processing"] is False

    # --- Response body completeness ---

    def test_scan_response_success_field(self, client):
        """Test that scan response includes success: True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            folder_id = client.post(
                "/sync-folders", json={"source_path": tmpdir}
            ).json()["id"]

            response = client.post(f"/sync-folders/{folder_id}/scan")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["message"] == "Folder scan started"

    def test_delete_response_fields(self, client):
        """Test that delete response includes success and message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            folder_id = client.post(
                "/sync-folders", json={"source_path": tmpdir}
            ).json()["id"]

            response = client.delete(f"/sync-folders/{folder_id}")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "message" in data

    def test_update_response_message(self, client):
        """Test that update response includes the expected message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            folder_id = client.post(
                "/sync-folders", json={"source_path": tmpdir}
            ).json()["id"]

            response = client.put(f"/sync-folders/{folder_id}", json={"enabled": False})
            assert response.status_code == 200
            assert response.json()["message"] == "Sync folder updated successfully"


class TestSyncServiceNotCoroutine:
    """
    T009: _process_pdf and _process_file must be plain callables, not coroutines.
    asyncio.run() from watchdog/background threads creates a new event loop per call
    and raises RuntimeError if ever called from within an existing event loop.
    Since both functions do purely synchronous I/O, there is no need for async at all.
    """

    def test_process_pdf_is_not_a_coroutine(self):
        """SyncFolderService._process_pdf must be a regular function."""
        assert not inspect.iscoroutinefunction(SyncFolderService._process_pdf)

    def test_process_file_is_not_a_coroutine(self):
        """PDFHandler._process_file must be a regular function."""
        assert not inspect.iscoroutinefunction(PDFHandler._process_file)

    def test_scan_folder_callable_without_event_loop(self, tmp_path):
        """scan_folder must be callable from a context with no running event loop."""
        import asyncio
        import threading

        svc = SyncFolderService(
            db_path=tmp_path / "test.db",
            upload_dir=tmp_path / "uploads",
            thumbnails_dir=tmp_path / "thumbnails",
        )
        (tmp_path / "uploads").mkdir()
        (tmp_path / "thumbnails").mkdir()

        # Calling scan_folder on a folder that doesn't exist in DB is a no-op,
        # but must NOT raise RuntimeError about event loops.
        raised = []

        def run():
            try:
                svc.scan_folder(9999)
            except RuntimeError as e:
                raised.append(e)

        t = threading.Thread(target=run)
        t.start()
        t.join(timeout=5)
        assert not raised, f"scan_folder raised RuntimeError: {raised[0]}"
