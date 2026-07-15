-- Dashboard page 1: revenue overview.
-- Grain: (revenue_month, region). MRR movement bridge decomposed per
-- customer-month: new (first billed month), expansion / contraction
-- (recurring rate vs the previous consecutive month), churned (a customer's
-- rate lands in the bridge one month after their last billed month). The
-- final observed month is excluded from churn attribution so still-active
-- customers are never counted as churned.

with monthly as (

    select * from {{ ref('int_customer_monthly_revenue') }}

),

bounds as (

    select max(revenue_month) as max_month from monthly

),

with_prev as (

    select
        *,
        lag(recurring_mrr) over (
            partition by customer_id order by revenue_month) as prev_mrr,
        lag(revenue_month) over (
            partition by customer_id order by revenue_month) as prev_month
    from monthly

),

movements as (

    select
        revenue_month,
        region,
        count(distinct customer_id)                       as active_customers,
        sum(recurring_mrr)                                as mrr,
        sum(addon_revenue)                                as addon_revenue,
        sum(case when months_since_signup = 0
                 then recurring_mrr else 0 end)           as new_mrr,
        sum(case when prev_month is not null
                  and {{ dbt.datediff('prev_month', 'revenue_month', 'month') }} = 1
                  and recurring_mrr > prev_mrr
                 then recurring_mrr - prev_mrr else 0 end) as expansion_mrr,
        sum(case when prev_month is not null
                  and {{ dbt.datediff('prev_month', 'revenue_month', 'month') }} = 1
                  and recurring_mrr < prev_mrr
                 then prev_mrr - recurring_mrr else 0 end) as contraction_mrr
    from with_prev
    group by 1, 2

),

last_active as (

    select *
    from (
        select
            *,
            row_number() over (
                partition by customer_id order by revenue_month desc) as rn
        from monthly
    ) ranked
    where rn = 1

),

churned as (

    select
        {{ dbt.dateadd('month', 1, 'last_active.revenue_month') }} as revenue_month,
        last_active.region,
        count(*)                     as churned_customers,
        sum(last_active.recurring_mrr) as churned_mrr
    from last_active
    cross join bounds
    where last_active.revenue_month < bounds.max_month
    group by 1, 2

),

joined as (

    select
        coalesce(movements.revenue_month, churned.revenue_month) as revenue_month,
        coalesce(movements.region, churned.region)               as region,
        coalesce(movements.active_customers, 0)   as active_customers,
        coalesce(movements.mrr, 0)                as mrr,
        coalesce(movements.mrr, 0) * 12           as arr,
        coalesce(movements.addon_revenue, 0)      as addon_revenue,
        coalesce(movements.new_mrr, 0)            as new_mrr,
        coalesce(movements.expansion_mrr, 0)      as expansion_mrr,
        coalesce(movements.contraction_mrr, 0)    as contraction_mrr,
        coalesce(churned.churned_mrr, 0)          as churned_mrr,
        coalesce(churned.churned_customers, 0)    as churned_customers
    from movements
    full outer join churned
        on movements.revenue_month = churned.revenue_month
       and movements.region = churned.region

)

select
    *,
    new_mrr + expansion_mrr - contraction_mrr - churned_mrr as net_new_mrr,
    (mrr - lag(mrr) over (partition by region order by revenue_month))
        / nullif(lag(mrr) over (partition by region order by revenue_month), 0)
        as mom_mrr_growth
from joined
