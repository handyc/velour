"""Pure forecasting math for Radiant. No DB writes; read-only.

The forecast walks each WorkloadClass across the horizon list and
returns a row per (horizon, class) plus a totals row. Three regimes
are used depending on how far out the horizon is — see `regime_for`
in models.py.

  linear (0-10 yr):   N(t) = N0 + rate * t
  logistic (20-100):  N(t) = K / (1 + ((K - N0) / N0) * exp(-r * t))
                      where r is fit so that linear growth in the first
                      ~5 years matches `rate`; K is the class's
                      `saturation_count`.
  speculative (200+): we still emit a number (same logistic asymptote
                      once flat, plus the narrative that nothing should
                      be trusted at this range).

RAM / storage / CPU are derived from project counts plus the class
resource profile plus a concurrency multiplier for WordPress-style
class workloads.
"""

import math

from .models import HORIZON_YEARS, regime_for, GrowthAssumption


def _logistic_rate(n0, k, years_to_linear_match, linear_slope):
    """Pick r so the logistic curve's slope at t=0 matches the linear
    regime's rate for the first ~5 years. Falls back to a sane default."""
    if n0 <= 0 or k <= 0 or linear_slope <= 0 or n0 >= k:
        return 0.1
    return max(0.01, min(0.5, linear_slope / (n0 * (1 - n0 / k))))


def _logistic(n0, k, r, t):
    if k <= 0:
        return n0 + r * t
    if n0 <= 0:
        return 0
    if r <= 0:
        return n0
    try:
        denom = 1 + ((k - n0) / n0) * math.exp(-r * t)
        return k / denom
    except OverflowError:
        return k


def project_count(wc, years):
    """Forecasted project count for this class at +years from now."""
    n0 = wc.current_count
    rate = wc.new_per_year or 0.0
    k = wc.saturation_count or 0
    regime = regime_for(years)

    if regime == 'linear':
        return n0 + rate * years
    r = _logistic_rate(n0, k if k else n0 + rate * 100, 5, rate)
    k_effective = k if k else n0 + rate * 100
    return _logistic(n0, k_effective, r, years)


def ram_gb_for_class(wc, count, peak_factor=1.0):
    """Aggregate RAM for `count` projects in class wc, in GB.

    peak_factor lifts the baseline to account for concurrent users on
    classroom WordPress. Idle RAM uses typical_ram_mb; peak multiplies
    by peak_concurrency when peak_factor > 1.
    """
    if peak_factor > 1 and wc.peak_concurrency > 1:
        per_project_mb = wc.typical_ram_mb * (1 + (wc.peak_concurrency - 1) * 0.25)
    else:
        per_project_mb = wc.typical_ram_mb
    return (count * per_project_mb) / 1024.0


def storage_gb_for_class(wc, count, years):
    """Aggregate storage in GB. Projects accrete data over their lifetime;
    we add a small per-year drift so a 10-year-old project is meaningfully
    larger than a brand-new one. Bounded so it doesn't run away in the
    speculative regime.
    """
    base_mb = wc.typical_storage_mb
    drift = GrowthAssumption.get_float('storage_drift_mb_per_year', 50)
    avg_age_years = min(years, 20) / 2 if years > 0 else 0
    per_project_mb = base_mb + drift * avg_age_years
    return (count * per_project_mb) / 1024.0


def cpu_cores_needed(ram_gb_total, peak_factor):
    """Rough heuristic: 1 core per 4 GB of working RAM, lifted by peak."""
    base = max(2, math.ceil(ram_gb_total / 4))
    if peak_factor > 1:
        base = math.ceil(base * peak_factor)
    return base


