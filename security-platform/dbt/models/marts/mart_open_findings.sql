-- 未対応の Finding を優先度・期限順に。期限切れと残り日数を付ける
select
    priority,
    service_id,
    package,
    version,
    fixed_version,
    advisory_id,
    severity,
    kev,
    epss,
    scope,
    source_kind,
    dependency_path,
    due_at,
    due_at is not null and due_at < now() as overdue,
    date_diff('day', now(), due_at) as days_left,
    first_seen_at,
    summary
from {{ ref('stg_findings') }}
where state = 'open'
order by priority, due_at nulls last, service_id, package
