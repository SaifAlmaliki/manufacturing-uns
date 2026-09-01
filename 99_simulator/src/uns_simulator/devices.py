"""
Industrial device implementations: PLC, SCADA, and HMI.
All devices communicate via MQTT using ISA-95 topic structure.
"""

import asyncio
import contextlib
import json
import logging
import random
import uuid
from datetime import datetime
from typing import Any

import aiomqtt

from uns_simulator.config import MQTTConfig
from uns_simulator.models import Equipment, ISA95Hierarchy, ParameterType
from uns_simulator.plant import DeviceView
from uns_simulator.profiles import DeviceSpec
from uns_simulator.signals import build_signal

LOGGER = logging.getLogger(__name__)


class AsyncMQTTDevice:
    """
    Base class for async MQTT devices.

    Provides common functionality for connection management, message publishing,
    and error handling for industrial devices.
    """

    def __init__(self, device_id: str, hierarchy: ISA95Hierarchy, mqtt_config: dict[str, Any]):
        self.device_id = device_id
        self.hierarchy = hierarchy
        self.mqtt_config = mqtt_config

        # uuid4, not time.time(): devices are constructed in a tight loop and a timestamp
        # collides. A duplicate client id makes the broker evict the earlier connection.
        self.client_id = f"uns_simulator-{device_id}-{uuid.uuid4().hex[:8]}"

        self.connected = False
        self.publish_ok = 0
        self.publish_fail = 0
        self.reconnects = 0
        self.last_error: str | None = None
        self.last_publish_ts: float | None = None
        self._stack: contextlib.AsyncExitStack | None = None
        self._running = False

        self.client = aiomqtt.Client(
            identifier=self.client_id,
            clean_session=MQTTConfig.clean_session,
            protocol=MQTTConfig.version,
            transport=MQTTConfig.transport,
            hostname=MQTTConfig.host,
            port=MQTTConfig.port,
            username=MQTTConfig.username,
            password=MQTTConfig.password,
            keepalive=MQTTConfig.keep_alive,
            tls_params=MQTTConfig.tls_params,
            tls_insecure=MQTTConfig.tls_insecure,
        )

        LOGGER.info("Initialized device: %s (client id %s)", device_id, self.client_id)

    async def connect(self) -> bool:
        """Open one long-lived broker connection, retrying with exponential backoff.

        Backoff doubles from 1 s and is capped at MQTTConfig.retry_interval, so a broker
        that is down at startup does not turn into a hot loop and does not give up either.
        """
        if self.connected:
            return True
        cap = float(getattr(MQTTConfig, "retry_interval", 10) or 10)
        delay = 1.0
        while True:
            self._stack = contextlib.AsyncExitStack()
            try:
                await self._stack.enter_async_context(self.client)
            except Exception as exc:
                self.reconnects += 1
                self.last_error = str(exc)
                await self._stack.aclose()
                self._stack = None
                LOGGER.warning("Device %s could not connect (%s); retrying in %.1fs", self.device_id, exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2.0, cap)
                continue
            self.connected = True
            LOGGER.info("Device %s connected to the broker", self.device_id)
            return True

    async def disconnect(self) -> None:
        """Close the connection. Safe to call when already disconnected."""
        self.connected = False
        if self._stack is None:
            return
        stack, self._stack = self._stack, None
        try:
            await stack.aclose()
        except Exception as exc:
            LOGGER.debug("Device %s disconnect raised %s", self.device_id, exc)

    def health(self) -> dict[str, Any]:
        """Connection and publish counters. Published as device health by sub-project B."""
        return {
            "device_id": self.device_id,
            "client_id": self.client_id,
            "connected": self.connected,
            "publish_ok": self.publish_ok,
            "publish_fail": self.publish_fail,
            "reconnects": self.reconnects,
            "last_error": self.last_error,
            "last_publish_ts": self.last_publish_ts,
        }

    async def publish_parameter(
        self, equipment: str, param_type: ParameterType, param_name: str, data: dict[str, Any]
    ) -> bool:
        """
        Publish parameter data to MQTT using ISA-95 topic structure.

        Args:
            equipment: Equipment identifier
            param_type: Parameter type
            param_name: Parameter name
            data: Parameter data dictionary

        Returns:
            True if publish successful, False otherwise
        """

        try:
            # Enrich data with metadata
            enriched_data = {
                **data,
                "timestamp": datetime.now().timestamp() * 1000,
                "source": self.device_id,
                "equipment": equipment,
            }

            # Validate data structure
            if not self._validate_publish_data(enriched_data):
                return False

            topic = self.hierarchy.get_parameter_topic(equipment, param_type, param_name)

            if not self.connected:
                await self.connect()

            await self.client.publish(topic, json.dumps(enriched_data))
            self.publish_ok += 1
            self.last_publish_ts = datetime.now().timestamp()
            LOGGER.debug("Device %s published to %s: %s", self.device_id, topic, enriched_data.get("value", "N/A"))
            return True

        except json.JSONDecodeError as e:
            LOGGER.error("JSON encoding error in device %s: %s", self.device_id, e)
            return False
        except Exception as e:
            self.publish_fail += 1
            self.last_error = str(e)
            self.connected = False
            await self.disconnect()
            LOGGER.error("Publish error in device %s: %s", self.device_id, e)
            return False

    def _validate_publish_data(self, data: dict[str, Any]) -> bool:
        """
        Validate data before publishing.

        Args:
            data: Data dictionary to validate

        Returns:
            True if data is valid
        """
        required_fields = ["timestamp", "source", "equipment"]
        for field in required_fields:
            if field not in data:
                LOGGER.error("Missing required field %s in publish data from %s", field, self.device_id)
                return False
        return True

    async def handle_message(self, topic: str, payload: dict[str, Any]) -> None:
        """
        Handle incoming MQTT messages.

        Args:
            topic: MQTT topic
            payload: Message payload
        """
        LOGGER.debug("Device %s received message on %s: %s", self.device_id, topic, payload)

    async def start(self, interval: float = 5.0) -> None:
        """Start device operation - to be implemented by subclasses."""
        raise NotImplementedError("Subclasses must implement start method")

    async def stop(self) -> None:
        """Stop device operation and release the broker connection."""
        self._running = False
        await self.disconnect()
        LOGGER.info("Device %s stopped", self.device_id)


