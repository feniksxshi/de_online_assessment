# Docs: 
# https://pandera.readthedocs.io/en/stable/dataframe_schemas.html
# https://pandera.readthedocs.io/en/stable/?badge=stable#dataframe-model
import pandera as pa
from datetime import date
from pandera import (
    Column, Check, DataFrameSchema,
	Series
)
import pandas as pd

ALLOWED_SERVICES = [
	'notification-worker',
 	'auth-service',
  	'payment-api',
    'batch-report',
    'web-portal'
]

ALLOWED_LEVELS = [
	'INFO',
	'WARN',
	'ERROR'
]

class SilverLogSchema(pa.DataFrameModel):
	event_timestamp_utc0: pd.Timestamp = pa.Field(
		dtype=pd.DatetimeTZDtype(tz="UTC"),
		nullable=False
	)
	event_date_utc0: pd.Date = pa.Field(
		ge=date(2026, 7, 27), # >= 27/07/2026
		le=date(2026, 8, 2), # <= 02/08/2026
     	nullable=False
    )
	is_event_corrupted: pd.BooleanDtype = pa.Field(nullable=False)
	service: str = pa.Field(isin=ALLOWED_SERVICES, nullable=False)
	level: str = pa.Field(isin=ALLOWED_LEVELS, nullable=False)
	is_level_imputed: pd.BooleanDtype = pa.Field(nullable=False)
	message: str = pa.Field(nullable=False)
	event_error_type: str = pa.Field(nullable=True)
	request_id: str = pa.Field(str_matches=r"^req-\d{8}$", nullable=False)
	trace_id: str = pa.Field(str_matches=f"^trace-\d{10}$", nullable=True)

	@pa.dataframe_check
	def check_event_corrupted(cls, df: pd.DataFrame) -> bool:
		expected = df['timestamp'].eq("not-a-date")
		return (df['is_event_corrupted'] == expected).all()
	
	@ pa.dataframe_check
	def check_fwd_filled_timestamp(cls, df: pd.DataFrame) -> bool:
		corrupted_rows = df["is_event_corrupted"]
	
		return (
      		df.loc[
				corrupted_rows,
				'event_timestamp_utc0'
			].notna().all()
		)
 
	@pa.dataframe_check
	def check_imputed_level(cls, df: pd.DataFrame) -> bool:
		imputed_rows = df['is_level_imputed']

		return (
			df.loc[imputed_rows, 'level'].eq("INFO")
			& df.loc[imputed_rows, 'message'].eq("Heartbeat ok")
		).all()
		
