"""
build_valuation.py — Base Fair Value + Sentiment-Adjusted Fair Value.

Base Fair Value = blend of:
  (1) sector-median P/E anchor, applied to EPS
  (2) sector-median EV/EBITDA anchor, applied to EBITDA (then de-levered by
      the company's own net debt back to an equity value per share)
  (3) DCF-lite on FCF per share (only when FCF is available)
Everything here is deliberately simple and transparent so the number is
reproducible and defensible.
"""
import statistics
import config


def _sector_median_pe(companies):
    by_sector = {}
    for c in companies:
        if c.get("pe"):
            by_sector.setdefault(c["sector"], []).append(c["pe"])
    return {s: statistics.median(v) for s, v in by_sector.items() if v}


def _company_ev_ebitda(c):
    """This company's own EV/EBITDA multiple, computed from parts we already
    show (price, net debt, EBITDA) rather than trusting a pre-computed ratio
    -- keeps the anchor auditable back to real fetched numbers."""
    ebitda_ps = c.get("ebitda_per_share")
    if not ebitda_ps or ebitda_ps <= 0:
        return None
    ev_per_share = c.get("price", 0) + (c.get("net_debt_per_share") or 0)
    if ev_per_share <= 0:
        return None
    return ev_per_share / ebitda_ps


def _sector_median_ev_ebitda(companies):
    by_sector = {}
    for c in companies:
        m = _company_ev_ebitda(c)
        if m:
            by_sector.setdefault(c["sector"], []).append(m)
    return {s: statistics.median(v) for s, v in by_sector.items() if v}


def _dcf_lite(fcf_per_share):
    if not fcf_per_share or fcf_per_share <= 0:
        return None
    g, r, yrs = config.DCF_TERMINAL_GROWTH, config.DCF_DISCOUNT_RATE, config.DCF_YEARS
    pv = 0.0
    fcf = fcf_per_share
    for t in range(1, yrs + 1):
        fcf *= (1 + g)
        pv += fcf / ((1 + r) ** t)
    terminal = (fcf * (1 + g)) / (r - g)
    pv += terminal / ((1 + r) ** yrs)
    return round(pv, 2)


def base_fair_value(companies):
    med_pe = _sector_median_pe(companies)
    med_ev_ebitda = _sector_median_ev_ebitda(companies)
    out = []
    for c in companies:
        c = dict(c)
        anchors = []
        # (1) sector-median P/E anchor
        if c.get("eps") and c["sector"] in med_pe:
            anchors.append(med_pe[c["sector"]] * c["eps"])
        # (2) sector-median EV/EBITDA anchor, de-levered to equity per share
        if c.get("ebitda_per_share") and c["sector"] in med_ev_ebitda:
            implied_ev_per_share = med_ev_ebitda[c["sector"]] * c["ebitda_per_share"]
            implied_price = implied_ev_per_share - (c.get("net_debt_per_share") or 0)
            if implied_price > 0:
                anchors.append(implied_price)
        # (3) DCF-lite
        dcf = _dcf_lite(c.get("fcf_per_share"))
        if dcf:
            anchors.append(dcf)
        # fallback: if nothing computable, use current price
        bfv = round(sum(anchors) / len(anchors), 2) if anchors else c.get("price", 0)
        c["base_fair_value"] = bfv
        out.append(c)
    return out


def sentiment_adjust(companies, k=None):
    k = config.SENTIMENT_TILT_K if k is None else k
    n = config.NEUTRAL_SENTIMENT
    for c in companies:
        adj = (c["sentiment_index"] - n) / n           # -1 .. +1
        c["sentiment_adjusted_fair_value"] = round(c["base_fair_value"] * (1 + k * adj), 2)
    return companies


if __name__ == "__main__":
    print("Run via run_all.py")
