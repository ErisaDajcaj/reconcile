from .parse import parse_payouts, parse_orders
from .matching import deterministic_match, ReconcileReport


def reconcile_files(payout_csv, orders_csv) -> ReconcileReport:
    payouts = parse_payouts(payout_csv)
    orders = parse_orders(orders_csv)
    return deterministic_match(orders, payouts)
