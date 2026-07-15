-- Dashboard page 3: cohort retention heatmap.
-- Grain: (cohort_month, months_since_signup). Logo retention (share of the
-- signup cohort still billing N months later) and MRR retention (cohort MRR
-- at month N vs month 0 -- cohort-level net revenue retention, since it
-- includes the expansion of survivors).

with monthly as (

    select * from {{ ref('int_customer_monthly_revenue') }}

),

cohorts as (

    select
        cohort_month,
        count(distinct case when months_since_signup = 0 then customer_id end)
                                                     as cohort_size,
        sum(case when months_since_signup = 0 then recurring_mrr else 0 end)
                                                     as cohort_starting_mrr
    from monthly
    group by 1

)

select
    monthly.cohort_month,
    monthly.months_since_signup,
    cohorts.cohort_size,
    count(distinct monthly.customer_id)          as active_customers,
    count(distinct monthly.customer_id)
        / nullif(cohorts.cohort_size, 0)         as retention_rate,
    sum(monthly.recurring_mrr)                   as retained_mrr,
    sum(monthly.recurring_mrr)
        / nullif(cohorts.cohort_starting_mrr, 0) as mrr_retention_rate
from monthly
inner join cohorts using (cohort_month)
group by 1, 2, 3, cohorts.cohort_starting_mrr
