-- Dashboard page 2: churn analysis.
-- Grain: (churn_month, plan_tier, churn_reason). Churned customer counts and
-- MRR per reason; customers/MRR at the start of the month are attached at
-- the (month, tier) level and REPEAT across reason rows -- aggregate reasons
-- away before computing churn rates ("at start of month m" = billed in
-- month m-1 on that tier).

with churned as (

    select
        {{ dbt.date_trunc('month', 'churn_date') }} as churn_month,
        plan_tier,
        churn_reason,
        count(*)          as churned_customers,
        sum(latest_mrr)   as churned_mrr
    from {{ ref('stg_subscriptions') }}
    where is_churned
    group by 1, 2, 3

),

at_start as (

    select
        {{ dbt.dateadd('month', 1, 'revenue_month') }} as churn_month,
        plan_tier,
        count(distinct customer_id) as customers_at_start,
        sum(recurring_mrr)          as mrr_at_start
    from {{ ref('int_customer_monthly_revenue') }}
    group by 1, 2

)

select
    churned.churn_month,
    churned.plan_tier,
    churned.churn_reason,
    churned.churned_customers,
    churned.churned_mrr,
    at_start.customers_at_start,
    at_start.mrr_at_start
from churned
left join at_start
    on churned.churn_month = at_start.churn_month
   and churned.plan_tier = at_start.plan_tier
