"""로그 설정과 치명적 오류 기록.

- logs/trendchecker-YYYYMMDD.log : 일반 로그(INFO 이상)
- logs/error-YYYYMMDD.log        : 오류와 처리되지 않은 예외의 traceback
오래된 로그는 keep_days 이후 삭제한다.
"""
from __future__ import annotations

import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT

LOG_DIR = ROOT / "logs"
_configured = False


def setup_logging(log_dir: Path | None = None, keep_days: int = 14, verbose: bool = False) -> Path:
    global _configured
    d = log_dir or LOG_DIR
    d.mkdir(parents=True, exist_ok=True)
    if _configured:
        return d
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    root.addHandler(console)

    general = logging.FileHandler(d / f"trendchecker-{stamp}.log", encoding="utf-8")
    general.setFormatter(fmt)
    general.setLevel(logging.INFO)
    root.addHandler(general)

    errors = logging.FileHandler(d / f"error-{stamp}.log", encoding="utf-8")
    errors.setFormatter(fmt)
    errors.setLevel(logging.ERROR)
    root.addHandler(errors)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    def _excepthook(exc_type, exc, tb):  # pragma: no cover - 프로세스 종료 직전 동작
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logging.getLogger("trendchecker").critical(
            "처리되지 않은 예외로 종료:\n%s", "".join(traceback.format_exception(exc_type, exc, tb))
        )

    sys.excepthook = _excepthook
    _prune(d, keep_days)
    _configured = True
    return d


def _prune(d: Path, keep_days: int) -> None:
    cutoff = time.time() - keep_days * 86400
    for f in d.glob("*.log"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
        except OSError:
            pass
