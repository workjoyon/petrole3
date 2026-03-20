"""API routes for reference data: countries, regions, chokepoints, routes, flows, ports."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Chokepoint,
    Country,
    Flow,
    Port,
    Region,
    Route,
)
from app.db.session import get_db
from app.domain.schemas import (
    ChokepointOut,
    CountryOut,
    FlowOut,
    PortOut,
    RegionOut,
    RouteChokepointOut,
    RouteOut,
)

router = APIRouter(tags=["reference"])


@router.get("/regions", response_model=list[RegionOut])
async def list_regions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Region).order_by(Region.name))
    return result.scalars().all()


@router.get("/countries", response_model=list[CountryOut])
async def list_countries(
    region_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Country).order_by(Country.name)
    if region_id:
        q = q.where(Country.region_id == region_id)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/countries/{code}", response_model=CountryOut)
async def get_country(code: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Country).where(Country.code == code.upper()))
    country = result.scalar_one_or_none()
    if not country:
        raise HTTPException(404, f"Country '{code}' not found")
    return country


@router.get("/chokepoints", response_model=list[ChokepointOut])
async def list_chokepoints(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Chokepoint).order_by(Chokepoint.name))
    return result.scalars().all()


@router.get("/routes", response_model=list[RouteOut])
async def list_routes(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Route).options(selectinload(Route.chokepoint_links)).order_by(Route.name)
    )
    routes = result.scalars().all()
    out = []
    for r in routes:
        out.append(RouteOut(
            id=r.id,
            name=r.name,
            route_type=r.route_type,
            chokepoints=[
                RouteChokepointOut(chokepoint_id=rc.chokepoint_id, order_index=rc.order_index)
                for rc in sorted(r.chokepoint_links, key=lambda x: x.order_index)
            ],
        ))
    return out


@router.get("/flows", response_model=list[FlowOut])
async def list_flows(
    exporter: str | None = Query(None),
    importer: str | None = Query(None),
    product: str | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    q = select(Flow)
    if exporter:
        q = q.where(Flow.exporter_code == exporter.upper())
    if importer:
        q = q.where(Flow.importer_code == importer.upper())
    if product:
        q = q.where(Flow.product_id == product)
    q = q.order_by(Flow.volume_mbpd.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/ports", response_model=list[PortOut])
async def list_ports(
    country: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Port).order_by(Port.name)
    if country:
        q = q.where(Port.country_code == country.upper())
    result = await db.execute(q)
    return result.scalars().all()
