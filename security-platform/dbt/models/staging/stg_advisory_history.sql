-- 変化 1 件 = 1 行に展開 (1 イベントに複数の change_type が入るため)
select
    h.id as history_id,
    h.advisory_id,
    t.change_type,
    h.run_id,
    cast(h.occurred_at as timestamptz) as occurred_at
from {{ source('intel', 'advisory_history') }} h,
    unnest(cast(cast(h.change_types_json as json) as varchar[])) as t(change_type)
