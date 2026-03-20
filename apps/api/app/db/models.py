import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.db.session import Base


class Region(Base):
    __tablename__ = "regions"

    id = Column(String(50), primary_key=True)
    name = Column(String(200), nullable=False)

    countries = relationship("Country", back_populates="region")


class Country(Base):
    __tablename__ = "countries"

    code = Column(String(3), primary_key=True)
    name = Column(String(200), nullable=False)
    region_id = Column(String(50), ForeignKey("regions.id"), nullable=False)
    production_mbpd = Column(Float, nullable=False, default=0.0)
    consumption_mbpd = Column(Float, nullable=False, default=0.0)
    refining_capacity_mbpd = Column(Float, nullable=False, default=0.0)
    strategic_reserves_mb = Column(Float, nullable=False, default=0.0)
    reserve_release_rate_mbpd = Column(Float, nullable=False, default=0.0)
    is_refining_hub = Column(Boolean, nullable=False, default=False)
    domestic_priority_ratio = Column(Float, nullable=False, default=0.3)
    longitude = Column(Float, nullable=False)
    latitude = Column(Float, nullable=False)

    region = relationship("Region", back_populates="countries")
    exports = relationship("Flow", foreign_keys="Flow.exporter_code", back_populates="exporter")
    imports = relationship("Flow", foreign_keys="Flow.importer_code", back_populates="importer")

    __table_args__ = (
        CheckConstraint("production_mbpd >= 0", name="ck_country_production"),
        CheckConstraint("consumption_mbpd >= 0", name="ck_country_consumption"),
        CheckConstraint("domestic_priority_ratio >= 0 AND domestic_priority_ratio <= 1", name="ck_country_dpr"),
    )


class Port(Base):
    __tablename__ = "ports"

    id = Column(String(50), primary_key=True)
    name = Column(String(200), nullable=False)
    country_code = Column(String(3), ForeignKey("countries.code"), nullable=False)
    capacity_mbpd = Column(Float, nullable=False, default=0.0)
    port_type = Column(String(20), nullable=False)
    longitude = Column(Float, nullable=False)
    latitude = Column(Float, nullable=False)

    __table_args__ = (
        CheckConstraint("port_type IN ('export', 'import', 'both')", name="ck_port_type"),
    )


class Chokepoint(Base):
    __tablename__ = "chokepoints"

    id = Column(String(50), primary_key=True)
    name = Column(String(200), nullable=False)
    throughput_mbpd = Column(Float, nullable=False, default=0.0)
    longitude = Column(Float, nullable=False)
    latitude = Column(Float, nullable=False)

    route_links = relationship("RouteChokepoint", back_populates="chokepoint")


class Route(Base):
    __tablename__ = "routes"

    id = Column(String(50), primary_key=True)
    name = Column(String(300), nullable=False)
    route_type = Column(String(20), nullable=False, default="maritime")

    chokepoint_links = relationship(
        "RouteChokepoint", back_populates="route", order_by="RouteChokepoint.order_index"
    )
    flows = relationship("Flow", back_populates="route")

    __table_args__ = (
        CheckConstraint("route_type IN ('maritime', 'pipeline', 'mixed')", name="ck_route_type"),
    )


class RouteChokepoint(Base):
    __tablename__ = "route_chokepoints"

    route_id = Column(String(50), ForeignKey("routes.id"), primary_key=True)
    chokepoint_id = Column(String(50), ForeignKey("chokepoints.id"), primary_key=True)
    order_index = Column(Integer, nullable=False)

    route = relationship("Route", back_populates="chokepoint_links")
    chokepoint = relationship("Chokepoint", back_populates="route_links")


class Product(Base):
    __tablename__ = "products"

    id = Column(String(20), primary_key=True)
    name = Column(String(100), nullable=False)


class Flow(Base):
    __tablename__ = "flows"

    id = Column(String(100), primary_key=True)
    exporter_code = Column(String(3), ForeignKey("countries.code"), nullable=False)
    importer_code = Column(String(3), ForeignKey("countries.code"), nullable=False)
    product_id = Column(String(20), ForeignKey("products.id"), nullable=False)
    volume_mbpd = Column(Float, nullable=False)
    route_id = Column(String(50), ForeignKey("routes.id"), nullable=False)
    confidence = Column(String(20), nullable=False, default="medium")
    source = Column(String(500), nullable=True)

    exporter = relationship("Country", foreign_keys=[exporter_code], back_populates="exports")
    importer = relationship("Country", foreign_keys=[importer_code], back_populates="imports")
    route = relationship("Route", back_populates="flows")

    __table_args__ = (
        CheckConstraint("volume_mbpd >= 0", name="ck_flow_volume"),
        CheckConstraint(
            "confidence IN ('high', 'medium', 'low', 'estimated')", name="ck_flow_confidence"
        ),
        Index("ix_flow_exporter", "exporter_code"),
        Index("ix_flow_importer", "importer_code"),
        Index("ix_flow_route", "route_id"),
    )


