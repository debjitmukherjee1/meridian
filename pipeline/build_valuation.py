"""
build_valuation.py — Base Fair Value + Sentiment-Adjusted Fair Value.

Base Fair Value = blend of:
  (1) sector-median-multiple anchor (P/E applied to EPS)
  (2) DCF-lite on FCF per share (only when FCF is available)
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
    out = []
    for c in companies:
        c = dict(c)
        anchors = []
        # (1) sector-median-multiple anchor
        if c.get("eps") and c["sector"] in med_pe:
            anchors.append(med_pe[c["sector"]] * c["eps"])
        # (2) DCF-lite
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
