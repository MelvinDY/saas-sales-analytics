-- Dashboard page 4: plan performance.
-- Grain: (revenue_month, plan_tier). ARPU, 12-month NRR (MRR today of the
-- customers who were on the tier 12 months ago -- churned customers count as
-- zero, expansion counts in full, new logos excluded -- divided by their MRR
-- then), realized CLV of customers churning in the month, and predictive
-- CLV = ARPU / trailing-12-month average churn rate.

with monthly as (

    select * from {{ ref('int_customer_monthly_revenue') }}

),

base as (

    select
        revenue_month,
        plan_tier,
        count(distinct customer_id) as active_customers,
        sum(recurring_mrr)          as mrr
    from monthly
    group by 1, 2

),

nrr_12m as (

    select
        {{ dbt.dateadd('month', 12, 'past.revenue_month') }} as revenue_month,
        past.plan_tier,
        sum(past.recurring_mrr)                  as mrr_12m_ago,
        sum(coalesce(now_.recurring_mrr, 0))     as retained_mrr_now
    from monthly as past
    left join monthly as now_
        on now_.customer_id = past.customer_id
       and now_.revenue_month = {{ dbt.dateadd('month', 12, 'past.revenue_month') }}
    group by 1, 2

),

churned as (

    select
        {{ dbt.date_trunc('month', 'churn_date') }} as revenue_month,
        plan_tier,
        count(*)               as churned_customers,
        avg(lifetime_revenue)  as avg_realized_clv
    from {{ ref('int_customer_revenue') }}
    where is_churned
    group by 1, 2

),

joined as (

    select
        base.revenue_month,
        base.plan_tier,
        base.active_customers,
        base.mrr,
        base.mrr / nullif(base.active_customers, 0) as arpu,
        lag(base.active_customers) over (
            partition by base.plan_tier order by base.revenue_month)
                                                    as customers_at_start,
        nrr_12m.mrr_12m_ago,
        nrr_12m.retained_mrr_now
            / nullif(nrr_12m.mrr_12m_ago, 0)        as nrr_12m,
        coalesce(churned.churned_customers, 0)      as churned_customers,
        churned.avg_realized_clv
    from base
    left join nrr_12m
        on base.revenue_month = nrr_12m.revenue_month
       and base.plan_tier = nrr_12m.plan_tier
    left join churned
        on base.revenue_month = churned.revenue_month
       and base.plan_tier = churned.plan_tier

),

with_churn_rate as (

    select
        *,
        churned_customers / nullif(customers_at_start, 0) as monthly_churn_rate
    from joined

)

select
    *,
    avg(monthly_churn_rate) over (
        partition by plan_tier
        order by revenue_month
        rows between 11 preceding and current row) as trailing_12m_churn_rate,
    arpu / nullif(
        avg(monthly_churn_rate) over (
            partition by plan_tier
            order by revenue_month
            rows between 11 preceding and current row), 0) as predictive_clv
from with_churn_rate
