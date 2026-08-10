import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline.logger import get_logger
from pipeline.ingest import run_ingestion
from pipeline.transform import run_transformation

PIPELINE_LOG_PATH = BASE_DIR / "pipeline" / "logs" / "pipeline.log"

DATA_DIR = BASE_DIR / "data" 
DATA_PATH = DATA_DIR / "raw" / "app_logs_7days.jsonl"
QUARANTINE_PATH = DATA_DIR / "bronze" / "quarantine" / "malformed_records.jsonl"
BRONZE_VALID_PATH = DATA_DIR / "bronze" / "bronze_valid_records.jsonl"
SILVER_OUTPUT_PATH = DATA_DIR / "silver" / "silver_valid_records.parquet"

logger = get_logger('MainPipeline')

def main():
	logger.info("STARTING LOG PROCESSING PIPELINE")
	
	try:
		logger.info("--- Step 1: Ingesting Raw to Bronze ---")
		run_ingestion(
			DATA_PATH=str(DATA_PATH),
			QUARANTINE_PATH=str(QUARANTINE_PATH),
			VALID_OUTPUT_PATH=str(BRONZE_VALID_PATH),
			LOG_PATH=str(PIPELINE_LOG_PATH)
		)
  
		logger.info("--- Step 2: Transforming Bronze to Silver Parquet ---")
		run_transformation(
			BRONZE_INPUT_PATH=str(BRONZE_VALID_PATH),
			SILVER_OUTPUT_PATH=str(SILVER_OUTPUT_PATH),
			LOG_PATH=str(PIPELINE_LOG_PATH)
		)
  
		logger.info("--- Pipeline completed successfully!")
	
	except Exception as e:
		logger.error(f"Pipeline execution failed: {str(e)}", exc_info=True)
		sys.exit(1)
 
if __name__ == "__main__":
    main()
    