class PLC(AsyncMQTTDevice):
    """
    Programmable Logic Controller device.

    Simulates industrial PLCs that generate sensor data, equipment status,
    and alarm conditions.
    """

    def __init__(self, plc_id: str, hierarchy: ISA95Hierarchy, mqtt_config: dict[str, Any], equipment_config: dict[str, Any]):
        super().__init__(f"PLC_{plc_id}", hierarchy, mqtt_config)
        self.plc_id = plc_id

        # Create equipment definition
        self.equipment = Equipment(name=equipment_config["name"], sensors=equipment_config["sensors"])

        # Equipment state
        self.operational = True
        self.performance = 1.0
        self.operating_hours = random.randint(0, 5000)  # ruff: ignore[suspicious-non-cryptographic-random-usage]
        self.last_maintenance = datetime.timestamp(datetime.now())

        LOGGER.info("Initialized PLC %s for equipment %s", plc_id, self.equipment.name)

    async def generate_sensor_data(self) -> list[dict[str, Any]]:
        """
        Generate realistic sensor data with random variation.

        Returns:
            List of sensor data messages
        """
        messages = []

        for sensor_name, sensor_config in self.equipment.sensors.items():
            try:
                base_value = sensor_config["base_value"]
                variation = sensor_config["variation"]

                # Generate value with realistic variation

                current_value = base_value + random.uniform(  # ruff: ignore[suspicious-non-cryptographic-random-usage]
                    -variation,
                    variation,
                )
                # Determine status based on deviation
                deviation = abs(current_value - base_value)
                if deviation > variation * 3:
                    status = "Alarm"
                elif deviation > variation * 2:
                    status = "Warning"
                else:
                    status = "Normal"

                sensor_data = {
                    "value": round(current_value, 2),
                    "unit": sensor_config["unit"],
                    "status": status,
                    "quality": "Good",
                }

                messages.append(
                    {
                        "equipment": self.equipment.name,
                        "param_type": ParameterType.PROCESS_VALUE,
                        "param_name": sensor_name,
                        "data": sensor_data,
                    }
                )

            except KeyError as e:
                LOGGER.error("Missing sensor configuration key %s in PLC %s", e, self.plc_id)

        LOGGER.debug("PLC %s generated %d sensor data points", self.plc_id, len(messages))
        return messages

    async def generate_status_data(self) -> dict[str, Any]:
        """
        Generate equipment status information.

        Returns:
            Status data dictionary
        """
        # Simulate occasional equipment state changes
        if random.random() < 0.02:  # ruff: ignore[suspicious-non-cryptographic-random-usage] # 2% chance of fault
            self.operational = False
            self.performance = round(random.uniform(0.5, 0.8), 2)  # ruff: ignore[suspicious-non-cryptographic-random-usage]
            LOGGER.warning("PLC %s equipment fault simulated", self.plc_id)
        elif random.random() < 0.05 and not self.operational:  # ruff: ignore[suspicious-non-cryptographic-random-usage] # 5% chance of recovery
            self.operational = True
            self.performance = round(random.uniform(0.9, 1.0), 2)  # ruff: ignore[suspicious-non-cryptographic-random-usage]
            LOGGER.info("PLC %s equipment recovery simulated", self.plc_id)

        status_data = {
            "operational": self.operational,
            "performance": self.performance,
            "mode": "Auto" if self.operational else "Maintenance",
            "operating_hours": self.operating_hours,
            "last_maintenance": self.last_maintenance,
        }

        return {
            "equipment": self.equipment.name,
            "param_type": ParameterType.STATUS,
            "param_name": "EquipmentStatus",
            "data": status_data,
        }

    async def generate_alarm_data(self) -> dict[str, Any] | None:
        """
        Generate alarm data with random occurrence.

        Returns:
            Alarm data dictionary or None if no alarms
        """

        if random.random() < 0.05:  # ruff: ignore[suspicious-non-cryptographic-random-usage] # 5% chance of alarm
            alarm_types = [
                ("HIGH_TEMPERATURE", "High temperature detected", "HIGH"),
                ("LOW_PRESSURE", "Low pressure warning", "MEDIUM"),
                ("EQUIPMENT_FAULT", "Equipment fault detected", "HIGH"),
                ("COMMUNICATION_LOSS", "Communication loss with sensor", "MEDIUM"),
            ]

            alarm_type, message, severity = random.choice(alarm_types)  # ruff: ignore[suspicious-non-cryptographic-random-usage]

            alarm_data = {
                "alarms": [
                    {
                        "id": f"ALM_{random.randint(1000, 9999)}",  # ruff: ignore[suspicious-non-cryptographic-random-usage]
                        "type": alarm_type,
                        "message": message,
                        "severity": severity,
                        "timestamp": datetime.now().timestamp() * 1000,
                        "acknowledged": False,
                    }
                ]
            }

            LOGGER.warning("PLC %s generated alarm: %s", self.plc_id, alarm_type)

            return {
                "equipment": self.equipment.name,
                "param_type": ParameterType.ALARM,
                "param_name": "ActiveAlarms",
                "data": alarm_data,
            }

        return None

    async def start(self, interval: float = 5.0) -> None:
        """
        Start PLC data generation.

        Args:
            interval: Data generation interval in seconds
        """
        self._running = True
        LOGGER.info("PLC %s started for equipment %s (interval: %ss)", self.plc_id, self.equipment.name, interval)

        try:
            while self._running:
                # Generate and publish sensor data
                sensor_messages = await self.generate_sensor_data()
                for msg in sensor_messages:
                    success = await self.publish_parameter(msg["equipment"], msg["param_type"], msg["param_name"], msg["data"])
                    if not success:
                        LOGGER.warning("PLC %s failed to publish sensor data", self.plc_id)

                # Generate and publish status data
                status_msg = await self.generate_status_data()
                await self.publish_parameter(
                    status_msg["equipment"], status_msg["param_type"], status_msg["param_name"], status_msg["data"]
                )

                # Generate and publish alarms if any
                alarm_msg = await self.generate_alarm_data()
                if alarm_msg:
                    await self.publish_parameter(
                        alarm_msg["equipment"], alarm_msg["param_type"], alarm_msg["param_name"], alarm_msg["data"]
                    )

                    # Increment operating hours
                self.operating_hours += 1

                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            LOGGER.info("PLC %s operation cancelled", self.plc_id)
        except Exception as e:
            LOGGER.error("PLC %s encountered error: %s", self.plc_id, e, exc_info=True)
        finally:
            await self.stop()


