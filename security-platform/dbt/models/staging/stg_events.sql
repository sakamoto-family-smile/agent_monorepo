select
    'intel' as producer,
    seq,
    event_id,
    type as event_type,
    cast(payload as json) as payload,
    cast(occurred_at as timestamptz) as occurred_at
from {{ source('intel', 'events') }}
