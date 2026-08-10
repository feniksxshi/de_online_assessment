import duckdb

# Connect to in-memory database
conn = duckdb.connect()

# Create a view pointing to the partitioned parquet dataset
conn.execute("""
	CREATE OR REPLACE VIEW silver_logs AS 
	SELECT *
	FROM read_parquet(
		'data/silver/silver_valid_records.parquet/**/*.parquet',
		hive_partitioning=true
	);
""")

# Query the view directly
# Which service has the most ERRORs within 7 days?
query_1_dense_rank = f"""
WITH service_errors AS (
	SELECT
		service,
		COUNT(*) AS error_count
	FROM silver_logs
	WHERE level = 'ERROR'
	GROUP BY service
),

ranked AS (
	SELECT 
		service, 
		error_count,
		DENSE_RANK() OVER (
			ORDER BY error_count DESC
		) AS error_rank
	FROM service_errors
)

SELECT 
	service,
	error_count
FROM ranked
WHERE error_rank = 1;
"""
result_1_dense_rank = conn.execute(query_1_dense_rank).df()
print(result_1_dense_rank)

query_1_max = f"""
WITH service_errors AS (
	SELECT
		service,
		COUNT(*) AS error_count
	FROM silver_logs
	WHERE level = 'ERROR'
	GROUP BY service
)

SELECT 
	service,
	error_count 
FROM service_errors 
WHERE error_count = (
	SELECT MAX(error_count) FROM service_errors
);
"""
result_1_max = conn.execute(query_1_max).df()
print("\n", result_1_max)

# How many error records/events occurred each day?
query_2 = f"""
SELECT 
	event_date_utc0,
	COUNT(message) AS error_count
FROM silver_logs
WHERE level = 'ERROR'
GROUP BY event_date_utc0
ORDER BY error_count DESC;
"""
result_2 = conn.execute(query_2).df()
print("\n", result_2)

query_3 = f"""
WITH service_errors AS (
	SELECT
		event_error_type,
		service,
		COUNT(*) AS error_count
	FROM silver_logs
	WHERE level = 'ERROR' AND event_error_type IS NOT NULL
	GROUP BY event_error_type, service
)

SELECT 
	event_error_type,
	service,
	error_count 
FROM (
	SELECT
		*,
		DENSE_RANK() OVER (ORDER BY error_count DESC) as rank
	FROM service_errors 
)
WHERE rank <= 3; 
"""
result_3 = conn.execute(query_3).df()
print("\n", result_3)

conn.close()