class SCADA(AsyncMQTTDevice):
    """
    Supervisory Control and Data Acquisition system.

    Monitors multiple field devices and provides system-wide overview
    and performance metrics.
    """

    def __init__(self, hierarchy: ISA95Hierarchy, mqtt_config: dict[str, Any], system_name: str = "SCADA_Main"):
        super().__init__("SCADA_System", hierarchy, mqtt_config)
        self.system_name = system_name
        self.connected_devices = 0
        self.data_points_received = 0
        self.start_time = datetime.now()

        LOGGER.info("Initialized SCADA system: %s", system_name)

    async def generate_system_status(self) -> dict[str, Any]:
        """
        Generate SCADA system health and performance data.

        Returns:
            System status dictionary
        """
        uptime = (datetime.now() - self.start_time).total_seconds()

        status_data = {
            "system_name": self.system_name,
            "system_status": "Operational",
            "connected_devices": self.connected_devices,
            "data_points_per_second": random.randint(500, 1500),  # ruff: ignore[suspicious-non-cryptographic-random-usage]
            "system_uptime_hours": round(uptime / 3600, 2),
            "cpu_usage_percent": round(random.uniform(10, 60), 1),  # ruff: ignore[suspicious-non-cryptographic-random-usage]
            "memory_usage_percent": round(random.uniform(20, 80), 1),  # ruff: ignore[suspicious-non-cryptographic-random-usage]
            "alarms_active": random.randint(0, 3),  # ruff: ignore[suspicious-non-cryptographic-random-usage]
            "version": "2.1.4",
        }

        return status_data

    async def start(self, interval: float = 10.0) -> None:
        """
        Start SCADA system monitoring.

        Args:
            interval: Status update interval in seconds
        """
        self._running = True
        LOGGER.info("SCADA system %s started (update interval: %ss)", self.system_name, interval)

        try:
            while self._running:
                status_data = await self.generate_system_status()
                success = await self.publish_parameter("SCADA", ParameterType.STATUS, "SystemStatus", status_data)

                if success:
                    LOGGER.debug("SCADA system published status update")
                else:
                    LOGGER.warning("SCADA system failed to publish status update")

                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            LOGGER.info("SCADA system operation cancelled")
        except Exception as e:
            LOGGER.error("SCADA system encountered error: %s", e, exc_info=True)
        finally:
            await self.stop()


