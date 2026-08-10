from pathlib import Path
import logging

DEFAULT_LOG_PATH = Path(__file__).resolve().parent / "logs" / "pipeline.log"

def get_logger(
    name: str = "pipeline",
    log_file: Path | str | None = None,
    level: int = logging.INFO) -> logging.Logger:
	
	logger = logging.getLogger(name)
	logger.setLevel(level)
	
	# Prevent adding duplicate handlers if get_logger is called multiple times
	if not logger.handlers:
		formatter = logging.Formatter(
			fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
			datefmt="%Y-%m-%d %H:%M:%S"
		)
  
		target_log_file = Path(log_file) if log_file is not None else DEFAULT_LOG_PATH
		target_log_file.parent.mkdir(parents=True, exist_ok=True)
  
		file_handler = logging.FileHandler(target_log_file, mode="a", encoding="utf-8")
		file_handler.setFormatter(formatter)
		logger.addHandler(file_handler) 
	
	return logger