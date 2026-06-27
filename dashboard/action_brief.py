"""Action Brief — synthesized decision view.

Takes all existing dashboard signals and produces a single, opinionated
swing-trader summary: market stance, action items, watchlist, and
conflict resolution. No new data fetching or indicators — pure synthesis.
"""

from typing import List, Dict, Optional, Any


def build_action_brief(regime: str,
                       regime_desc: str,
                       fii_dii: list,
                       trade_plans: list,
                       buy_opps: list,
                       sell_opps: list,
                       strategy_signals: list,
                       tech_signals: list,
                       mf_signals: list) -> dict:
    """Build the Action Brief synthesis from all dashboard data.

    Returns a dict ready for JSON serialization and rendering.
    """
    # ── Counts ───────────────────────────────────────────────────
    enter_plans = [p for p in trade_plans if p.action == "ENTER"]
    wait_plans = sorted(
        [p for p in trade_plans if p.action == "WAIT"],
        key=lambda p: p.combined_score, reverse=True,
    )
    exit_plans = [p for p in trade_plans if p.action == "EXIT"]
    avoid_count = sum(1 for p in trade_plans if p.action == "AVOID")
    total = len(trade_plans) or 1

    bullish_count = sum(1 for s in tech_signals if s.score >= 3)
    bullish_pct = round(bullish_count / max(len(tech_signals), 1) * 100)

    entry_zone = [s for s in strategy_signals if s.zone == "entry"]
    near_zone = [s for s in strategy_signals if s.zone == "near"]
    crossed_zone = [s for s in strategy_signals if s.zone == "crossed"]

    # ── FII / DII ────────────────────────────────────────────────
    fii_net = 0.0
    dii_net = 0.0
    for flow in (fii_dii or []):
        cat = flow.get("category", "")
        net = flow.get("net", 0)
        if "FII" in cat or "FPI" in cat:
            fii_net = net
        elif "DII" in cat:
            dii_net = net

    # ── Stance ───────────────────────────────────────────────────
    stance, stance_color, rationale = _compute_stance(
        regime, len(enter_plans), avoid_count, total,
        fii_net, bullish_pct,
    )

    # ── Action Items (max 5) ─────────────────────────────────────
    actions = []

    # BUY NOW — Trade Planner ENTER with quality gates
    for p in enter_plans:
        if len(actions) >= 5:
            break
        actions.append({
            "ticker": p.ticker,
            "sector": p.sector,
            "type": "BUY NOW",
            "price": _safe_round(p.close),
            "stop_loss": _safe_round(p.stop_loss),
            "sl_pct": _safe_round(p.sl_pct),
            "target": _safe_round(p.target),
            "target_pct": _safe_round(p.target_pct),
            "risk_reward": _safe_round(p.risk_reward),
            "reason": _top_reason(p),
        })

    # EXIT — confirmed sells (tech <= -2 AND flow <= -3)
    confirmed_sells = []
    for o in sell_opps:
        if o.tech_score <= -2 and o.flow_score <= -3:
            confirmed_sells.append(o)
    # Also add trade planner EXIT signals
    exit_tickers = {p.ticker for p in exit_plans}
    for o in sell_opps:
        if o.ticker in exit_tickers and o not in confirmed_sells:
            confirmed_sells.append(o)

    for o in confirmed_sells:
        if len(actions) >= 5:
            break
        actions.append({
            "ticker": o.ticker,
            "sector": o.sector,
            "type": "EXIT",
            "price": _safe_round(o.close),
            "stop_loss": None,
            "sl_pct": None,
            "target": None,
            "target_pct": None,
            "risk_reward": None,
            "reason": f"Tech {o.tech_score}, Flow {o.flow_score} — both confirm sell",
        })

    # TRAIL STOP — Strategy CROSSED stocks (already running)
    for s in crossed_zone:
        if len(actions) >= 5:
            break
        actions.append({
            "ticker": s.ticker,
            "sector": s.sector,
            "type": "TRAIL STOP",
            "price": _safe_round(s.close),
            "stop_loss": _safe_round(s.stop_loss),
            "sl_pct": _safe_round(s.sl_pct),
            "target": _safe_round(s.target_20d),
            "target_pct": None,
            "risk_reward": None,
            "reason": f"MACD crossed {s.days_since_cross}d ago — trail SL, let it run",
        })

    # ── Watchlist (max 5) ────────────────────────────────────────
    watchlist = []
    seen_tickers = {a["ticker"] for a in actions}

    # Trade Planner WAIT stocks
    for p in wait_plans:
        if len(watchlist) >= 5:
            break
        if p.ticker in seen_tickers:
            continue
        seen_tickers.add(p.ticker)
        trigger = _wait_trigger(p, regime)
        watchlist.append({
            "ticker": p.ticker,
            "sector": p.sector,
            "price": _safe_round(p.close),
            "combined_score": _safe_round(p.combined_score),
            "target_pct": _safe_round(p.target_pct),
            "risk_reward": _safe_round(p.risk_reward),
            "trigger": trigger,
        })

    # Strategy NEAR zone
    for s in near_zone:
        if len(watchlist) >= 5:
            break
        if s.ticker in seen_tickers:
            continue
        seen_tickers.add(s.ticker)
        watchlist.append({
            "ticker": s.ticker,
            "sector": s.sector,
            "price": _safe_round(s.close),
            "combined_score": None,
            "target_pct": None,
            "risk_reward": None,
            "trigger": f"RSI approaching oversold ({_safe_round(s.rsi)}), MACD converging — watch for entry zone",
        })

    # Buy opps blocked by regime (confirmed category, regime = bear)
    if regime == "bear":
        confirmed_opps = [o for o in buy_opps
                          if o.signal_category == "confirmed"
                          and o.ticker not in seen_tickers]
        for o in confirmed_opps:
            if len(watchlist) >= 5:
                break
            seen_tickers.add(o.ticker)
            watchlist.append({
                "ticker": o.ticker,
                "sector": o.sector,
                "price": _safe_round(o.close),
                "combined_score": None,
                "target_pct": _safe_round(o.target_pct),
                "risk_reward": _safe_round(o.risk_reward),
                "trigger": "Tech + Flow both bullish but bear market — needs regime shift",
            })

    # Top tech-score stocks not yet in watchlist
    tech_sorted = sorted(tech_signals, key=lambda s: s.score, reverse=True)
    for s in tech_sorted:
        if len(watchlist) >= 5:
            break
        if s.ticker in seen_tickers:
            continue
        if s.score < 3:
            break
        seen_tickers.add(s.ticker)
        # Find matching trade plan for context
        plan = next((p for p in trade_plans if p.ticker == s.ticker), None)
        trigger = "Strong technicals"
        if plan and regime == "bear":
            trigger = f"Tech score {s.score}/16 — needs regime shift (bear market suppressing)"
        elif plan:
            rr = _safe_round(plan.risk_reward)
            trigger = f"Tech score {s.score}/16 — needs R:R above 1.5 (currently {rr})"
        watchlist.append({
            "ticker": s.ticker,
            "sector": getattr(s, 'sector', ''),
            "price": _safe_round(s.close),
            "combined_score": _safe_round(plan.combined_score) if plan else None,
            "target_pct": _safe_round(plan.target_pct) if plan else None,
            "risk_reward": _safe_round(plan.risk_reward) if plan else None,
            "trigger": trigger,
        })

    # ── Conflicts ────────────────────────────────────────────────
    conflicts = _detect_conflicts(
        regime, tech_signals, trade_plans, entry_zone,
        avoid_count, total, buy_opps, sell_opps,
    )

    return {
        "stance": stance,
        "stance_color": stance_color,
        "regime": regime,
        "regime_desc": regime_desc,
        "fii_net": round(fii_net, 2),
        "dii_net": round(dii_net, 2),
        "bullish_pct": bullish_pct,
        "enter_count": len(enter_plans),
        "wait_count": len(wait_plans),
        "avoid_count": avoid_count,
        "exit_count": len(exit_plans),
        "entry_zone_count": len(entry_zone),
        "rationale": rationale,
        "actions": actions,
        "watchlist": watchlist,
        "conflicts": conflicts,
    }