def forecast_table(workload_classes):
    """Return one dict per horizon with per-class and aggregate figures."""
    rows = []
    for years in HORIZON_YEARS:
        per_class = []
        total_projects = 0.0
        total_ram_idle = 0.0
        total_ram_peak = 0.0
        total_storage = 0.0
        for wc in workload_classes:
            n = project_count(wc, years)
            ram_idle = ram_gb_for_class(wc, n, 1.0)
            ram_peak = ram_gb_for_class(wc, n, 1.5)
            storage = storage_gb_for_class(wc, n, years)
            per_class.append({
                'class_name':  wc.name,
                'class_slug':  wc.slug,
                'projects':    n,
                'ram_idle_gb': ram_idle,
                'ram_peak_gb': ram_peak,
                'storage_gb':  storage,
            })
            total_projects += n
            total_ram_idle += ram_idle
            total_ram_peak += ram_peak
            total_storage += storage
        rows.append({
            'years':             years,
            'regime':            regime_for(years),
            'per_class':         per_class,
            'total_projects':    total_projects,
            'total_ram_idle_gb': total_ram_idle,
            'total_ram_peak_gb': total_ram_peak,
            'total_storage_gb':  total_storage,
            'total_cpu_cores':   cpu_cores_needed(total_ram_peak, 1.0),
        })
    return rows


def purchase_recommendation(rows, split_wordpress=True):
    """Convert the 1-year and 5-year rows into a concrete May 2026 spec.

    Sizes for roughly 2x the 5-year peak — we want to replace in ~5-7
    years, not every year. Optionally splits WordPress onto its own box.
    """
    row_1y = next(r for r in rows if r['years'] == 1)
    row_5y = next(r for r in rows if r['years'] == 5)

    target_ram = row_5y['total_ram_peak_gb'] * 2
    target_storage = row_5y['total_storage_gb'] * 2.5
    target_cores = max(8, cpu_cores_needed(target_ram, 1.0))

    def _snap_ram(gb):
        for tier in [16, 32, 64, 128, 256, 512, 1024]:
            if tier >= gb:
                return tier
        return int(gb + 127) // 128 * 128

    def _snap_storage(gb):
        for tier in [500, 1000, 2000, 4000, 8000, 16000]:
            if tier >= gb:
                return tier
        return int(gb + 999) // 1000 * 1000

    def _snap_cores(c):
        for tier in [4, 8, 16, 24, 32, 48, 64]:
            if tier >= c:
                return tier
        return c

    if not split_wordpress:
        return {
            'split': False,
            'boxes': [{
                'label':     'Unified LUCDH server',
                'ram_gb':    _snap_ram(target_ram),
                'storage_gb':_snap_storage(target_storage),
                'cpu_cores': _snap_cores(target_cores),
                'notes':     'Replaces the current single 200 GB machine.',
            }],
            'basis_years': 5,
            'basis_ram_peak_gb': row_5y['total_ram_peak_gb'],
            'basis_storage_gb': row_5y['total_storage_gb'],
            'year_1': row_1y,
            'year_5': row_5y,
        }

    # Split the 5-year totals into "wp-heavy" and "rest" by class slug.
    wp_ram = 0.0
    wp_storage = 0.0
    rest_ram = 0.0
    rest_storage = 0.0
    for cls in row_5y['per_class']:
        if 'wordpress' in cls['class_slug']:
            wp_ram += cls['ram_peak_gb']
            wp_storage += cls['storage_gb']
        else:
            rest_ram += cls['ram_peak_gb']
            rest_storage += cls['storage_gb']

    boxes = [
        {
            'label':     'Production + Django box',
            'ram_gb':    _snap_ram(rest_ram * 2),
            'storage_gb':_snap_storage(rest_storage * 2.5),
            'cpu_cores': _snap_cores(cpu_cores_needed(rest_ram * 2, 1.0)),
            'notes':     'Handles Django 24/7, dev, experimental, admin.',
        },
        {
            'label':     'WordPress classroom box',
            'ram_gb':    _snap_ram(wp_ram * 2),
            'storage_gb':_snap_storage(wp_storage * 2),
            'cpu_cores': _snap_cores(cpu_cores_needed(wp_ram * 2, 1.3)),
            'notes':     'Isolates classroom spikes (40 concurrent '
                         'students/site) from production workloads.',
        },
    ]
    return {
        'split':             True,
        'boxes':             boxes,
        'basis_years':       5,
        'basis_ram_peak_gb': row_5y['total_ram_peak_gb'],
        'basis_storage_gb':  row_5y['total_storage_gb'],
        'year_1':            row_1y,
        'year_5':            row_5y,
    }
