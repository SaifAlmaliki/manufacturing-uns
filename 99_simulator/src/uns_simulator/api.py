"""The simulator's control API (spec 5).

Served by uvicorn inside the simulation's own event loop, so every handler reads live
in-process state. There is no database, no cache and no snapshot thread: `simulator` *is*
the running plant.

This module translates and nothing else. Each handler is one call into the simulator plus
one exception mapped to a status code; all the behaviour lives in simulator.py, where it
can be tested without HTTP.

Deliberately not part of the GraphQL surface in 07_uns_graphql: GraphQL queries the
Unified Namespace, and this commands a process that happens to publish into it. See
docs/adr/0007-simulator-control-api-outside-graphql.md.
"""

import logging
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from uns_simulator.simulator import ReconfigurationError, UnifiedNamespaceSimulator

LOGGER = logging.getLogger(__name__)


def _unknown_device(device_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"unknown device {device_id!r}")


def _rejected(exc: ReconfigurationError) -> HTTPException:
    """A domain refusal, as a 422 naming the field to blame (spec 5.2).

    A dict rather than a string, so the console can highlight the offending control instead
    of showing a sentence in a toast.
    """
    return HTTPException(status_code=422, detail={"field": exc.field, "message": exc.message})


class _StrictModel(BaseModel):
    """Rejects keys it does not recognise.

    A silently-dropped `sedd: 42` is a control that appears to work and changes nothing,
    which is worse than an error.
    """

    model_config = ConfigDict(extra="forbid")


class RunRequest(_StrictModel):
    action: Literal["start", "stop", "pause", "resume"]


class ProfileRequest(_StrictModel):
    profile: str
    seed: int | None = None


class TiersRequest(_StrictModel):
    """Seconds between publishes, per cadence tier. Absent fields are left unchanged.

    Named fields rather than a free `dict[str, float]`, so an unknown tier and a negative
    interval are both pydantic 422s that name the offending key with no validation code
    of our own. All seven of plan A's tiers, including `event`.
    """

    fast: float | None = Field(default=None, ge=0.0)
    process: float | None = Field(default=None, ge=0.0)
    energy: float | None = Field(default=None, ge=0.0)
    status: float | None = Field(default=None, ge=0.0)
    meter: float | None = Field(default=None, ge=0.0)
    lab: float | None = Field(default=None, ge=0.0)
    event: float | None = Field(default=None, ge=0.0)


class FamiliesRequest(_StrictModel):
    """One field per sensor family in plan A's FAMILIES. Absent means unchanged."""

    energy: bool | None = None
    water: bool | None = None
    utilities: bool | None = None
    asset_health: bool | None = None
    production: bool | None = None
    safety: bool | None = None


class DeviceRequest(_StrictModel):
    enabled: bool


def create_app(simulator: UnifiedNamespaceSimulator, token: str | None = None) -> FastAPI:
    """Build the app around a live simulator.

    A factory rather than a module-level `app`, because the simulator has to exist first —
    and because the tests build several.
    """
    app = FastAPI(
        title="UNS simulator control API",
        description=(
            "Run control and observation for 99_simulator. Development and demonstration "
            "software: it generates synthetic plant data and is not for production use."
        ),
        docs_url="/simulator/docs",
        openapi_url="/simulator/openapi.json",
        redoc_url=None,
    )

    def require_token(x_simulator_token: Annotated[str | None, Header()] = None) -> None:
        """The optional shared secret from spec 10. No token configured means open."""
        if token is None or x_simulator_token == token:
            return
        raise HTTPException(status_code=401, detail="X-Simulator-Token is missing or wrong")

    # The prefix is what nginx and the Vite dev server proxy on, so it is part of the
    # contract rather than a tidy-looking default.
    router = APIRouter(prefix="/simulator", dependencies=[Depends(require_token)])

    @router.get("/health")
    async def get_health() -> dict[str, Any]:
        """Liveness. Answers while the plant is stopped."""
        return simulator.health_body()

    @router.get("/status")
    async def get_status() -> dict[str, Any]:
        """The document the console polls every two seconds."""
        return simulator.status()

    @router.get("/config")
    async def get_config() -> dict[str, Any]:
        """What is loaded, and what could be. Read-only."""
        return simulator.config_snapshot()

    @router.get("/plant")
    async def get_plant() -> dict[str, Any]:
        """The correlated plant state, per site and per line."""
        return simulator.plant_snapshot()

    @router.get("/devices")
    async def get_devices() -> dict[str, Any]:
        return {"devices": simulator.device_snapshots()}

    @router.get("/devices/{device_id}/signals")
    async def get_device_signals(device_id: str) -> dict[str, Any]:
        try:
            return simulator.signal_snapshot(device_id)
        except KeyError:
            raise _unknown_device(device_id) from None

    @router.get("/diagnostics")
    async def get_diagnostics() -> dict[str, Any]:
        """The load report, whatever is failing, and topics to paste into an MQTT client."""
        return simulator.diagnostics()

    @router.post("/run")
    async def post_run(request: RunRequest) -> dict[str, Any]:
        """Start, stop, pause or resume. Idempotent: a double-clicked button is not an error."""
        async with simulator.lock:
            if request.action == "start":
                await simulator.start()
            elif request.action == "stop":
                await simulator.stop()
            elif request.action == "pause":
                await simulator.pause()
            else:
                await simulator.resume()
        return simulator.status()

    @router.put("/profile")
    async def put_profile(request: ProfileRequest) -> dict[str, Any]:
        """Switch profile, optionally reseeding. Runtime only — nothing is written to YAML."""
        async with simulator.lock:
            try:
                await simulator.apply_profile(request.profile, seed=request.seed)
            except ReconfigurationError as exc:
                raise _rejected(exc) from exc
        body = simulator.status()
        # The devices that were counting are gone, so published_total and failed_total are
        # back to zero. Saying so stops a console computing a rate from a total that just
        # went backwards.
        body["counters_reset"] = True
        return body

    @router.put("/tiers")
    async def put_tiers(request: TiersRequest) -> dict[str, Any]:
        """Override publish intervals. `exclude_none` is what makes the body a patch."""
        async with simulator.lock:
            try:
                await simulator.apply_tiers(request.model_dump(exclude_none=True))
            except ReconfigurationError as exc:
                raise _rejected(exc) from exc
        return simulator.status()

    @router.put("/families")
    async def put_families(request: FamiliesRequest) -> dict[str, Any]:
        """Enable or disable the devices a sensor family contributed."""
        async with simulator.lock:
            try:
                await simulator.apply_families(request.model_dump(exclude_none=True))
            except ReconfigurationError as exc:
                raise _rejected(exc) from exc
        return simulator.status()

    @router.put("/devices/{device_id}")
    async def put_device(device_id: str, request: DeviceRequest) -> dict[str, Any]:
        """Silence or unsilence one device."""
        async with simulator.lock:
            try:
                await simulator.set_device_enabled(device_id, request.enabled)
            except KeyError:
                raise _unknown_device(device_id) from None
        return simulator.status()

    app.include_router(router)
    return app
