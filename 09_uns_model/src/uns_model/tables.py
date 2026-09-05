"""*******************************************************************************
* Copyright (c) 2021 Ashwin Krishnan
*
* All rights reserved. This program and the accompanying materials
* are made available under the terms of MIT and  is provided "as is",
* without warranty of any kind, express or implied, including but
* not limited to the warranties of merchantability, fitness for a
* particular purpose and noninfringement. In no event shall the
* authors, contributors or copyright holders be liable for any claim,
* damages or other liability, whether in an action of contract,
* tort or otherwise, arising from, out of or in connection with the software
* or the use or other dealings in the software.
*
* Contributors:
*    -
*******************************************************************************

Declarative models for the authored Asset Model in schema `model`, and for the
console configuration in schema `console`.

These tables are low-volume, relational and human-edited, which is what the ORM
is for. Nothing time-series is defined here: the hypertables and their continuous
aggregates are not part of this metadata, so `create_all()` produces an
incomplete database and must not be used outside unit tests (ADR-0004).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from uns_model.model_config import CONSOLE_SCHEMA, MODEL_SCHEMA

# The canonical Asset Levels, coarsest first. A branch may skip any of them —
# the simulator publishes ENTERPRISE/SITE/AREA/LINE/WORK_CELL/MACHINE with no
# PRODUCTION_UNIT — which is why an Asset stores its own level.
ASSET_LEVELS: tuple[tuple[str, int, str], ...] = (
    ("ENTERPRISE", 0, "The organisation as a whole"),
    ("SITE", 1, "A physical plant or facility"),
    ("AREA", 2, "A production area within a Site"),
    ("PRODUCTION_UNIT", 3, "An ISA-95 production unit within an Area"),
    ("LINE", 4, "A production line"),
    ("WORK_CELL", 5, "A cell within a Line"),
    ("MACHINE", 6, "A machine or PLC that publishes Metrics"),
)


class Base(DeclarativeBase):
    """Declarative base for every authored table."""


class AssetLevel(Base):
    """A name for an Asset's rank in the Asset Model."""

    __tablename__ = "asset_level"
    __table_args__ = {"schema": MODEL_SCHEMA}

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    rank: Mapped[int] = mapped_column(SmallInteger, nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    def __repr__(self) -> str:
        return f"AssetLevel(name={self.name!r}, rank={self.rank})"


class Asset(Base):
    """
    A thing the plant model declares exists.

    `path` is the topic prefix the Asset publishes under, and is the natural key
    everything else joins on. `parent_id` carries the tree so that deleting a Site
    deletes what is under it; `path` is kept alongside it because resolving a topic
    means matching a prefix, not walking a tree.
    """

    __tablename__ = "asset"
    __table_args__ = (
        UniqueConstraint("path", name="uq_asset_path"),
        UniqueConstraint("parent_id", "segment", name="uq_asset_sibling_segment"),
        CheckConstraint("segment <> ''", name="ck_asset_segment_not_empty"),
        # right()/length() rather than LIKE: '%/' || segment would treat an
        # underscore in the segment as a wildcard and let a wrong path through.
        CheckConstraint(
            "path = segment OR right(path, length(segment) + 1) = '/' || segment",
            name="ck_asset_path_ends_with_segment",
        ),
        CheckConstraint("id <> parent_id", name="ck_asset_not_its_own_parent"),
        Index("idx_asset_parent", "parent_id"),
        Index("idx_asset_level", "level"),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.asset.id", ondelete="CASCADE"),
        nullable=True,
    )
    segment: Mapped[str] = mapped_column(Text, nullable=False)
    """The single topic segment naming this Asset, e.g. 'G1'."""

    path: Mapped[str] = mapped_column(Text, nullable=False)
    """The full topic prefix, e.g. 'CovestroAG/Dormagen/Production/Line1/Cell1/G1'."""

    level: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{MODEL_SCHEMA}.asset_level.name", onupdate="CASCADE"),
        nullable=False,
    )

    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    serial_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    criticality: Mapped[str | None] = mapped_column(Text, nullable=True)
    commissioned_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    """Site-specific facts that do not deserve a column. Enriched onto reads as-is."""

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    parent: Mapped[Asset | None] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list[Asset]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    metric_definitions: Mapped[list[MetricDefinition]] = relationship(
        back_populates="asset",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def name(self) -> str:
        """What a human should see: the display name if one was authored."""
        return self.display_name or self.segment

    def __repr__(self) -> str:
        return f"Asset(path={self.path!r}, level={self.level!r})"


class MetricDefinition(Base):
    """
    The authored description of a Metric, keyed by Metric Key.

    A null `asset_id` means "every Asset", which is how one row gives `°C` to the
    Temperature of all forty mixers. An Asset-specific row wins over a null one.
    """

    __tablename__ = "metric_definition"
    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "metric_key",
            name="uq_metric_definition_asset_key",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("metric_key <> ''", name="ck_metric_definition_key_not_empty"),
        CheckConstraint(
            "min_value IS NULL OR max_value IS NULL OR min_value <= max_value",
            name="ck_metric_definition_range",
        ),
        Index("idx_metric_definition_key", "metric_key"),
        {"schema": MODEL_SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.asset.id", ondelete="CASCADE"),
        nullable=True,
    )
    metric_key: Mapped[str] = mapped_column(Text, nullable=False)
    """e.g. 'ProcessValue/Temperature/value'."""

    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_of_measure: Mapped[str | None] = mapped_column(Text, nullable=True)
    """The physical unit, e.g. '°C'. Never abbreviated to `unit` (see CONTEXT.md)."""

    decimals: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    min_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    deadband: Mapped[float | None] = mapped_column(Double, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    asset: Mapped[Asset | None] = relationship(back_populates="metric_definitions")

    def __repr__(self) -> str:
        return f"MetricDefinition(metric_key={self.metric_key!r}, unit_of_measure={self.unit_of_measure!r})"


class TopicBinding(Base):
    """
    The resolved link from one observed topic to its Asset.

    Derived, never authored: the historian inserts a row the first time it sees a
    topic, and every write to `asset` invalidates it. Its whole purpose is to turn
    an unindexable longest-prefix match into an equality join, by paying for the
    match once per distinct topic instead of once per row (ADR-0003).
    """

    __tablename__ = "topic_binding"
    __table_args__ = (
        Index("idx_topic_binding_asset", "asset_id"),
        {"schema": MODEL_SCHEMA},
    )

    topic: Mapped[str] = mapped_column(Text, primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(f"{MODEL_SCHEMA}.asset.id", ondelete="SET NULL"),
        nullable=True,
    )
    metric_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    """Topic segments below the Asset. Empty when the topic is the Asset itself."""

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    def __repr__(self) -> str:
        return f"TopicBinding(topic={self.topic!r}, asset_id={self.asset_id!r})"


class AccessGroup(Base):
    __tablename__ = "access_group"
    __table_args__ = (
        UniqueConstraint("name", name="uq_access_group_name"),
        CheckConstraint("name <> ''", name="ck_access_group_name_not_empty"),
        {"schema": MODEL_SCHEMA},
    )
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class AccessGroupRoot(Base):
    __tablename__ = "access_group_root"
    __table_args__ = (
        UniqueConstraint("group_id", "asset_id", name="uq_access_group_root"),
        {"schema": MODEL_SCHEMA},
    )
    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{MODEL_SCHEMA}.access_group.id", ondelete="CASCADE"), primary_key=True
    )
    asset_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{MODEL_SCHEMA}.asset.id", ondelete="CASCADE"), primary_key=True
    )


