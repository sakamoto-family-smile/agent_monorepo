-- サービスごとの未対応件数 (優先度別) と、修正版があってすぐ上げられる件数
select
    service_id,
    count(*) as open_findings,
    count(*) filter (where priority = 'P1') as p1,
    count(*) filter (where priority = 'P2') as p2,
    count(*) filter (where priority = 'P3') as p3,
    count(*) filter (where priority = 'P4') as p4,
    count(*) filter (where fixed_version is not null) as fixable,
    count(*) filter (where source_kind = 'image') as from_image,
    count(*) filter (where due_at is not null and due_at < now()) as overdue,
    min(due_at) as next_due_at
from {{ ref('stg_findings') }}
where state = 'open'
group by 1