# ─── Internal helpers ────────────────────────────────────────────

def _safe_round(val, decimals=2):
    if val is None:
        return None
    try:
        import math
        if math.isnan(val) or math.isinf(val):
            return None
        return round(val, decimals)
    except (TypeError, ValueError):
        return None


def _compute_stance(regime, enter_count, avoid_count, total,
                    fii_net, bullish_pct):
    """Determine market stance from regime + signal density."""
    if regime == "bear":
        if enter_count == 0:
            rationale = "Bear market"
            if fii_net < 0:
                rationale += f" + FII selling ({fii_net:+,.0f} Cr)"
            rationale += f" + zero ENTER signals = capital preservation mode"
            return "STAY IN CASH", "red", rationale
        else:
            return ("SELECTIVE BUYS", "amber",
                    f"Bear market but {enter_count} stocks breaking through — "
                    f"trade with tight stops")

    elif regime == "sideways":
        if enter_count >= 3:
            return ("SELECTIVE BUYS", "amber",
                    f"Sideways market with {enter_count} actionable setups — "
                    f"pick the best R:R")
        elif enter_count >= 1:
            return ("SELECTIVE BUYS", "amber",
                    f"Sideways market, {enter_count} setup(s) — be selective")
        else:
            return ("STAY IN CASH", "red",
                    f"Sideways market with no conviction setups — wait for clarity")

    elif regime == "bull":
        if enter_count >= 5:
            fii_note = ""
            if fii_net > 0:
                fii_note = f", FII buying (+{fii_net:,.0f} Cr)"
            return ("AGGRESSIVE", "green",
                    f"Bull market + {enter_count} ENTER signals"
                    f"{fii_note} — deploy capital")
        elif enter_count >= 1:
            return ("SELECTIVE BUYS", "amber",
                    f"Bull market but only {enter_count} setup(s) pass quality gates")
        else:
            return ("STAY IN CASH", "amber",
                    f"Bull market but no setups pass R:R filter — wait for pullback entries")

    # Unknown regime
    return ("STAY IN CASH", "red",
            "Insufficient market data — stay cautious")


