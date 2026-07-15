"""Sandboxed download storage for SURF."""
import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from config.settings import settings
from core.foundation import BrowserOperationError, ValidationError
from utils.path_policy import is_allowed_export_path, resolve_export_directory

logger = structlog.get_logger()


class DownloadService:
    """Persist browser and fetch downloads inside a SURF-owned sandbox."""

    def __init__(self) -> None:
        self.root = self._path(settings.downloads_dir)
        self.index_path = self.root / "index.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    async def save_playwright_download(
        self,
        download: Any,
        filename: Optional[str] = None,
        output_dir: Optional[str] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        suggested = filename or download.suggested_filename or "download.bin"
        record = self._new_record(suggested, source_url=download.url, output_dir=output_dir, overwrite=overwrite)
        await download.save_as(record["path"])
        self._validate_size(Path(record["path"]))
        record["size_bytes"] = Path(record["path"]).stat().st_size
        self._add_record(record)
        return self._public_record(record)

    async def save_bytes(
        self,
        content: bytes,
        filename: Optional[str] = None,
        source_url: Optional[str] = None,
        content_type: Optional[str] = None,
        output_dir: Optional[str] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        if len(content) > settings.max_download_size_bytes:
            raise ValidationError("download", "Downloaded content exceeds configured maximum size")
        record = self._new_record(
            filename or self._filename_from_url(source_url) or "download.bin",
            source_url=source_url,
            output_dir=output_dir,
            overwrite=overwrite,
        )
        Path(record["path"]).write_bytes(content)
        record["size_bytes"] = len(content)
        record["content_type"] = content_type
        self._add_record(record)
        return self._public_record(record)

    def list_downloads(self) -> List[Dict[str, Any]]:
        with self._lock:
            self.reap_expired()
            return [self._public_record(record) for record in self._load_index().values()]

    def get_download(self, download_id: str) -> Dict[str, Any]:
        record = self._record(download_id)
        return self._public_record(record)

    def path_for(self, download_id: str) -> Path:
        record = self._record(download_id)
        path = Path(record["path"]).resolve()
        if record.get("external"):
            if not is_allowed_export_path(path):
                raise ValidationError("download_id", "External download path is outside configured export roots")
        elif not self._inside_root(path):
            raise ValidationError("download_id", "Download path is outside sandbox")
        return path

    def delete_download(self, download_id: str) -> Dict[str, Any]:
        with self._lock:
            records = self._load_index()
            record = records.pop(download_id, None)
            if not record:
                raise ValidationError("download_id", "Download not found")
            path = Path(record["path"])
            allowed = self._inside_root(path.resolve()) or (
                record.get("external") and is_allowed_export_path(path)
            )
            if allowed and path.exists():
                path.unlink()
            self._save_index(records)
            return {"deleted": True, "download_id": download_id}

    def reap_expired(self) -> Dict[str, Any]:
        with self._lock:
            records = self._load_index()
            cutoff = time.time() - settings.download_retention_seconds
            deleted = []
            for download_id, record in list(records.items()):
                if record.get("created_at_epoch", 0) < cutoff:
                    path = Path(record["path"])
                    if self._inside_root(path.resolve()) and path.exists():
                        path.unlink()
                    records.pop(download_id, None)
                    deleted.append(download_id)
            if deleted:
                self._save_index(records)
            return {"deleted": deleted, "count": len(deleted)}

    def _new_record(
        self,
        filename: str,
        source_url: Optional[str] = None,
        output_dir: Optional[str] = None,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        download_id = f"dl_{uuid.uuid4().hex[:12]}"
        safe_name = self._safe_filename(filename)
        external = bool(output_dir)
        if external:
            target_dir = self._requested_output_dir(output_dir)
            path = (target_dir / safe_name).resolve()
            if not is_allowed_export_path(path):
                raise ValidationError("output_dir", "Target file escapes configured export roots", str(path))
            if path.exists() and not overwrite:
                raise ValidationError("output_dir", "Target file already exists; set overwrite=true to replace it", str(path))
        else:
            path = (self.root / f"{download_id}_{safe_name}").resolve()
        if not external and not self._inside_root(path):
            raise ValidationError("filename", "Invalid download filename")
        return {
            "download_id": download_id,
            "filename": safe_name,
            "path": str(path),
            "absolute_path": str(path),
            "external": external,
            "source_url": source_url,
            "created_at_epoch": time.time(),
            "size_bytes": 0,
        }

    def _add_record(self, record: Dict[str, Any]) -> None:
        with self._lock:
            records = self._load_index()
            records[record["download_id"]] = record
            self._save_index(records)

    def _record(self, download_id: str) -> Dict[str, Any]:
        records = self._load_index()
        record = records.get(download_id)
        if not record:
            raise ValidationError("download_id", "Download not found")
        return record

    def _load_index(self) -> Dict[str, Dict[str, Any]]:
        if not self.index_path.exists():
            return {}
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("Download index unreadable; starting empty", error=str(e))
            return {}

    def _save_index(self, records: Dict[str, Dict[str, Any]]) -> None:
        tmp_path = self.index_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(records, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, self.index_path)

    def _validate_size(self, path: Path) -> None:
        if path.stat().st_size > settings.max_download_size_bytes:
            path.unlink(missing_ok=True)
            raise BrowserOperationError("download", "Downloaded file exceeds configured maximum size")

    def _public_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        public = dict(record)
        path = Path(record["path"]).resolve()
        public["absolute_path"] = str(path)
        public["path"] = str(path) if record.get("external") else os.path.relpath(path, Path(__file__).parent.parent)
        public["created_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record["created_at_epoch"]))
        return public

    def _safe_filename(self, filename: str) -> str:
        base = os.path.basename(filename or "download.bin")
        safe = "".join(c if c.isalnum() or c in (".", "-", "_") else "_" for c in base).strip("._")
        return safe[:180] or "download.bin"

    def _filename_from_url(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        name = os.path.basename(url.split("?", 1)[0].rstrip("/"))
        return name or None

    def _inside_root(self, path: Path) -> bool:
        try:
            path.relative_to(self.root.resolve())
            return True
        except ValueError:
            return False

    def _path(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = Path(__file__).parent.parent / path
        return path

    def _requested_output_dir(self, value: Optional[str]) -> Path:
        return resolve_export_directory(value or "")
