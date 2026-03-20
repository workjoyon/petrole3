"""Narrative generator — produces human-readable simulation explanations."""

from __future__ import annotations

from app.engine.types import SimulationResult


def generate_narrative(result: SimulationResult, scenario_name: str = "Unnamed") -> str:
    """Generate a Markdown narrative from simulation results."""
    lines: list[str] = []

    lines.append(f"## Simulation: {scenario_name}")
    lines.append("")
    lines.append(f"**Global Supply Loss**: {result.global_supply_loss_pct:.1f}%")
    lines.append(f"**Estimated Price Impact**: +{result.estimated_price_impact_pct:.1f}%")
    lines.append(f"**Global Stress Score**: {result.global_stress_score:.1f}/100")
    lines.append("")

    # Status summary
    s = result.summary
    lines.append("### Country Status Summary")
    lines.append(f"- **Stable**: {s.get('countries_stable', 0)}")
    lines.append(f"- **Under Tension**: {s.get('countries_tension', 0)}")
    lines.append(f"- **Critical**: {s.get('countries_critical', 0)}")
    lines.append(f"- **Emergency**: {s.get('countries_emergency', 0)}")
    lines.append("")

    # Top affected countries
    top = s.get("top_affected", [])
    if top:
        lines.append("### Most Affected Countries")
        for i, c in enumerate(top, 1):
            lines.append(
                f"{i}. **{c['country_code']}** — "
                f"stress {c['stress_score']:.0f}/100 ({c['stress_status']}), "
                f"demand coverage {c['demand_coverage_ratio']:.1%}"
            )
        lines.append("")

    # Flow losses
    total_loss = s.get("total_flow_loss_mbpd", 0)
    if total_loss > 0:
        lines.append("### Flow Disruptions")
        lines.append(f"Total flow volume lost: **{total_loss:.2f} Mb/d**")
        lines.append("")

        # Top disrupted flows
        disrupted = sorted(
            [f for f in result.flow_impacts if f.loss_pct > 0],
            key=lambda f: f.volume_before - f.volume_after,
            reverse=True,
        )[:10]

        if disrupted:
            lines.append("Top disrupted flows:")
            for f in disrupted:
                lines.append(
                    f"- **{f.flow_id}**: {f.volume_before:.3f} → "
                    f"{f.volume_after:.3f} Mb/d ({f.loss_pct:.0f}% loss)"
                )
            lines.append("")

    # Causal trace summary
    lines.append("### Causal Trace")
    for step in result.steps:
        if step.rule_id in ("INIT", "DONE"):
            continue
        lines.append(f"- **Step {step.step_number} [{step.rule_id}]**: {step.description}")
    lines.append("")

    # Disclaimer
    lines.append("---")
    lines.append(
        "*This is a deterministic what-if analysis, not a prediction. "
        "Price impact uses a simplified elasticity model (factor=3.0). "
        "See documentation for assumptions and limitations.*"
    )

    return "\n".join(lines)