class AccessGroupMember(Base):
    __tablename__ = "access_group_member"
    __table_args__ = (
        UniqueConstraint("group_id", "subject", name="uq_access_group_member"),
        CheckConstraint("subject <> ''", name="ck_access_group_member_subject_not_empty"),
        {"schema": MODEL_SCHEMA},
    )
    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey(f"{MODEL_SCHEMA}.access_group.id", ondelete="CASCADE"), primary_key=True
    )
    subject: Mapped[str] = mapped_column(Text, primary_key=True)


# The vocabularies the console writes. Declared once here so the CHECK
# constraints, the migration and the GraphQL enums cannot drift apart.
ALERT_SEVERITIES: tuple[str, ...] = ("CRITICAL", "HIGH", "WARNING", "INFO")

ALERT_CATEGORIES: tuple[str, ...] = (
    "TEMPERATURE",
    "PRESSURE",
    "VIBRATION",
    "FLOW_RATE",
    "STALE_TIMEOUT",
    "NODE_OFFLINE",
    "COMMUNICATION",
    "THRESHOLD",
    "SAFETY",
    "CUSTOM",
)

ALERT_CONDITIONS: tuple[str, ...] = (
    "GREATER_THAN",
    "LESS_THAN",
    "EQUALS",
    "NOT_EQUALS",
    "RANGE_OUTSIDE",
    "STALE_TIMEOUT",
    "CONTAINS",
)

