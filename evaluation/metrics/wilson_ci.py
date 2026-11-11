"""
evaluation/metrics/wilson_ci.py
===============================
Wilson score interval calculation for binomial proportions.
Provides statistically sound confidence intervals for small and moderate sample sizes.
"""
import math
from typing import Tuple


def wilson_score_interval(k: int, n: int, confidence: float = 0.95) -> Tuple[float, float]:
    """
    Computes the Wilson score confidence interval for a binomial proportion k / n.
    Returns (lower_bound, upper_bound) clamped to [0.0, 1.0].
    """
    if n <= 0:
        return 0.0, 0.0

    p_hat = k / n
    # Approximate normal quantiles: 95% -> 1.95996, 90% -> 1.64485, 99% -> 2.57583
    if math.isclose(confidence, 0.95, rel_tol=1e-2):
        z = 1.95996398454
    elif math.isclose(confidence, 0.90, rel_tol=1e-2):
        z = 1.64485362695
    elif math.isclose(confidence, 0.99, rel_tol=1e-2):
        z = 2.57582930355
    else:
        z = 1.95996398454

    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p_hat + z2 / (2.0 * n)) / denom
    margin = (z / denom) * math.sqrt((p_hat * (1.0 - p_hat) / n) + (z2 / (4.0 * n * n)))

    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    return round(lower, 4), round(upper, 4)


def format_proportion_ci(k: int, n: int, confidence: float = 0.95) -> str:
    """Formats k/n (pct%) [CI_lower - CI_upper]."""
    if n == 0:
        return "0/0 (N/A)"
    pct = (k / n) * 100.0
    low, high = wilson_score_interval(k, n, confidence)
    return f"{k}/{n} ({pct:.1f}%) [95% CI: {low*100:.1f}% - {high*100:.1f}%]"
