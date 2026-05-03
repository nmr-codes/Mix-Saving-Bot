from core.contracts.types import JobRecord


def fmt_queued(job_id: str) -> str:
    return f"Queued download (job {job_id[:8]}…). This may take a minute."


def fmt_busy() -> str:
    return "The download queue is busy. Please try again in a moment."


def fmt_timeout() -> str:
    return "Download timed out. Try again with a shorter clip."


def fmt_failed(record: JobRecord) -> str:
    msg = record.get("error_message_safe") or "Download failed."
    code = record.get("error_code", "")
    if code:
        return f"{msg} [{code}]"
    return msg
