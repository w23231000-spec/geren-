"""Configures task-scoped console and file logging without global hidden state."""

import logging
from pathlib import Path


def build_logger(task_dir: Path) -> logging.Logger:
    logger = logging.getLogger(f"hfss_optimization_agent.{task_dir.name}")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        task_dir.mkdir(parents=True, exist_ok=True)
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        handler = logging.FileHandler(task_dir / "run.log", encoding="utf-8")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    return logger