def _top_reason(plan):
    """Extract the single most important reason from a trade plan."""
    reasons = getattr(plan, 'top_reasons', [])
    if reasons:
        # Pick the first technical reason
        for r in reasons:
            if r.startswith("[T]"):
                return r.replace("[T] ", "")
        return reasons[0].replace("[T] ", "").replace("[M] ", "")
    return f"Combined score {plan.combined_score:.0f}"


def _wait_trigger(plan, regime):
    """Explain what's needed for a WAIT stock to become actionable."""
    parts = []
    if regime == "bear" and "bear" in (plan.action_reason or "").lower():
        parts.append("needs regime shift (bear market suppressing)")
    if plan.risk_reward is not None and plan.risk_reward < 1.5:
        parts.append(f"R:R is {plan.risk_reward:.1f} (needs >= 1.5)")
    if not parts:
        parts.append(plan.action_reason or "waiting for confirmation")
    return " + ".join(parts).capitalize()


def _detect_conflicts(regime, tech_signals, trade_plans, entry_zone,
                      avoid_count, total, buy_opps, sell_opps):
    """Detect and explain tab conflicts in plain language."""
    conflicts = []
    avoid_pct = round(avoid_count / max(total, 1) * 100)

    # Conflict 1: Strategy Entry Zone vs Trade Planner AVOID
    if len(entry_zone) >= 3 and avoid_pct >= 80:
        conflicts.append(
            f"{len(entry_zone)} stocks in Strategy Entry Zone (oversold RSI) "
            f"but Trade Planner says AVOID for {avoid_pct}% of stocks — "
            f"bear market is pulling RSI down across the board. "
            f"These are not individual buy setups, it's broad market weakness."
        )

    # Conflict 2: Technical BUY/STRONG BUY but Trade Planner AVOID
    plan_actions = {p.ticker: p.action for p in trade_plans}
    tech_buys_avoided = [
        s for s in tech_signals
        if s.action in ("BUY", "STRONG BUY")
        and plan_actions.get(s.ticker) == "AVOID"
    ]
    if tech_buys_avoided:
        tickers = ", ".join(s.ticker for s in tech_buys_avoided[:3])
        more = f" +{len(tech_buys_avoided) - 3} more" if len(tech_buys_avoided) > 3 else ""
        verb = "shows" if len(tech_buys_avoided) == 1 else "show"
        conflicts.append(
            f"{tickers}{more} {verb} BUY on technicals but Trade Planner says AVOID — "
            f"bear market regime filter is suppressing all buy signals until "
            f"Nifty reclaims EMA 20 > EMA 50."
        )

    # Conflict 3: Buy opps with poor R:R
    # Check for stocks that passed tech filters but have bad R:R
    poor_rr = [
        s for s in tech_signals
        if s.score >= 3
        and any(p.ticker == s.ticker
                and p.risk_reward is not None
                and p.risk_reward < 1.5
                for p in trade_plans)
    ]
    if poor_rr:
        for s in poor_rr[:2]:
            plan = next((p for p in trade_plans if p.ticker == s.ticker), None)
            if plan and plan.risk_reward is not None:
                conflicts.append(
                    f"{s.ticker} has tech score {s.score}/16 but R:R is only "
                    f"{plan.risk_reward:.1f} — resistance too close or stop too wide. "
                    f"Wait for a pullback to improve entry."
                )

    # Conflict 4: Trap signals (tech up, money exiting)
    traps = [o for o in (buy_opps + sell_opps)
             if o.signal_category == "trap"]
    if traps:
        tickers = ", ".join(o.ticker for o in traps[:3])
        conflicts.append(
            f"{tickers}: technicals look bullish but money is flowing OUT (trap signal). "
            f"Smart money may be distributing — avoid despite positive technicals."
        )

    return conflicts
