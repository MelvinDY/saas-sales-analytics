-- One row per order line. Cleans types, derives the billing month, and flags
-- recurring plan invoices vs one-off add-ons. The plan tier a customer was
-- billed on in a given month is recovered from the product name, which gives
-- downstream models *historical* tier (the subscriptions file only carries
-- the latest tier).

with source as (

    select * from {{ source('raw', 'saas_transactions') }}

)

select
    order_id,
    cast(order_date as date)                                as order_date,
    {{ dbt.date_trunc('month', 'cast(order_date as date)') }} as order_month,
    customer_id,
    product,
    case when product like '%Plan Subscription' then true else false end
                                                            as is_recurring,
    case
        when product like '%Plan Subscription'
        then replace(product, ' Plan Subscription', '')
    end                                                     as billed_plan_tier,
    cast(sales as {{ dbt.type_numeric() }})                 as sales,
    cast(profit as {{ dbt.type_numeric() }})                as profit,
    region

from source
