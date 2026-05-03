"""
Core backend: queue, workers, pipeline, cache, and JSON logging.

Intended consumers: Bot Agent (enqueue jobs), Downloader Agent (perform downloads
via injected handlers). Import stable symbols from this package.
"""

from services.dedupe_cache import CacheBackendError, DownloadCache
from services.downloader import (
    DownloadResult,
    GeoBlockedError,
    InvalidURLError,
    PrivateContentError,
    YtDlpDownloadError,
    cleanup_work_dir,
    default_ytdlp_config_path,
    download_audio,
    download_video,
)
from services.logging_config import setup_json_logging, get_logger
from services.pipeline import TaskPipeline
from services.queue_manager import JobQueueManager, QueueOverflowError, QueueClosedError
from services.remote_backend import (
    api_base_env,
    build_download_processor,
    execute_remote_download,
)
from services.types import Job, JobStatus, TaskResult
from services.worker import Worker, WorkerPool, JobProcessor

__all__ = [
    "CacheBackendError",
    "DownloadCache",
    "DownloadResult",
    "GeoBlockedError",
    "InvalidURLError",
    "PrivateContentError",
    "YtDlpDownloadError",
    "cleanup_work_dir",
    "default_ytdlp_config_path",
    "download_audio",
    "download_video",
    "Job",
    "JobProcessor",
    "JobQueueManager",
    "JobStatus",
    "QueueClosedError",
    "QueueOverflowError",
    "TaskPipeline",
    "TaskResult",
    "Worker",
    "WorkerPool",
    "api_base_env",
    "build_download_processor",
    "execute_remote_download",
    "get_logger",
    "setup_json_logging",
]
