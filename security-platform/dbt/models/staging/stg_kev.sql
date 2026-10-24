select
    cve,
    vendor,
    product,
    name,
    cast(date_added as date) as date_added,
    cast(due_date as date) as due_date,
    ransomware = 'Known' as ransomware_known
from {{ source('intel', 'kev_entries') }}
