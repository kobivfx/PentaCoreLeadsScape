"""CLI entry point: python -m app.pipeline --once"""
import argparse
import sys
from pathlib import Path
from threading import Event

src = str(Path(__file__).resolve().parents[1])
if src not in sys.path:
    sys.path.insert(0, src)

from app.core.config import DB_PATH
from app.core.db import DatabaseManager
from app.core.logging_config import setup_logging
from app.core.secrets_manager import SecretsManager
from app.pipeline.engine import PipelineEngine


def main():
    parser = argparse.ArgumentParser(description="LeadsScraper2 pipeline CLI")
    parser.add_argument("--once", action="store_true", help="Run pipeline once and exit")
    parser.add_argument("--dry-run", action="store_true", help="Dry run (no API calls)")
    parser.add_argument("--mock", action="store_true", help="Use mock data")
    args = parser.parse_args()

    if not args.once:
        parser.print_help()
        sys.exit(1)

    log_file = setup_logging()
    print(f"Log file: {log_file}")

    db = DatabaseManager(DB_PATH)
    secrets = SecretsManager(DB_PATH)

    def progress(msg, pct):
        print(f"[{pct:3d}%] {msg}" if pct >= 0 else f"      {msg}")

    engine = PipelineEngine(
        db=db,
        secrets=secrets,
        cancel_event=Event(),
        progress_callback=progress,
        dry_run=args.dry_run,
        mock_run=args.mock,
    )

    run_id = engine.run()
    run = db.get_run(run_id)
    print(f"\nPipeline finished: {run.status}" if run else "Pipeline finished")
    sys.exit(0 if run and run.status == "success" else 1)


if __name__ == "__main__":
    main()
