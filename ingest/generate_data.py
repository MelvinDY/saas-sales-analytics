"""Deterministic synthetic SaaS data generator.

Produces the two raw files the pipeline expects, matching the project plan's
Kaggle dataset schemas exactly:

  data/raw/saas_transactions.csv
      order_id, order_date, customer_id, product, sales, profit, region
  data/raw/subscriptions.csv
      customer_id, plan_tier, mrr, subscription_start, churn_date,
      churn_reason, country

The generator is seeded, so every run yields identical data. It encodes real
SaaS dynamics rather than uniform noise:

  * signup volume grows ~3.5%/month from Jan 2023 with mild seasonality
  * churn is a monthly hazard that depends on plan tier, is elevated in the
    first three months of a subscription, and is much worse for the mid-2024
    promo cohort (cheap signups, poor retention -- the cohort-heatmap story)
  * customers expand (seat growth, tier upgrades) and occasionally contract,
    so NRR and the MRR bridge have real movement in every direction
  * every active month bills a recurring invoice; add-on products (onboarding,
    support, integrations) appear as one-off orders with service-level margins
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 42
OBS_END = date(2026, 6, 30)          # observation cutoff (data "as of")
SIGNUP_START = date(2023, 1, 1)
SIGNUP_MONTHS = 42                   # Jan 2023 .. Jun 2026
BASE_SIGNUPS = 12                    # signups in month 0
MONTHLY_GROWTH = 1.035

TIERS = {
    #  tier        base $/seat  seat range   monthly churn hazard
    "Basic":      (49.0,        (1, 1),      0.045),
    "Pro":        (149.0,       (1, 5),      0.025),
    "Enterprise": (499.0,       (2, 10),     0.012),
}
TIER_WEIGHTS = [("Basic", 0.52), ("Pro", 0.36), ("Enterprise", 0.12)]
EARLY_LIFE_MULT = 1.8                # hazard multiplier in months 0-2
PROMO_MONTHS = {date(2024, 5, 1), date(2024, 6, 1), date(2024, 7, 1)}
PROMO_VOLUME_MULT = 1.8
PROMO_HAZARD_MULT = 2.2

COUNTRIES = [
    ("Australia", "APAC", 0.30), ("United States", "AMER", 0.25),
    ("United Kingdom", "EMEA", 0.12), ("New Zealand", "APAC", 0.08),
    ("Singapore", "APAC", 0.07), ("Canada", "AMER", 0.06),
    ("Germany", "EMEA", 0.05), ("India", "APAC", 0.04),
    ("Japan", "APAC", 0.03),
]

CHURN_REASONS = {
    # weights skew by tier: price bites Basic, features/support bite higher tiers
    "Basic":      [("Too expensive", 0.34), ("Low usage", 0.26),
                   ("Switched to competitor", 0.16), ("Missing features", 0.12),
                   ("Poor support", 0.06), ("Company closed", 0.06)],
    "Pro":        [("Missing features", 0.28), ("Switched to competitor", 0.24),
                   ("Too expensive", 0.18), ("Low usage", 0.14),
                   ("Poor support", 0.10), ("Company closed", 0.06)],
    "Enterprise": [("Missing features", 0.30), ("Poor support", 0.22),
                   ("Switched to competitor", 0.20), ("Too expensive", 0.10),
                   ("Low usage", 0.10), ("Company closed", 0.08)],
}

ADDONS = [
    # product, price, margin, eligible tiers, monthly probability
    ("Onboarding Package", 750.0, 0.35, {"Pro", "Enterprise"}, None),  # signup only
    ("Premium Support", 99.0, 0.55, {"Basic", "Pro"}, 0.020),
    ("API Add-on", 59.0, 0.80, {"Pro", "Enterprise"}, 0.025),
    ("Training Session", 400.0, 0.40, {"Pro", "Enterprise"}, 0.012),
    ("Custom Integration", 1500.0, 0.30, {"Enterprise"}, 0.010),
]
RECURRING_MARGIN = {"Basic": 0.82, "Pro": 0.80, "Enterprise": 0.76}

TIER_ORDER = ["Basic", "Pro", "Enterprise"]


def month_add(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return date(y, m + 1, 1)


def weighted(rng: random.Random, pairs):
    return rng.choices([p[0] for p in pairs], weights=[p[1] for p in pairs])[0]


def seasonal(month: int) -> float:
    # softer signups over ANZ summer holidays, a bump around mid-year budgets
    return {1: 0.85, 2: 0.95, 6: 1.10, 7: 1.10, 12: 0.80}.get(month, 1.0)


def main() -> None:
    rng = random.Random(SEED)
    out_dir = Path(__file__).resolve().parents[1] / "data" / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)

    customers, orders = [], []
    order_no = 0
    cust_no = 0

    for mi in range(SIGNUP_MONTHS):
        month_start = month_add(SIGNUP_START, mi)
        n = BASE_SIGNUPS * (MONTHLY_GROWTH ** mi) * seasonal(month_start.month)
        is_promo = month_start in PROMO_MONTHS
        if is_promo:
            n *= PROMO_VOLUME_MULT
        for _ in range(round(n)):
            cust_no += 1
            cid = f"CUST-{cust_no:05d}"
            country, region = (lambda c: (c[0], c[1]))(
                weighted(rng, [((c, r), w) for c, r, w in COUNTRIES]))
            tier = "Basic" if is_promo and rng.random() < 0.75 \
                else weighted(rng, TIER_WEIGHTS)
            base, seat_range, _ = TIERS[tier]
            seats = rng.randint(*seat_range)
            signup = month_start + timedelta(days=rng.randint(0, 27))

            # simulate month by month until churn or observation end
            churn_date = None
            month = 0
            cur_tier, cur_seats = tier, seats
            while True:
                bill_month = month_add(signup, month)
                if bill_month > OBS_END:
                    break
                base_price = TIERS[cur_tier][0]
                mrr_now = round(base_price * cur_seats, 2)

                # recurring invoice on the anniversary day (clamped to 28)
                order_no += 1
                bill_date = bill_month + timedelta(days=min(signup.day, 28) - 1)
                if bill_date <= OBS_END:
                    orders.append((
                        f"ORD-{order_no:06d}", bill_date.isoformat(), cid,
                        f"{cur_tier} Plan Subscription", mrr_now,
                        round(mrr_now * (RECURRING_MARGIN[cur_tier]
                                         + rng.uniform(-0.03, 0.03)), 2),
                        region,
                    ))

                # add-on purchases
                for prod, price, margin, elig, p in ADDONS:
                    if cur_tier not in elig:
                        continue
                    hit = (month == 0 and p is None and rng.random() < 0.55) or \
                          (p is not None and rng.random() < p)
                    if hit and bill_date <= OBS_END:
                        order_no += 1
                        orders.append((
                            f"ORD-{order_no:06d}", bill_date.isoformat(), cid,
                            prod, price,
                            round(price * (margin + rng.uniform(-0.05, 0.05)), 2),
                            region,
                        ))

                # churn hazard for surviving into next month
                _, _, hazard = TIERS[cur_tier]
                if month < 3:
                    hazard *= EARLY_LIFE_MULT
                if is_promo:
                    hazard *= PROMO_HAZARD_MULT
                if rng.random() < hazard:
                    nxt = month_add(signup, month + 1)
                    churn_date = min(nxt + timedelta(days=rng.randint(0, 27)),
                                     OBS_END)
                    break

                # expansion / contraction for next month
                ti = TIER_ORDER.index(cur_tier)
                r = rng.random()
                if r < 0.008 and ti < 2:                       # tier upgrade
                    cur_tier = TIER_ORDER[ti + 1]
                    cur_seats = max(cur_seats, TIERS[cur_tier][1][0])
                elif r < 0.020 and cur_tier != "Basic":        # seat expansion
                    cur_seats += rng.randint(1, 3)
                elif r < 0.024 and cur_seats > TIERS[cur_tier][1][0]:
                    cur_seats -= 1                             # contraction
                month += 1

            final_mrr = round(TIERS[cur_tier][0] * cur_seats, 2)
            reason = weighted(rng, CHURN_REASONS[cur_tier]) if churn_date else ""
            customers.append((
                cid, cur_tier, final_mrr, signup.isoformat(),
                churn_date.isoformat() if churn_date else "", reason, country,
            ))

    with open(out_dir / "subscriptions.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["customer_id", "plan_tier", "mrr", "subscription_start",
                    "churn_date", "churn_reason", "country"])
        w.writerows(customers)

    orders.sort(key=lambda r: (r[1], r[0]))
    with open(out_dir / "saas_transactions.csv", "w", newline="",
              encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["order_id", "order_date", "customer_id", "product",
                    "sales", "profit", "region"])
        w.writerows(orders)

    churned = sum(1 for c in customers if c[4])
    print(f"customers: {len(customers)} ({churned} churned, "
          f"{churned / len(customers):.0%})")
    print(f"orders:    {len(orders)}")
    print(f"written to {out_dir}")


if __name__ == "__main__":
    main()
