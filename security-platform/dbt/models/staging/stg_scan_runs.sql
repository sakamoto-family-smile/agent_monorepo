select
    run_id,
    job,
    status,
    services,
    components,
    open_findings,
    opened,
    updated,
    resolved,
    warnings_json,
    error,
    cast(started_at as timestamptz) as started_at,
    cast(finished_at as timestamptz) as finished_at
from {{ source('detection', 'scan_runs') }}
