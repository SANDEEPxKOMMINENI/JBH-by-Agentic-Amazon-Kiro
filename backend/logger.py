"""
@file purpose: Centralized logging system for the Democratized backend
This module provides unified logging that writes to both local files and
BetterStack. It handles Python backend logs, errors, and system events
with proper formatting.
"""

import json
import logging
import logging.handlers
import os
import queue
import sys  # noqa: E402
import threading  # noqa: E402
import traceback  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Dict, Optional  # noqa: E402

import requests  # noqa: E402


class BetterStackHandler(logging.Handler):
    """Custom logging handler that sends logs to BetterStack"""

    def __init__(self, source_token: str, ingesting_host: str):
        super().__init__()
        self.source_token = source_token
        self.ingesting_host = ingesting_host
        self.url = f"https://{ingesting_host}/logs"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {source_token}",
                "Content-Type": "application/json",
            }
        )

        # User email tracking (like v1)
        self.user_email = "Unknown"

        # Error tracking to avoid spam
        self.auth_error_logged = False
        self.error_count = 0

        # Queue for async logging
        self.log_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

    def update_user_email(self, user_email: str):
        """Update the user email for all future logs"""
        self.user_email = user_email

    def emit(self, record):
        """Send log record to BetterStack"""
        try:
            # Format the log entry
            log_entry = {
                "timestamp": datetime.fromtimestamp(record.created).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": self.format(record),
                "module": record.module,
                "function": record.funcName,
                "line": record.lineno,
                "process": "backend",
                "app": "jobhuntr",
                "user_email": self.user_email,  # Add user email like v1
            }

            # Add exception info if present
            if record.exc_info:
                log_entry["exception"] = traceback.format_exception(*record.exc_info)

            # Add to queue for async processing
            self.log_queue.put(log_entry)

        except Exception as e:
            # Fallback to stderr if BetterStack fails
            print(f"Failed to queue log for BetterStack: {e}", file=sys.stderr)

    def _worker(self):
        """Background worker to send logs to BetterStack"""
        while True:
            try:
                # Get log entry from queue (blocks until available)
                log_entry = self.log_queue.get(timeout=1)

                # Send to BetterStack
                response = self.session.post(self.url, json=log_entry, timeout=5)

                if response.status_code not in [200, 202]:
                    # Handle 401 Unauthorized specially (token issue)
                    if response.status_code == 401:
                        if not self.auth_error_logged:
                            print(
                                "\nWARNING: BetterStack Authentication Failed "
                                "(401 Unauthorized)",
                                file=sys.stderr,
                            )
                            print(
                                f"   Token: {self.source_token[:10]}...",
                                file=sys.stderr,
                            )
                            print(
                                f"   Host: {self.ingesting_host}",
                                file=sys.stderr,
                            )
                            print(
                                "   Please verify your BetterStack source token "
                                "and host.",
                                file=sys.stderr,
                            )
                            print(
                                "   Logs will continue to be written locally.\n",
                                file=sys.stderr,
                            )
                            self.auth_error_logged = True
                    else:
                        # Log other errors (but limit to avoid spam)
                        self.error_count += 1
                        if self.error_count <= 3:
                            print(
                                "BetterStack logging failed: "
                                f"{response.status_code} - {response.text}",
                                file=sys.stderr,
                            )
                        elif self.error_count == 4:
                            print(
                                "(Suppressing further BetterStack errors...)",
                                file=sys.stderr,
                            )

                self.log_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                self.error_count += 1
                if self.error_count <= 3:
                    print(f"BetterStack worker error: {e}", file=sys.stderr)