class HMI(AsyncMQTTDevice):
    """
    Human Machine Interface device.

    Simulates operator workstations and user interactions with the
    industrial control system.
    """

    def __init__(self, hmi_id: str, hierarchy: ISA95Hierarchy, mqtt_config: dict[str, Any]):
        super().__init__(f"HMI_{hmi_id}", hierarchy, mqtt_config)
        self.hmi_id = hmi_id
        self.current_screen = "MainDashboard"
        self.operator = f"operator{random.randint(1, 5)}"  # ruff: ignore[suspicious-non-cryptographic-random-usage]
        self.interaction_count = 0
        self.session_start = datetime.now()

        LOGGER.info("Initialized HMI %s for operator %s", hmi_id, self.operator)

    async def generate_operator_actions(self) -> dict[str, Any]:
        """
        Generate simulated operator interactions.

        Returns:
            Operator actions data dictionary
        """
        actions = []

        # 30% chance of operator action each cycle
        if random.random() < 0.3:  # ruff: ignore[suspicious-non-cryptographic-random-usage]
            action_types = [
                ("SETPOINT_CHANGE", "Changed temperature setpoint"),
                ("ALARM_ACKNOWLEDGE", "Acknowledged alarm"),
                ("MODE_CHANGE", "Changed operating mode"),
                ("RECIPE_LOAD", "Loaded production recipe"),
                ("MANUAL_OVERRIDE", "Manual override activated"),
                ("TREND_VIEW", "Viewed trend data"),
            ]

            action_type, description = random.choice(action_types)  # ruff: ignore[suspicious-non-cryptographic-random-usage]

            # Simulate screen navigation with action
            screens = ["MainDashboard", "AlarmSummary", "TrendDisplay", "ControlPanel", "RecipeManagement"]
            self.current_screen = random.choice(screens)  # ruff: ignore[suspicious-non-cryptographic-random-usage]

            action_data = {
                "type": action_type,
                "description": description,
                "operator": self.operator,
                "screen": self.current_screen,
                "timestamp": datetime.now().timestamp() * 1000,
                "session_duration_minutes": round((datetime.now() - self.session_start).total_seconds() / 60, 1),
            }

            # Add context-specific data
            if action_type == "SETPOINT_CHANGE":
                action_data["parameter"] = f"Temp_Setpoint_{random.randint(1, 5)}"  # ruff: ignore[suspicious-non-cryptographic-random-usage]
                action_data["new_value"] = round(random.uniform(60, 90), 2)  # ruff: ignore[suspicious-non-cryptographic-random-usage]
                action_data["old_value"] = round(action_data["new_value"] - random.uniform(1, 5), 2)  # ruff: ignore[suspicious-non-cryptographic-random-usage]

            actions.append(action_data)
            self.interaction_count += 1

            LOGGER.debug("HMI %s generated operator action: %s", self.hmi_id, action_type)

        return {
            "actions": actions,
            "current_screen": self.current_screen,
            "operator": self.operator,
            "total_interactions": self.interaction_count,
            "workstation_id": self.device_id,
        }

    async def start(self, interval: float = 3.0) -> None:
        """
        Start HMI operation simulation.

        Args:
            interval: Action generation interval in seconds
        """
        self._running = True
        LOGGER.info("HMI %s started for operator %s (interval: %ss)", self.hmi_id, self.operator, interval)

        try:
            while self._running:
                action_data = await self.generate_operator_actions()

                # Only publish if there are actions
                if action_data["actions"]:
                    success = await self.publish_parameter("HMI", ParameterType.EVENT, "OperatorActions", action_data)

                    if success:
                        LOGGER.debug("HMI %s published operator actions", self.hmi_id)
                    else:
                        LOGGER.warning("HMI %s failed to publish operator actions", self.hmi_id)

                await asyncio.sleep(interval)

        except asyncio.CancelledError:
            LOGGER.info("HMI %s operation cancelled", self.hmi_id)
        except Exception as e:
            LOGGER.error("HMI %s encountered error: %s", self.hmi_id, e, exc_info=True)
        finally:
            await self.stop()


