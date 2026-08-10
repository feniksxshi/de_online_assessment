from pipeline.logger import get_logger
from pipeline.data_quality import SilverLogSchema
import pandera as pa
import pandas as pd

logger = get_logger("SilverCleaning")
LOG_SOURCE_COLUMNS = [
    "timestamp",
    "service",
    "level",
    "message",
    "request_id",
    "trace_id",
]

def run_transformation(BRONZE_INPUT_PATH: str, SILVER_OUTPUT_PATH: str):
	"""
	Description: Bronze to Silver layer 
	Goal: Transform data
	Transformation: Yes
	"""	
	# 1. Read Bronze
	logger.info("Reading Bronze data")
	df = pd.read_json(BRONZE_INPUT_PATH, lines=True)
	logger.info(f"Bronze records: {len(df)}")
	
	missing_cols = set(LOG_SOURCE_COLUMNS) - set(df.columns)
	if missing_cols:
		raise ValueError(
			f"Missing required columns: {missing_cols}"
		)
	
	# 2. Dedup 
	logger.info("Removing complete duplicate records")
	len_before_dup = len(df)
	df = df.drop_duplicates(
		subset=LOG_SOURCE_COLUMNS,
		keep="first"
	)
	logger.info(f"Removed {len_before_dup - len(df)} duplicate records")
	
	# 3. Timestamp transformation
	df['event_timestamp_utc0'] = pd.to_datetime(
		df['timestamp'],
		utc=True,
		errors="coerce"
	)
	
	df['is_event_corrupted'] = (df['event_timestamp_utc0'].isna())
	
	# Forward-fill 'not-a-date' timestamp
	df['event_timestamp_utc0'] = (df['event_timestamp_utc0'].ffill())
	
	df['event_date_utc0'] = (df['event_timestamp_utc0'].dt.date)
 
	# 4. Level transformation
	level_impute_msk = (
		df["level"].isna()
		& df["message"].eq("Heartbeat ok")
	)
	df["is_level_imputed"] = level_impute_msk
	
	df.loc[
		level_impute_msk,
		"level"
	] = "INFO"
	
	# 5. Message transformation
	df['event_error_type'] = df['message'].str.extract(
		r"^ERR\s+(HTTP\s+\d+|\S+)"
	)
 
	# 6. Data quality validation
	logger.info("Running Data Quality validation with Pandera")
	try:
		# lazy=True collects ALL failure cases instead of stopping at the first one
		validated_df = SilverLogSchema.validate(df, lazy=True)
		logger.info("ALL PASSED!")
	except pa.errors.SchemaErrors as err:
		logger.error(f"FAILED! Found {len(err.failure_cases)} issues:")
		logger.error("\n" + str(err.failure_cases[['check', 'column', 'failure_case']]))
  
		# raise error to stop corrupt data from being written to Parquet
		raise RuntimeError("Pipeline stopped: Silver data contract violated") from err

	# 7. Save to partitioned parquet 
	logger.info(f"Writing validated Silver data to Parquet partitioned by event_date_utc0: {SILVER_OUTPUT_PATH}")
	
	validated_df.to_parquet(
		path=SILVER_OUTPUT_PATH,
		partition_cols=["event_date_utc0"],
		index=False,
		engine="pyarrow"
	)
 
	logger.info(f"Successfully saved {len(validated_df)} Silver records")

	