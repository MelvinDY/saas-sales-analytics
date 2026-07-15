-- Enriched customer grain: subscriptions joined to lifetime transaction
-- aggregates, with the derived lifecycle fields the marts build on.
-- Grain: customer_id.

with subscriptions as (

    select * from {{ ref('stg_subscriptions') }}

),

customer_orders as (

    select
        customer_id,
        min(order_date)                                       as first_order_date,
        max(order_date)                                       as last_order_date,
        count(*)                                              as order_count,
        sum(sales)                                            as lifetime_revenue,
        sum(profit)                                           as lifetime_profit,
        sum(case when is_recurring then sales else 0 end)     as recurring_revenue,
        sum(case when not is_recurring then sales else 0 end) as addon_revenue,
        count(distinct case when is_recurring then order_month end)
                                                              as months_active
    from {{ ref('stg_saas_transactions') }}
    group by 1

)

select
    subscriptions.customer_id,
    subscriptions.plan_tier,
    subscriptions.country,
    subscriptions.latest_mrr,
    subscriptions.subscription_start,
    subscriptions.cohort_month,
    subscriptions.churn_date,
    subscriptions.churn_reason,
    subscriptions.is_churned,
    {{ dbt.datediff(
        'subscriptions.subscription_start',
        "coalesce(subscriptions.churn_date, cast('" ~ var('as_of_date') ~ "' as date))",
        'day') }}                          as subscription_length_days,
    customer_orders.first_order_date,
    customer_orders.last_order_date,
    coalesce(customer_orders.order_count, 0)        as order_count,
    coalesce(customer_orders.months_active, 0)      as months_active,
    coalesce(customer_orders.lifetime_revenue, 0)   as lifetime_revenue,
    coalesce(customer_orders.lifetime_profit, 0)    as lifetime_profit,
    coalesce(customer_orders.recurring_revenue, 0)  as recurring_revenue,
    coalesce(customer_orders.addon_revenue, 0)      as addon_revenue,
    coalesce(customer_orders.lifetime_revenue, 0)
        / nullif(customer_orders.months_active, 0)  as revenue_per_month

from subscriptions
left join customer_orders using (customer_id)
