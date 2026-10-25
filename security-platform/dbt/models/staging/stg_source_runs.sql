select
    run_id,
    source,
    mode,
    status,
    fetched,
    changed,
    error,
    cast(started_at as timestamptz) as started_at,
    cast(finished_at as timestamptz) as finished_at,
    date_diff('second', cast(started_at as timestamptz), cast(finished_at as timestamptz)) as duration_seconds
from {{ source('intel', 'source_runs') }}
