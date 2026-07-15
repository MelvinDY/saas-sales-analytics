-- Customer x active-month spine: the base table for MRR, the movement
-- bridge, NRR, and cohort retention. A customer is "active" in a month iff a
-- recurring plan invoice was billed that month (billing runs monthly, so
-- activity and billing coincide). Grain: (customer_id, revenue_month).

with transactions as (

    select * from {{ ref('stg_saas_transactions') }}

),

subscriptions as (

    select * from {{ ref('stg_subscriptions') }}

),

monthly as (

    select
        customer_id,
        order_month                                          as revenue_month,
        max(region)                                          as region,
        max(billed_plan_tier)                                as plan_tier,
        sum(case when is_recurring then sales else 0 end)    as recurring_mrr,
        sum(case when not is_recurring then sales else 0 end) as addon_revenue,
        sum(sales)                                           as total_revenue,
        sum(profit)                                          as total_profit
    from transactions
    group by 1, 2
    having sum(case when is_recurring then sales else 0 end) > 0

)

select
    monthly.customer_id,
    monthly.revenue_month,
    monthly.region,
    monthly.plan_tier,
    subscriptions.country,
    subscriptions.cohort_month,
    {{ dbt.datediff('subscriptions.cohort_month', 'monthly.revenue_month', 'month') }}
                                as months_since_signup,
    monthly.recurring_mrr,
    monthly.addon_revenue,
    monthly.total_revenue,
    monthly.total_profit

from monthly
inner join subscriptions using (customer_id)