class SignalDevice(AsyncMQTTDevice):
    """A device whose behaviour is entirely declared by its DeviceSpec.

    Two responsibilities, deliberately kept apart:
      evaluate(dt)      - advance the signals. Called once per plant tick.
      publish_tier(t)   - send the current values for one cadence tier.

    Splitting them is what makes a 900 s meter reading and a 1 s vibration sample describe
    the same instant of the same world. The old PLC computed a value at publish time, so a
    slow publisher necessarily saw a coarser simulation.
    """

    def __init__(
        self,
        spec: DeviceSpec,
        mqtt_config: dict[str, Any],
        view: DeviceView,
        global_seed: int,
    ) -> None:
        super().__init__(spec.id, spec.path, mqtt_config)
        self.spec = spec
        self.view = view
        self.enabled = spec.enabled
        self.values: dict[str, Any] = {}
        self._last_published: dict[str, Any] = {}

        self._param_types: dict[str, ParameterType] = {}
        for signal_spec in spec.signals:
            try:
                self._param_types[signal_spec.name] = ParameterType(signal_spec.param_type)
            except ValueError:
                allowed = ", ".join(member.value for member in ParameterType)
                raise ValueError(
                    f"device {spec.id!r} signal {signal_spec.name!r}: unknown param_type "
                    f"{signal_spec.param_type!r} (allowed: {allowed})"
                ) from None

        # spec.signals is already in dependency order (profiles.expand_template sorted it),
        # so evaluating in sequence guarantees a derived signal sees this tick's siblings.
        self.signals = [
            build_signal(signal_spec, f"{spec.topic_prefix}/{signal_spec.name}", global_seed) for signal_spec in spec.signals
        ]
        self.tiers = frozenset(signal_spec.tier for signal_spec in spec.signals)

    def evaluate(self, dt: float) -> dict[str, Any]:
        """Advance every signal by `dt` seconds. Synchronous, and never publishes."""
        for signal in self.signals:
            self.values[signal.spec.name] = signal.next(dt, self.view, self.values)
        return self.values

    async def publish_tier(self, tier: str) -> int:
        """Publish the current value of every signal in `tier`. Returns the success count."""
        if not self.enabled:
            return 0
        published = 0
        for signal in self.signals:
            if signal.spec.tier != tier:
                continue
            value = self.values.get(signal.spec.name)
            if value is None:
                continue
            # The 'event' tier means "on change" - a door that stays shut says so once.
            if tier == "event" and self._last_published.get(signal.spec.name, object()) == value:
                continue
            payload = {
                "value": value,
                "unit": signal.spec.unit,
                "status": signal.status(),
                "quality": "Good",
            }
            if signal.spec.limits:
                payload["limits"] = signal.spec.limits
            if await self.publish_parameter(
                self.spec.equipment, self._param_types[signal.spec.name], signal.spec.name, payload
            ):
                self._last_published[signal.spec.name] = value
                published += 1
        return published

    async def run_tier(self, tier: str, interval: float) -> None:
        """Publish `tier` every `interval` seconds until stopped or cancelled."""
        self._running = True
        LOGGER.info("Device %s publishing tier %s every %.1fs", self.device_id, tier, interval)
        try:
            while self._running:
                await self.publish_tier(tier)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            LOGGER.info("Device %s tier %s cancelled", self.device_id, tier)
            raise

    def snapshot(self) -> list[dict[str, Any]]:
        """Describe every signal. Rendered by sub-project B's SignalInspector."""
        return [
            {
                "name": signal.spec.name,
                "shape": signal.spec.shape,
                "unit": signal.spec.unit,
                "precision": signal.spec.precision,
                "range": list(signal.spec.value_range) if signal.spec.value_range else None,
                "limits": dict(signal.spec.limits),
                "params": dict(signal.spec.params),
                "tier": signal.spec.tier,
                "param_type": signal.spec.param_type,
                "value": self.values.get(signal.spec.name),
                "status": signal.status(),
            }
            for signal in self.signals
        ]
