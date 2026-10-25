select
    record_id,
    advisory_id,
    db_prefix,
    summary,
    cvss_score,
    severity_label,
    cast(withdrawn as boolean) as withdrawn,
    cast(published_at as timestamptz) as published_at,
    cast(modified_at as timestamptz) as modified_at,
    cast(ingested_at as timestamptz) as ingested_at
from {{ source('intel', 'osv_records') }}
