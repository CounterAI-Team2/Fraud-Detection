from __future__ import annotations

RISK_TIER_COLORS: dict[str, str] = {
    "Critical": "#f44336",
    "High":     "#fb8c00",
    "Medium":   "#fdd835",
    "Low":      "#cfd8dc",
}

ALERT_QUEUE_DISPLAY_LIMIT        = 200
RELATED_TRANSACTIONS_WINDOW_DAYS = 30
CUSTOMER_RECENT_TXNS_LIMIT       = 25
TREND_HISTORICAL_DAYS            = 30

ALERT_THRESHOLDS: dict[str, float] = {
    "Critical": 0.85,
    "High":     0.70,
    "Medium":   0.50,
}