CONSOLE_ROLES: tuple[str, ...] = ("admin", "engineer", "operator", "auditor", "viewer")


def _one_of(column: str, allowed: tuple[str, ...], *, nullable: bool = False) -> str:
    """A CHECK body restricting a column to a vocabulary."""
    values = ", ".join(f"'{value}'" for value in allowed)
    prefix = f"{column} IS NULL OR " if nullable else ""
    return f"{prefix}{column} IN ({values})"


class AlertRule(Base):
    """
    An ISA-18.2 alert rule as authored in the console.

    Config, not time-series: a handful of rows an engineer edits, which is why it
    is here rather than in a hypertable. It lives in Postgres rather than in the
    browser so that a rule is a property of the plant and not of whoever's laptop
    happened to define it.

    `id` is text and supplied by the caller: the console generates it, and keeping
    it means a rule can be exported and re-imported without changing identity.
    """

    __tablename__ = "alert_rules"
    __table_args__ = (
        CheckConstraint(_one_of("severity", ALERT_SEVERITIES), name="alert_rules_severity_check"),
        CheckConstraint(_one_of("category", ALERT_CATEGORIES), name="alert_rules_category_check"),
        CheckConstraint(_one_of("condition", ALERT_CONDITIONS), name="alert_rules_condition_check"),
        CheckConstraint(
            _one_of("escalation_role", CONSOLE_ROLES, nullable=True),
            name="alert_rules_escalation_role_check",
        ),
        CheckConstraint("delay_seconds >= 0", name="alert_rules_delay_seconds_check"),
        CheckConstraint(
            "escalation_timeout_minutes IS NULL OR escalation_timeout_minutes >= 1",
            name="alert_rules_escalation_timeout_minutes_check",
        ),
        CheckConstraint("trigger_count >= 0", name="alert_rules_trigger_count_check"),
        Index("idx_alert_rules_enabled", "enabled"),
        Index("idx_alert_rules_topic", "topic"),
        Index("idx_alert_rules_severity", "severity"),
        {"schema": CONSOLE_SCHEMA},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)

    topic: Mapped[str] = mapped_column(Text, nullable=False)
    """The topic the rule watches. May be an MQTT pattern; not resolved to an Asset here."""

    metric_field: Mapped[str] = mapped_column(Text, nullable=False)
    condition: Mapped[str] = mapped_column(Text, nullable=False)

    threshold_value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    """A JSON scalar: the console compares numbers, strings and booleans alike."""

    threshold_upper_value: Mapped[float | None] = mapped_column(Double, nullable=True)
    unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    """As typed by the engineer. Not a Metric Definition's unit_of_measure (see CONTEXT.md)."""

    delay_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    escalation_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalation_timeout_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    auto_resolve_on_normal: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    in_app_notification: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    audio_chime: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    mqtt_publish_on_trigger: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    mqtt_alarm_topic: Mapped[str | None] = mapped_column(Text, nullable=True)
    email_webhook: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    webhook_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    trigger_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    notify_roles: Mapped[list[AlertRuleRole]] = relationship(
        back_populates="rule",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    @property
    def roles(self) -> list[str]:
        """The roles notified when this rule fires, as plain strings."""
        return sorted(link.role for link in self.notify_roles)

    def __repr__(self) -> str:
        return f"AlertRule(id={self.id!r}, topic={self.topic!r}, severity={self.severity!r})"


class AlertRuleRole(Base):
    """A role that is notified when an Alert Rule fires."""

    __tablename__ = "alert_rule_roles"
    __table_args__ = (
        CheckConstraint(_one_of("role", CONSOLE_ROLES), name="alert_rule_roles_role_check"),
        Index("idx_alert_rule_roles_role", "role"),
        {"schema": CONSOLE_SCHEMA},
    )

    rule_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{CONSOLE_SCHEMA}.alert_rules.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(Text, primary_key=True)

    rule: Mapped[AlertRule] = relationship(back_populates="notify_roles")

    def __repr__(self) -> str:
        return f"AlertRuleRole(rule_id={self.rule_id!r}, role={self.role!r})"


# The vocabularies the Connectivity catalog uses. Declared once here so the
# CHECK constraints, the migration and the GraphQL enums cannot drift apart.
CONNECTIVITY_PROTOCOLS: tuple[str, ...] = ("opc_ua",)

CONNECTIVITY_STATUSES: tuple[str, ...] = ("untested", "connected", "failed")

CONNECTIVITY_AUTH_MODES: tuple[str, ...] = ("anonymous", "username", "x509")

CONNECTIVITY_SECURITY_POLICIES: tuple[str, ...] = (
    "None",
    "Basic256Sha256",
    "Aes128Sha256RsaOaep",
    "Aes256Sha256RsaPss",
)

CONNECTIVITY_SECURITY_MODES: tuple[str, ...] = ("None", "Sign", "SignAndEncrypt")


class ConnectivityServer(Base):
    """
    An OPC-UA server the console dials.

    Config, not time-series: a handful of rows an engineer edits, which is why
    it lives in the `console` schema next to Alert Rules. The OPC-UA bridge
    (10_uns_opcua) reads this catalog to know which servers to connect to and
    which tags to republish over MQTT.

    `id` is text and supplied by the caller: the console generates it, so a
    server can be exported and re-imported without changing identity.
    """

    __tablename__ = "connectivity_servers"
    __table_args__ = (
        CheckConstraint(
            _one_of("protocol", CONNECTIVITY_PROTOCOLS),
            name="connectivity_servers_protocol_check",
        ),
        CheckConstraint(
            _one_of("last_status", CONNECTIVITY_STATUSES),
            name="connectivity_servers_last_status_check",
        ),
        CheckConstraint(
            _one_of("auth_mode", CONNECTIVITY_AUTH_MODES),
            name="connectivity_servers_auth_mode_check",
        ),
        CheckConstraint(
            _one_of("security_policy", CONNECTIVITY_SECURITY_POLICIES),
            name="connectivity_servers_security_policy_check",
        ),
        CheckConstraint(
            _one_of("security_mode", CONNECTIVITY_SECURITY_MODES),
            name="connectivity_servers_security_mode_check",
        ),
        Index("idx_connectivity_servers_protocol", "protocol"),
        {"schema": CONSOLE_SCHEMA},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    protocol: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    auth_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'anonymous'"))
    security_policy: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'None'"))
    security_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'None'"))
    username: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    password: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    certificate: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    private_key: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    server_certificate: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))

    last_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'untested'")
    )
    """untested | connected | failed. Updated by `ConnectivityRepository.record_test`."""

    last_error: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    tags: Mapped[list[ConnectivityTag]] = relationship(
        back_populates="server",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"ConnectivityServer(id={self.id!r}, endpoint={self.endpoint!r})"


class ConnectivityTag(Base):
    """
    An OPC-UA node the console subscribes to.

    `subscribed` is set by the engineer (or by `replace_subscribed_tags` during
    discovery) and is left untouched when a later discovery does not list the
    node: an engineer unsubscribes deliberately via `unsubscribe_tag`, never by
    omission. `mqtt_topic` is engineer-edited and must survive a re-discovery.
    """

    __tablename__ = "connectivity_tags"
    __table_args__ = (
        Index("idx_connectivity_tags_server", "server_id"),
        Index(
            "idx_connectivity_tags_subscribed",
            "server_id",
            "subscribed",
            postgresql_where=text("subscribed"),
        ),
        {"schema": CONSOLE_SCHEMA},
    )

    server_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey(f"{CONSOLE_SCHEMA}.connectivity_servers.id", ondelete="CASCADE"),
        primary_key=True,
    )
    node_id: Mapped[str] = mapped_column(Text, primary_key=True)

    browse_path: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    display_name: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    mqtt_topic: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    subscribed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    server: Mapped[ConnectivityServer] = relationship(back_populates="tags")

    def __repr__(self) -> str:
        return f"ConnectivityTag(server_id={self.server_id!r}, node_id={self.node_id!r}, subscribed={self.subscribed})"