class Scenario(Base):
    __tablename__ = "scenarios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(300), nullable=False)
    name_fr = Column(String(300), nullable=True)
    description = Column(Text, nullable=True)
    description_fr = Column(Text, nullable=True)
    is_preset = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    actions = relationship(
        "ScenarioAction",
        back_populates="scenario",
        cascade="all, delete-orphan",
        order_by="ScenarioAction.order_index",
    )
    simulation_runs = relationship("SimulationRun", back_populates="scenario")


class ScenarioAction(Base):
    __tablename__ = "scenario_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scenario_id = Column(UUID(as_uuid=True), ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False)
    action_type = Column(String(50), nullable=False)
    target_id = Column(String(100), nullable=False)
    severity = Column(Float, nullable=False, default=1.0)
    params = Column(JSONB, nullable=False, default=dict)
    order_index = Column(Integer, nullable=False, default=0)

    scenario = relationship("Scenario", back_populates="actions")

    __table_args__ = (
        CheckConstraint("severity >= 0 AND severity <= 1", name="ck_action_severity"),
        Index("ix_action_scenario", "scenario_id"),
    )


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scenario_id = Column(UUID(as_uuid=True), ForeignKey("scenarios.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    duration_ms = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="running")
    global_stress_score = Column(Float, nullable=True)
    global_supply_loss_pct = Column(Float, nullable=True)
    estimated_price_impact_pct = Column(Float, nullable=True)
    summary = Column(JSONB, nullable=True)

    scenario = relationship("Scenario", back_populates="simulation_runs")
    country_impacts = relationship(
        "SimulationCountryImpact", back_populates="run", cascade="all, delete-orphan"
    )
    flow_impacts = relationship(
        "SimulationFlowImpact", back_populates="run", cascade="all, delete-orphan"
    )
    steps = relationship(
        "SimulationStep", back_populates="run", cascade="all, delete-orphan", order_by="SimulationStep.step_number"
    )


class SimulationCountryImpact(Base):
    __tablename__ = "simulation_country_impacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False)
    country_code = Column(String(3), ForeignKey("countries.code"), nullable=False)
    production_before = Column(Float, nullable=False)
    production_after = Column(Float, nullable=False)
    consumption = Column(Float, nullable=False)
    imports_before = Column(Float, nullable=False)
    imports_after = Column(Float, nullable=False)
    exports_before = Column(Float, nullable=False)
    exports_after = Column(Float, nullable=False)
    domestic_available = Column(Float, nullable=False)
    demand_coverage_ratio = Column(Float, nullable=False)
    stress_score = Column(Float, nullable=False)
    stress_status = Column(String(20), nullable=False)
    reserve_mobilized_mbpd = Column(Float, nullable=False, default=0.0)

    run = relationship("SimulationRun", back_populates="country_impacts")

    __table_args__ = (
        Index("ix_ci_run", "run_id"),
        Index("ix_ci_country", "country_code"),
    )


class SimulationFlowImpact(Base):
    __tablename__ = "simulation_flow_impacts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False)
    flow_id = Column(String(100), ForeignKey("flows.id"), nullable=False)
    volume_before = Column(Float, nullable=False)
    volume_after = Column(Float, nullable=False)
    loss_pct = Column(Float, nullable=False)
    loss_reasons = Column(JSONB, nullable=False, default=list)

    run = relationship("SimulationRun", back_populates="flow_impacts")

    __table_args__ = (Index("ix_fi_run", "run_id"),)


class SimulationStep(Base):
    __tablename__ = "simulation_steps"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("simulation_runs.id", ondelete="CASCADE"), nullable=False)
    step_number = Column(Integer, nullable=False)
    rule_id = Column(String(10), nullable=False)
    description = Column(Text, nullable=False)
    affected_entities = Column(JSONB, nullable=False, default=dict)
    detail = Column(JSONB, nullable=False, default=dict)

    run = relationship("SimulationRun", back_populates="steps")

    __table_args__ = (Index("ix_step_run_num", "run_id", "step_number"),)


class DataSnapshot(Base):
    __tablename__ = "data_snapshots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    source = Column(String(500), nullable=True)
    period = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)


class SourceProvenance(Base):
    __tablename__ = "source_provenance"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(100), nullable=False)
    source_name = Column(String(300), nullable=False)
    source_url = Column(String(500), nullable=True)
    source_date = Column(String(20), nullable=True)
    coverage = Column(String(200), nullable=True)
    confidence = Column(String(20), nullable=True)
    notes = Column(Text, nullable=True)
