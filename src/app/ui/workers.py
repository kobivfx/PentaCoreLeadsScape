"""Background workers for pipeline execution via QThread."""
from __future__ import annotations

import logging
from threading import Event

from PySide6.QtCore import QObject, QThread, Signal

from ..core.db import DatabaseManager
from ..core.secrets_manager import SecretsManager
from ..pipeline.engine import PipelineEngine

log = logging.getLogger(__name__)


class PipelineWorker(QObject):
    """Runs the pipeline engine in a background thread."""
    progress = Signal(str, int)       # message, percent
    finished = Signal(str, str)       # run_id, status
    error = Signal(str)               # error message

    def __init__(self, db: DatabaseManager, secrets: SecretsManager,
                 dry_run: bool = False, mock_run: bool = False, group_ids: list = None):
        super().__init__()
        self._db = db
        self._secrets = secrets
        self._dry_run = dry_run
        self._mock_run = mock_run
        self._group_ids = group_ids or ["all"]
        self._cancel_event = Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        try:
            engine = PipelineEngine(
                db=self._db,
                secrets=self._secrets,
                cancel_event=self._cancel_event,
                progress_callback=self._on_progress,
                dry_run=self._dry_run,
                mock_run=self._mock_run,
                group_ids=self._group_ids,
            )
            run_id = engine.run()
            run = self._db.get_run(run_id)
            status = run.status if run else "unknown"
            self.finished.emit(run_id, status)
        except Exception as e:
            log.exception("Pipeline worker error")
            self.error.emit(str(e))

    def _on_progress(self, msg: str, pct: int):
        self.progress.emit(msg, pct)


def start_pipeline_worker(db: DatabaseManager, secrets: SecretsManager,
                          dry_run: bool = False, mock_run: bool = False, group_ids: list = None,
                          progress_slot=None, finished_slot=None,
                          error_slot=None) -> tuple[QThread, PipelineWorker]:
    """Create and start a pipeline worker thread. Returns (thread, worker)."""
    thread = QThread()
    worker = PipelineWorker(db, secrets, dry_run=dry_run, mock_run=mock_run, group_ids=group_ids)
    worker.moveToThread(thread)

    thread.started.connect(worker.run)
    if progress_slot:
        worker.progress.connect(progress_slot)
    if finished_slot:
        worker.finished.connect(finished_slot)
    if error_slot:
        worker.error.connect(error_slot)
    worker.finished.connect(thread.quit)
    worker.error.connect(thread.quit)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(worker.deleteLater)

    thread.start()
    return thread, worker
