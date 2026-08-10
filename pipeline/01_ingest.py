
from pipeline.logger import get_logger 
import json

logger = get_logger("IngestBronze")

def run_ingestion(DATA_PATH: str, QUARANTINE_PATH: str, VALID_OUTPUT_PATH: str):
	"""
	Description: Raw to Bronze layer 
	Goal: Isolate malformed JSON from valid JSON with zero data loss
	Transformation: None
	"""
	
	logger.info("Starting data ingestion process...")
	
	success_count = 0
	error_count = 0
 
	with open(DATA_PATH, mode='r', encoding='utf-8') as f_in, \
		open(VALID_OUTPUT_PATH, mode="w", encoding="utf-8") as f_valid, \
		open(QUARANTINE_PATH, mode='w', encoding='utf-8') as f_err:
			for line_num, line in enumerate(f_in, start=1):
				raw_line = line.strip()
				if not raw_line:
					logger.warning(f"Line {line_num}: Empty line found. Skipping.")
					continue
				
				try:
					record = json.loads(raw_line)
					success_count += 1
					# Write valid JSON object as a line in the new JSONL file
					f_valid.write(json.dumps(record) + "\n")
				except json.JSONDecodeError as e:
					error_count += 1
					malformed_record = {
						"source_file": str(DATA_PATH),
						"line_number": line_num,
						"raw_line": raw_line,
						"error_message": str(e)
					}
					f_err.write(json.dumps(malformed_record) + "\n")
					logger.error(f"Line {line_num}: JSONDecodeError: {e.msg}. Writing to quarantine.")

	logger.info(f"Valid records saved: {success_count} -> {VALID_OUTPUT_PATH}")
	logger.info(f"Malformed records saved: {error_count} -> {QUARANTINE_PATH}")
	logger.info("Data ingestion process completed.")
