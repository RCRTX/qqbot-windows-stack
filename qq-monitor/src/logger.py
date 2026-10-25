"""QQ bot stack component."""




import os
import sys
import tempfile
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_LOG_DIR = os.path.join(BASE_DIR, "logs")


def setup_logger(name: str = "qq-monitor", log_dir: str = None,
                 level=logging.DEBUG) -> logging.Logger:
    """QQ bot stack component."""











    if log_dir is None:
        
        
        
        _argv0 = os.path.abspath(sys.argv[0] or "")
        _is_test = (os.sep + "tests" + os.sep) in _argv0
        if _is_test:
            log_dir = os.path.join(tempfile.gettempdir(), "qqmon-tests-logs")
        else:
            log_dir = os.environ.get("QQMON_LOG_DIR") or DEFAULT_LOG_DIR
    log_dir = os.path.abspath(log_dir)
    os.makedirs(log_dir, exist_ok=True)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    today = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(log_dir, f"monitor_{today}.log")

    if logger.handlers:
        if getattr(logger, "_qqmon_log_file", None) == log_file:
            return logger
        
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(console_fmt)
    logger.addHandler(console_handler)

    
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  
        backupCount=30,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    file_fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s [%(filename)s:%(lineno)d] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_fmt)
    logger.addHandler(file_handler)

    logger._qqmon_log_file = log_file
    return logger