class DemocratizedLogger:
    """Main logger class for the Democratized application"""

    def __init__(
        self,
        log_file_path: str = None,
        betterstack_token: str = None,
        betterstack_host: str = None,
    ):
        # Set up log file path
        if log_file_path is None:
            log_dir = (
                Path.home() / "Library" / "Application Support" / "jobhuntr" / "logs"
            )
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file_path = log_dir / "jobhuntr.log"

        self.log_file_path = Path(log_file_path)
        self.log_file_path.parent.mkdir(parents=True, exist_ok=True)

        # Create main logger - use root logger so all child loggers inherit handlers
        self.logger = logging.getLogger()
        self.logger.setLevel(logging.DEBUG)

        # Silence noisy third-party loggers
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("azure").setLevel(logging.WARNING)

        # Only clear and re-add handlers if this is the first initialization
        # Check if we already have our custom handlers
        has_our_handlers = any(
            isinstance(h, (logging.handlers.RotatingFileHandler, BetterStackHandler))
            for h in self.logger.handlers
        )

        # Store reference to BetterStack handler for user email updates
        self.betterstack_handler = None

        if has_our_handlers:
            # Already initialized, just find and store the BetterStack handler
            for handler in self.logger.handlers:
                if isinstance(handler, BetterStackHandler):
                    self.betterstack_handler = handler
                    break
            return

        # Create formatters
        file_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)-20s | %(funcName)-15s:%(lineno)-4d | %(message)s",  # noqa: E501
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        console_formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S"
        )

        # File handler (rotates at 10MB) with UTF-8 encoding
        file_handler = logging.handlers.RotatingFileHandler(
            self.log_file_path,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)

        # Console handler with UTF-8 encoding for Windows
        if sys.platform == "win32":
            import io

            console_stream = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace"
            )
        else:
            console_stream = sys.stdout

        console_handler = logging.StreamHandler(console_stream)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)

        # BetterStack handler
        if betterstack_token and betterstack_host:
            try:
                self.betterstack_handler = BetterStackHandler(
                    betterstack_token, betterstack_host
                )
                self.betterstack_handler.setLevel(logging.INFO)
                self.betterstack_handler.setFormatter(file_formatter)
                self.logger.addHandler(self.betterstack_handler)
                self.logger.info("BetterStack logging initialized successfully")
            except Exception as e:
                self.logger.error(f"Failed to initialize BetterStack logging: {e}")

        # Log startup
        self.logger.info("=" * 80)
        self.logger.info("Democratized Backend Logger Initialized")
        self.logger.info(f"Log file: {self.log_file_path}")
        self.logger.info(f"Python version: {sys.version}")
        self.logger.info(f"Working directory: {os.getcwd()}")
        self.logger.info("=" * 80)

    def get_logger(self, name: str = None) -> logging.Logger:
        """Get a logger instance - all loggers inherit from root"""
        if name:
            return logging.getLogger(name)
        return self.logger

    def log_system_info(self):
        """Log system information"""
        import platform  # noqa: E402

        self.logger.info("System Information:")
        self.logger.info(f"  Platform: {platform.platform()}")
        python_version = platform.python_version()
        self.logger.info(f"  Python: {python_version}")

        # Try to import psutil, but don't fail if it's not available
        # or has architecture issues
        try:
            import psutil  # noqa: E402

            self.logger.info(f"  CPU cores: {psutil.cpu_count()}")
            memory_gb = psutil.virtual_memory().total / (1024**3)
            self.logger.info(f"  Memory: {memory_gb:.1f} GB")
        except ImportError as e:
            self.logger.warning(
                "  System metrics unavailable (psutil import failed): " f"{e}"
            )
        except Exception as e:
            self.logger.warning(f"  System metrics unavailable (psutil error): {e}")

    def log_exception(self, exception: Exception, context: str = ""):
        """Log an exception with full traceback"""
        self.logger.error(f"Exception in {context}: {str(exception)}")
        self.logger.error(f"Traceback: {traceback.format_exc()}")

    def log_frontend_message(
        self, level: str, message: str, data: Dict[str, Any] = None
    ):
        """Log a message from the frontend"""  # noqa: E402
        frontend_logger = self.get_logger("frontend")
        log_level = getattr(logging, level.upper(), logging.INFO)

        if data:
            message = f"{message} | Data: {json.dumps(data, default=str)}"

        frontend_logger.log(log_level, message)

    def update_user_email(self, user_email: str):
        """Update user email for BetterStack logs (like v1)"""
        if self.betterstack_handler:
            self.betterstack_handler.update_user_email(user_email)

    def _load_user_email_from_auth_file(self):
        """Load user email from JWT auth file if it exists"""
        try:
            from constants import BASE_DIR  # noqa: E402

            auth_file = Path(BASE_DIR) / "user_auth.json"
            if auth_file.exists():
                with open(auth_file, "r") as f:
                    auth_data = json.load(f)
                    user_info = auth_data.get("user_info", {})
                    email = user_info.get("email") or user_info.get(
                        "user_metadata", {}
                    ).get("email")
                    if email:
                        self.update_user_email(email)
                        self.logger.info(f"Loaded user email from auth file: {email}")
        except Exception as e:
            self.logger.debug(f"Could not load user email from auth file: {e}")


# Global logger instance
_global_logger: Optional[DemocratizedLogger] = None


def initialize_logging(
    betterstack_token: str = None, betterstack_host: str = None
) -> DemocratizedLogger:
    """Initialize the global logging system"""
    global _global_logger

    if _global_logger is None:
        _global_logger = DemocratizedLogger(
            betterstack_token=betterstack_token, betterstack_host=betterstack_host
        )

        # Log system info
        _global_logger.log_system_info()

        # Try to load user email from JWT auth file
        _global_logger._load_user_email_from_auth_file()

    return _global_logger


def get_logger(name: str = None) -> logging.Logger:
    """Get a logger instance"""
    if _global_logger is None:
        initialize_logging()
    return _global_logger.get_logger(name)


def log_exception(exception: Exception, context: str = ""):
    """Log an exception"""
    if _global_logger is None:
        initialize_logging()
    _global_logger.log_exception(exception, context)


def log_frontend_message(level: str, message: str, data: Dict[str, Any] = None):
    """Log a message from the frontend"""  # noqa: E402
    if _global_logger is None:
        initialize_logging()
    _global_logger.log_frontend_message(level, message, data)


def update_user_email(user_email: str):
    """Update user email for all future logs (like v1)"""
    if _global_logger is None:
        initialize_logging()
    _global_logger.update_user_email(user_email)
