from pathlib import Path
import logging

# BASE_PATH = Path(__file__).resolve().parent
# LOG_PATH = BASE_PATH / "logs" / "pipeline.log"
# # Create log file if it doesn't exist
# LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def get_logger(
    log_file: Path,
    name: str = "pipeline",
    level: int = logging.INFO) -> logging.Logger:
	
	logger = logging.getLogger(name)
	logger.setLevel(level)
	
	# Prevent adding duplicate handlers if get_logger is called multiple times
	if not logger.handlers:
		formatter = logging.Formatter(
			fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
			datefmt="%Y-%m-%d %H:%M:%S"
		)
  
		file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
		file_handler.setFormatter(formatter)
		logger.addHandler(file_handler) 
	
	return logger