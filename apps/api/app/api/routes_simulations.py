"""API routes for simulation execution and results."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Chokepoint,
    Country,
    Flow,
    Route,
    RouteChokepoint,
    Scenario,
    SimulationCountryImpact,
    SimulationFlowImpact,
    SimulationRun,
    SimulationStep,
)
from app.db.session import get_db
from app.domain.schemas import (
    CountryImpactOut,
    FlowImpactOut,
    NarrativeOut,
    SimulationRunCombinedRequest,
    SimulationRunOut,
    SimulationRunRequest,
    SimulationStepOut,
)
from app.engine.core import SimulationEngine
from app.engine.narrative import generate_narrative

router = APIRouter(prefix="/simulations", tags=["simulations"])


async def _load_reference_data(db: AsyncSession) -> dict:
    """Load all reference data needed for the simulation engine."""
    countries_r = await db.execute(select(Country))
    countries = [
        {
            "code": c.code, "name": c.name, "region_id": c.region_id,
            "production_mbpd": c.production_mbpd, "consumption_mbpd": c.consumption_mbpd,
            "refining_capacity_mbpd": c.refining_capacity_mbpd,
            "strategic_reserves_mb": c.strategic_reserves_mb,
            "reserve_release_rate_mbpd": c.reserve_release_rate_mbpd,
            "is_refining_hub": c.is_refining_hub,
            "domestic_priority_ratio": c.domestic_priority_ratio,
            "longitude": c.longitude, "latitude": c.latitude,
        }
        for c in countries_r.scalars().all()
    ]

    flows_r = await db.execute(select(Flow))
    flows = [
        {
            "id": f.id, "exporter_code": f.exporter_code,
            "importer_code": f.importer_code, "product_id": f.product_id,
            "volume_mbpd": f.volume_mbpd, "route_id": f.route_id,
        }
        for f in flows_r.scalars().all()
    ]

    cps_r = await db.execute(select(Chokepoint))
    chokepoints = [
        {"id": cp.id, "name": cp.name, "throughput_mbpd": cp.throughput_mbpd}
        for cp in cps_r.scalars().all()
    ]

    routes_r = await db.execute(select(Route))
    routes = [
        {"id": r.id, "name": r.name, "route_type": r.route_type}
        for r in routes_r.scalars().all()
    ]

    rcs_r = await db.execute(
        select(RouteChokepoint).order_by(RouteChokepoint.route_id, RouteChokepoint.order_index)
    )
    route_chokepoints = [
        {"route_id": rc.route_id, "chokepoint_id": rc.chokepoint_id, "order_index": rc.order_index}
        for rc in rcs_r.scalars().all()
    ]

    return {
        "countries": countries,
        "flows": flows,
        "chokepoints": chokepoints,
        "routes": routes,
        "route_chokepoints": route_chokepoints,
    }


@router.post("/run", response_model=SimulationRunOut, status_code=201)
async def run_simulation(body: SimulationRunRequest, db: AsyncSession = Depends(get_db)):
    # Load scenario
    result = await db.execute(
        select(Scenario)
        .options(selectinload(Scenario.actions))
        .where(Scenario.id == body.scenario_id)
    )
    scenario = result.scalar_one_or_none()
    if not scenario:
        raise HTTPException(404, "Scenario not found")

    # Load reference data
    ref = await _load_reference_data(db)

    # Build actions list
    actions = [
        {
            "action_type": a.action_type,
            "target_id": a.target_id,
            "severity": a.severity,
            "params": a.params or {},
        }
        for a in scenario.actions
    ]

    # Run simulation
    engine = SimulationEngine()
    sim_result = engine.run(
        countries=ref["countries"],
        flows=ref["flows"],
        chokepoints=ref["chokepoints"],
        routes=ref["routes"],
        route_chokepoints=ref["route_chokepoints"],
        actions=actions,
    )

    # Persist results
    run_id = uuid.uuid4()
    run = SimulationRun(
        id=run_id,
        scenario_id=scenario.id,
        status="completed",
        duration_ms=sim_result.duration_ms,
        global_stress_score=sim_result.global_stress_score,
        global_supply_loss_pct=sim_result.global_supply_loss_pct,
        estimated_price_impact_pct=sim_result.estimated_price_impact_pct,
        summary=sim_result.summary,
    )
    db.add(run)

    # Country impacts
    for ci in sim_result.country_impacts:
        db.add(SimulationCountryImpact(
            id=uuid.uuid4(),
            run_id=run_id,
            country_code=ci.country_code,
            production_before=ci.production_before,
            production_after=ci.production_after,
            consumption=ci.consumption,
            imports_before=ci.imports_before,
            imports_after=ci.imports_after,
            exports_before=ci.exports_before,
            exports_after=ci.exports_after,
            domestic_available=ci.domestic_available,
            demand_coverage_ratio=ci.demand_coverage_ratio,
            stress_score=ci.stress_score,
            stress_status=ci.stress_status,
            reserve_mobilized_mbpd=ci.reserve_mobilized_mbpd,
        ))

    # Flow impacts
    for fi in sim_result.flow_impacts:
        db.add(SimulationFlowImpact(
            id=uuid.uuid4(),
            run_id=run_id,
            flow_id=fi.flow_id,
            volume_before=fi.volume_before,
            volume_after=fi.volume_after,
            loss_pct=fi.loss_pct,
            loss_reasons=fi.loss_reasons,
        ))

    # Journal steps
    for step in sim_result.steps:
        db.add(SimulationStep(
            id=uuid.uuid4(),
            run_id=run_id,
            step_number=step.step_number,
            rule_id=step.rule_id,
            description=step.description,
            affected_entities=step.affected_entities,
            detail=step.detail,
        ))

    await db.flush()
    await db.refresh(run)
    return run


@router.post("/run-combined", response_model=SimulationRunOut, status_code=201)
async def run_combined_simulation(body: SimulationRunCombinedRequest, db: AsyncSession = Depends(get_db)):
    """Run a simulation combining actions from multiple scenarios."""
    # Load all selected scenarios
    result = await db.execute(
        select(Scenario)
        .options(selectinload(Scenario.actions))
        .where(Scenario.id.in_(body.scenario_ids))
    )
    scenarios = result.scalars().all()
    if len(scenarios) != len(body.scenario_ids):
        raise HTTPException(404, "One or more scenarios not found")

    # Merge all actions from all scenarios
    actions = []
    for scenario in scenarios:
        for a in scenario.actions:
            actions.append({
                "action_type": a.action_type,
                "target_id": a.target_id,
                "severity": a.severity,
                "params": a.params or {},
            })

    if not actions:
        raise HTTPException(400, "Selected scenarios have no actions")

    # Create a temporary combined scenario
    combined_name = " + ".join(s.name for s in scenarios)
    combined_scenario = Scenario(
        id=uuid.uuid4(),
        name=f"[Combined] {combined_name}"[:300],
        name_fr=None,
        description=f"Combined simulation from {len(scenarios)} scenarios",
        description_fr=f"Simulation combinée de {len(scenarios)} scénarios",
        is_preset=False,
    )
    db.add(combined_scenario)
    await db.flush()

    # Load reference data and run
    ref = await _load_reference_data(db)
    engine = SimulationEngine()
    sim_result = engine.run(
        countries=ref["countries"],
        flows=ref["flows"],
        chokepoints=ref["chokepoints"],
        routes=ref["routes"],
        route_chokepoints=ref["route_chokepoints"],
        actions=actions,
    )

    # Persist results
    run_id = uuid.uuid4()
    run = SimulationRun(
        id=run_id,
        scenario_id=combined_scenario.id,
        status="completed",
        duration_ms=sim_result.duration_ms,
        global_stress_score=sim_result.global_stress_score,
        global_supply_loss_pct=sim_result.global_supply_loss_pct,
        estimated_price_impact_pct=sim_result.estimated_price_impact_pct,
        summary=sim_result.summary,
    )
    db.add(run)

    for ci in sim_result.country_impacts:
        db.add(SimulationCountryImpact(
            id=uuid.uuid4(), run_id=run_id,
            country_code=ci.country_code,
            production_before=ci.production_before, production_after=ci.production_after,
            consumption=ci.consumption,
            imports_before=ci.imports_before, imports_after=ci.imports_after,
            exports_before=ci.exports_before, exports_after=ci.exports_after,
            domestic_available=ci.domestic_available,
            demand_coverage_ratio=ci.demand_coverage_ratio,
            stress_score=ci.stress_score, stress_status=ci.stress_status,
            reserve_mobilized_mbpd=ci.reserve_mobilized_mbpd,
        ))

    for fi in sim_result.flow_impacts:
        db.add(SimulationFlowImpact(
            id=uuid.uuid4(), run_id=run_id,
            flow_id=fi.flow_id,
            volume_before=fi.volume_before, volume_after=fi.volume_after,
            loss_pct=fi.loss_pct, loss_reasons=fi.loss_reasons,
        ))

    for step in sim_result.steps:
        db.add(SimulationStep(
            id=uuid.uuid4(), run_id=run_id,
            step_number=step.step_number, rule_id=step.rule_id,
            description=step.description,
            affected_entities=step.affected_entities, detail=step.detail,
        ))

    await db.flush()
    await db.refresh(run)
    return run


@router.get("/{run_id}", response_model=SimulationRunOut)
async def get_simulation(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SimulationRun).where(SimulationRun.id == run_id)
    )
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Simulation run not found")
    return run


@router.get("/{run_id}/countries", response_model=list[CountryImpactOut])
async def get_simulation_countries(
    run_id: uuid.UUID,
    sort_by: str = Query("stress_score"),
    order: str = Query("desc"),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    q = select(SimulationCountryImpact).where(SimulationCountryImpact.run_id == run_id)

    col = getattr(SimulationCountryImpact, sort_by, SimulationCountryImpact.stress_score)
    if order == "asc":
        q = q.order_by(col.asc())
    else:
        q = q.order_by(col.desc())
    q = q.limit(limit)

    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{run_id}/flows", response_model=list[FlowImpactOut])
async def get_simulation_flows(
    run_id: uuid.UUID,
    min_loss_pct: float = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(SimulationFlowImpact)
        .where(SimulationFlowImpact.run_id == run_id)
        .where(SimulationFlowImpact.loss_pct >= min_loss_pct)
        .order_by(SimulationFlowImpact.loss_pct.desc())
        .limit(limit)
    )
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{run_id}/journal", response_model=list[SimulationStepOut])
async def get_simulation_journal(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    q = (
        select(SimulationStep)
        .where(SimulationStep.run_id == run_id)
        .order_by(SimulationStep.step_number)
    )
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{run_id}/narrative", response_model=NarrativeOut)
async def get_simulation_narrative(run_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    # Load the run
    run_r = await db.execute(
        select(SimulationRun)
        .options(selectinload(SimulationRun.scenario))
        .where(SimulationRun.id == run_id)
    )
    run = run_r.scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Simulation run not found")

    # Load impacts and steps
    ci_r = await db.execute(
        select(SimulationCountryImpact)
        .where(SimulationCountryImpact.run_id == run_id)
        .order_by(SimulationCountryImpact.stress_score.desc())
    )
    fi_r = await db.execute(
        select(SimulationFlowImpact)
        .where(SimulationFlowImpact.run_id == run_id)
        .order_by(SimulationFlowImpact.loss_pct.desc())
    )
    steps_r = await db.execute(
        select(SimulationStep)
        .where(SimulationStep.run_id == run_id)
        .order_by(SimulationStep.step_number)
    )

    from app.engine.types import (
        CountryImpactResult,
        FlowImpactResult,
        SimulationResult,
        SimulationStep as SimStep,
    )

    country_impacts = [
        CountryImpactResult(
            country_code=ci.country_code,
            production_before=ci.production_before,
            production_after=ci.production_after,
            consumption=ci.consumption,
            imports_before=ci.imports_before,
            imports_after=ci.imports_after,
            exports_before=ci.exports_before,
            exports_after=ci.exports_after,
            domestic_available=ci.domestic_available,
            demand_coverage_ratio=ci.demand_coverage_ratio,
            stress_score=ci.stress_score,
            stress_status=ci.stress_status,
            reserve_mobilized_mbpd=ci.reserve_mobilized_mbpd,
        )
        for ci in ci_r.scalars().all()
    ]

    flow_impacts = [
        FlowImpactResult(
            flow_id=fi.flow_id,
            volume_before=fi.volume_before,
            volume_after=fi.volume_after,
            loss_pct=fi.loss_pct,
            loss_reasons=fi.loss_reasons or [],
        )
        for fi in fi_r.scalars().all()
    ]

    steps = [
        SimStep(
            step_number=s.step_number,
            rule_id=s.rule_id,
            description=s.description,
            affected_entities=s.affected_entities or {},
            detail=s.detail or {},
        )
        for s in steps_r.scalars().all()
    ]

    sim_result = SimulationResult(
        global_stress_score=run.global_stress_score or 0,
        global_supply_loss_pct=run.global_supply_loss_pct or 0,
        estimated_price_impact_pct=run.estimated_price_impact_pct or 0,
        country_impacts=country_impacts,
        flow_impacts=flow_impacts,
        steps=steps,
        summary=run.summary or {},
    )

    narrative = generate_narrative(sim_result, scenario_name=run.scenario.name)
    return NarrativeOut(narrative=narrative)
