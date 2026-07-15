-- One row per customer. Casts dates, standardises plan-tier casing, and
-- nulls out empty churn fields for still-active customers.

with source as (

    select * from {{ source('raw', 'subscriptions') }}

)

select
    customer_id,
    upper(substr(trim(plan_tier), 1, 1))
        || lower(substr(trim(plan_tier), 2))        as plan_tier,
    cast(mrr as {{ dbt.type_numeric() }})           as latest_mrr,
    cast(subscription_start as date)                as subscription_start,
    {{ dbt.date_trunc('month', 'cast(subscription_start as date)') }}
                                                    as cohort_month,
    cast(churn_date as date)                        as churn_date,
    nullif(cast(churn_reason as {{ dbt.type_string() }}), '') as churn_reason,
    country,
    churn_date is not null                          as is_churned

from source
