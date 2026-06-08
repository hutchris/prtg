"""
Python module to manage PRTG servers via the HTTP API.

Provides object-oriented access to the PRTG sensor tree: probes, groups,
devices, sensors and channels. Each object exposes methods to query and
mutate its corresponding PRTG resource (rename, pause, clone, set
properties, delete, etc.).

Typical use:

    from prtg import PrtgApi

    prtg = PrtgApi(
        host="prtg.example.com",
        user="prtgadmin",
        passhash="0000000",
        rootid=0,
    )

    for probe in prtg.probes:
        print(probe)
"""

from __future__ import annotations

import csv
import json
import logging
import urllib3
from datetime import datetime
from typing import Any, Iterable, NamedTuple

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PrtgError(Exception):
    """Base class for all PRTG-related errors."""


class AuthenticationError(PrtgError):
    """Authentication with the PRTG server failed."""


class ResourceNotFound(PrtgError):
    """The requested PRTG resource was not found."""


class MalformedRequest(PrtgError):
    """PRTG rejected the request as malformed."""


# ---------------------------------------------------------------------------
# Connection config
# ---------------------------------------------------------------------------


class ConfData(NamedTuple):
    """Connection configuration passed between objects."""

    host: str
    port: str
    user: str | None
    passhash: str | None
    protocol: str
    apikey: str | None
    verify_ssl: bool
    timeout: float


class ConnectionMethods:
    """Mixin providing URL building and HTTP request handling."""

    confdata: ConfData

    def unpack_config(self, confdata: ConfData) -> None:
        self.confdata = confdata
        self.host = confdata.host
        self.port = confdata.port
        self.user = confdata.user
        self.passhash = confdata.passhash
        self.protocol = confdata.protocol
        self.apikey = confdata.apikey
        self.verify_ssl = confdata.verify_ssl
        self.timeout = confdata.timeout

        self.base_url = f"{self.protocol}://{self.host}:{self.port}/api/"
        self.base_url_no_api = f"{self.protocol}://{self.host}:{self.port}/"

        if self.user is None and self.passhash is None and self.apikey is None:
            raise AuthenticationError(
                "Please supply username & passhash or api key"
            )
        if self.apikey is None and (self.user is None or self.passhash is None):
            raise AuthenticationError(
                "Please supply both username & passhash"
            )

        if not self.verify_ssl:
            # Suppress the InsecureRequestWarning per-process when the user
            # has opted in to skipping cert verification.
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    def _auth_params(self) -> dict[str, str]:
        if self.apikey is not None:
            return {"apitoken": self.apikey}
        return {"username": self.user, "passhash": self.passhash}

    def get_request(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        api: bool = True,
        check_login_page: bool = True,
    ) -> requests.Response:
        """Issue a GET against the PRTG server.

        ``path`` is the endpoint relative to ``/api/`` (or to root when
        ``api=False``). ``params`` is the query string as a dict — values
        are URL-encoded automatically by requests, so callers don't need
        to worry about special characters.

        ``check_login_page`` controls whether a 200 response landing on
        ``/public/login.htm`` is treated as an auth failure. Set to False
        for endpoints (like ``duplicateobject.htm``) whose success response
        legitimately lands on a login page with the result embedded in the URL.
        """
        base = self.base_url if api else self.base_url_no_api
        url = f"{base}{path}"
        all_params = {**(params or {}), **self._auth_params()}

        try:
            req = requests.get(
                url,
                params=all_params,
                verify=self.verify_ssl,
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise PrtgError(
                f"Request to {path} timed out after {self.timeout}s"
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise PrtgError(f"Connection to PRTG failed: {exc}") from exc

        if req.status_code in (200, 302):
            if check_login_page and self._looks_like_login_page(req):
                raise AuthenticationError(
                    "PRTG returned a login page — credentials likely invalid "
                    "or session expired"
                )
            return req
        if req.status_code == 401:
            raise AuthenticationError(
                "PRTG authentication failed. Check credentials in config file"
            )
        if req.status_code == 404:
            raise ResourceNotFound(f"No resource at URL used: {path}")
        if req.status_code == 400:
            raise MalformedRequest(f"Request was rejected by prtg. {path}")
        raise PrtgError(
            f"Unexpected response status {req.status_code}: {req.text}"
        )

    @staticmethod
    def _looks_like_login_page(req: requests.Response) -> bool:
        """Detect PRTG's 200-with-login-page-body auth failure response."""
        return "/public/login.htm" in req.url


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------


class GlobalArrays:
    """Holds flat lists of every object discovered in the sensor tree.

    NOTE: these are class-level attributes so that all objects spawned
    from a single ``PrtgApi`` instance share the same registry. If you
    instantiate ``PrtgApi`` against more than one PRTG server in the
    same process, the lists will be shared between them; clearing one
    clears all. Call ``clear_arrays()`` on a fresh instance to reset.
    """

    allprobes: list = []
    allgroups: list = []
    alldevices: list = []
    allsensors: list = []


# ---------------------------------------------------------------------------
# Base config (shared methods for all PRTG objects)
# ---------------------------------------------------------------------------


class BaseConfig(ConnectionMethods):
    """Shared behaviour for every PRTG object (probe/group/device/sensor)."""

    name: str = ""
    id: str = ""
    active: str = ""
    type: str = ""

    def __repr__(self) -> str:
        cls = type(self).__name__
        return (
            f"<{cls} name={self.name!r} id={self.id} active={self.active}>"
        )

    def clear_arrays(self) -> None:
        del GlobalArrays.allprobes[:]
        del GlobalArrays.allgroups[:]
        del GlobalArrays.alldevices[:]
        del GlobalArrays.allsensors[:]

    def delete(self, confirm: bool = True) -> None:
        """Delete this object from PRTG.

        If ``confirm`` is True the user is prompted at the terminal. Raises
        ``PrtgError`` if called on the root object.
        """
        if self.type == "Root":
            raise PrtgError("You cannot delete the root object.")

        if confirm:
            response = ""
            while response.upper() not in ("Y", "N"):
                response = input("Would you like to continue? (Y/[N]) ") or "N"
            if response.upper() != "Y":
                log.info("Delete aborted by user for id=%s", self.id)
                return

        self.get_request(
            "deleteobject.htm",
            params={"id": self.id, "approve": 1},
        )

    def set_property(self, name: str, value: Any) -> None:
        if self.type != "Channel":
            params = {"id": self.id, "name": name, "value": value}
        else:
            params = {
                "id": self.sensorid,
                "subtype": "channel",
                "subid": self.objid,
                "name": name,
                "value": value,
            }
        self.get_request("setobjectproperty.htm", params=params)
        setattr(self, name, value)

    def get_property(self, name: str) -> str:
        if self.type != "Channel":
            params = {"id": self.id, "name": name, "show": "text"}
        else:
            params = {
                "id": self.sensorid,
                "subtype": "channel",
                "subid": self.objid,
                "name": name,
            }
        req = self.get_request("getobjectproperty.htm", params=params)
        soup = BeautifulSoup(req.text, "xml")
        text = soup.result.text
        if text == "(Property not found)":
            raise ResourceNotFound(f"No object property of name: {name}")
        setattr(self, name, text)
        return text

    def set_interval(self, interval: int) -> None:
        """Set the scanning interval (seconds).

        Note: inheritance must still be disabled manually in the PRTG UI.
        Valid intervals: 30, 60, 300, 600, 900, 1800, 3600, 14400, 21600,
        43200, 86400.
        """
        self.set_property(name="interval", value=interval)

    def get_tree(self, root: str | int = "") -> BeautifulSoup:
        """Fetch the sensortree XML from PRTG starting at ``root``."""
        req = self.get_request(
            "table.xml",
            params={"content": "sensortree", "output": "xml", "id": root},
        )
        treesoup = BeautifulSoup(req.text, "xml")
        if not treesoup.sensortree.nodes.find(True):
            raise ResourceNotFound(f"No objects at ID: {root}")
        return treesoup

    def rename(self, newname: str) -> None:
        self.get_request(
            "rename.htm",
            params={"id": self.id, "value": newname},
        )
        self.name = newname

    def pause(self, duration: int = 0, message: str = "") -> None:
        if duration > 0:
            path = "pauseobjectfor.htm"
            params: dict[str, Any] = {"id": self.id, "duration": duration}
        else:
            path = "pause.htm"
            params = {"id": self.id, "action": 0}
        if message:
            params["pausemsg"] = message
        self.get_request(path, params=params)
        self.status = "Paused"
        self.active = "false"
        self.status_raw = "7"

    def resume(self) -> None:
        self.get_request(
            "pause.htm",
            params={"id": self.id, "action": 1},
        )
        # Status is indeterminate immediately after resume.
        self.status = "?"
        self.active = "true"
        self.status_raw = "?"

    def get_status(self, name: str = "status") -> str:
        req = self.get_request(
            "getobjectstatus.htm",
            params={"id": self.id, "name": name, "show": "text"},
        )
        soup = BeautifulSoup(req.text, "xml")
        status = soup.result.text.strip()
        self.status = status
        return status

    def clone(self, newname: str, newplaceid: str) -> str | None:
        """Duplicate this object and return the new object's id.

        PRTG's response shape for ``duplicateobject.htm`` has varied across
        versions. We've seen:

        1. A 302 redirect to ``/object.htm?id=<newid>`` — the modern,
           documented behaviour. ``req.history`` is populated.
        2. A 200 response with no redirect, but ``req.url`` containing
           ``/public/login.htm?loginurl=/object.htm?id=<newid>&errormsg=``
           (Paessler KB confirms this happens on some configurations).
        3. A 200 with only progress info and no usable id (older versions).

        This method handles 1 and 2 and returns ``None`` for 3 so callers
        can detect failure rather than crash.
        """
        req = self.get_request(
            "duplicateobject.htm",
            params={
                "id": self.id,
                "name": newname,
                "targetid": newplaceid,
            },
            check_login_page=False,
        )
        if req is None:
            return None
        return _extract_new_id(req)

    def add_tags(self, tags: list[str], clear_old: bool = False) -> None:
        if not isinstance(tags, list):
            raise TypeError("tags must be a list")
        old_tags = [] if clear_old else self.get_property("tags").split(" ")
        # Preserve order and dedup
        merged = list(dict.fromkeys(t for t in old_tags + tags if t))
        self.set_property(name="tags", value=" ".join(merged))

    def acknowledge(self, message: str = "") -> None:
        """Acknowledge an alarm on this object."""
        self.get_request(
            "acknowledgealarm.htm",
            params={"id": self.id, "ackmsg": message},
        )

    def save_graph(
        self,
        graphid: str,
        filepath: str,
        size: str,
        hidden_channels: str = "",
        filetype: str = "svg",
    ) -> None:
        """Download a graph image for this object. Size options: S, M, L."""
        width, height, font = _graph_dimensions(size)
        params: dict[str, Any] = {
            "type": "graph",
            "graphid": graphid,
            "id": self.id,
            "width": width,
            "height": height,
            "plotcolor": "#ffffff",
            "gridcolor": "#ffffff",
            "graphstyling": f"showLegend='1' baseFontSize='{font}'",
        }
        if hidden_channels:
            params["hide"] = hidden_channels

        try:
            req = requests.get(
                f"{self.base_url_no_api}chart.{filetype}",
                params={**params, **self._auth_params()},
                verify=self.verify_ssl,
                stream=True,
                timeout=self.timeout,
            )
        except requests.exceptions.Timeout as exc:
            raise PrtgError(
                f"save_graph timed out after {self.timeout}s"
            ) from exc

        req.raise_for_status()
        with open(filepath, "wb") as imgfile:
            for chunk in req.iter_content(chunk_size=8192):
                imgfile.write(chunk)
        self.filepath = filepath

    def get_details(self) -> None:
        """Fetch the JSON sensordata blob and store it on ``self.details``."""
        req = self.get_request(
            "getsensordetails.json",
            params={"id": self.id},
        )
        self.details = json.loads(req.text)["sensordata"]

    def get_historic_data(
        self,
        startdate: datetime | str,
        enddate: datetime | str,
        timeaverage: int,
    ) -> dict[str, list]:
        """Fetch historic data for this object between two timestamps.

        Date arguments may be ``datetime`` instances or pre-formatted
        ``YYYY-MM-DD-HH-MM-SS`` strings. ``timeaverage`` is the averaging
        interval in seconds (0 = raw).

        Returns a dict keyed by column header, with parallel lists of
        values. The ``Date Time`` column is parsed as US-format
        ``MM/DD/YYYY HH:MM:SS AM/PM``, matching PRTG's CSV default.
        Servers configured for other regional formats will require
        adjustment.

        Note: PRTG only returns meaningful historic data for sensors
        (and in some versions, channels). Calling this on a group/device
        will likely return an empty result or an error from PRTG.
        """
        if isinstance(startdate, datetime):
            startdate = _format_prtg_date(startdate)
        if isinstance(enddate, datetime):
            enddate = _format_prtg_date(enddate)

        req = self.get_request(
            "historicdata.csv",
            params={
                "id": self.id,
                "avg": timeaverage,
                "sdate": startdate,
                "edate": enddate,
            },
        )
        return _parse_historic_csv(req.text)


# ---------------------------------------------------------------------------
# Tree reconciliation helper
# ---------------------------------------------------------------------------


def _reconcile_children(
    candidates: Iterable,
    existing: list,
    factory,
    all_list: list | None = None,
    id_of_soup=lambda c: c.find("id").string,
) -> None:
    """Refresh ``existing`` against ``candidates`` BeautifulSoup nodes.

    For each candidate: refresh the matching object if present, otherwise
    create one via ``factory(childsoup)`` and append it to both ``existing``
    and ``all_list`` (when provided). Any object in ``existing`` whose id
    is no longer in ``candidates`` is removed from both lists.
    """
    existing_by_id = {obj.id: obj for obj in existing}
    seen: set[str] = set()

    for childsoup in candidates:
        cid = id_of_soup(childsoup)
        seen.add(cid)
        match = existing_by_id.get(cid)
        if match is not None:
            match.refresh(childsoup)
        else:
            new = factory(childsoup)
            existing.append(new)
            if all_list is not None and all_list is not existing:
                all_list.append(new)

    for obj in list(existing):
        if obj.id not in seen:
            existing.remove(obj)
            if all_list is not None and all_list is not existing and obj in all_list:
                all_list.remove(obj)


def _iter_named_children(parent_soup):
    """Yield direct children of a soup node that are real tags (not whitespace)."""
    for child in parent_soup.children:
        if child.name is not None:
            yield child


def _absorb_simple_children(obj, soup) -> None:
    """Copy text-only children of ``soup`` onto ``obj`` as attributes.

    Used by every object's parser: any direct child that isn't itself a
    nested PRTG object becomes a string attribute on the parent.
    """
    for child in _iter_named_children(soup):
        if child.string is None:
            child.string = ""
        setattr(obj, child.name, child.string)


def _extract_new_id(req: requests.Response) -> str | None:
    """Extract the new object id from a ``duplicateobject.htm`` response.

    PRTG's redirect chain after a successful clone varies considerably:

    * **Classic local-login setup**: ``duplicateobject.htm`` → 302 to
      ``object.htm?id=NNN`` (or ``sensor.htm?id=NNN``).
    * **SSO setup (e.g. Azure AD)**: longer chain that goes via
      ``sensor.htm?id=NNN`` → ``login.htm?loginurl=/sensor.htm?id=NNN``
      → IdP → callback → ``local_login.htm?loginurl=/sensor.htm?id=NNN``.

    The new id is **always** present somewhere in the chain (either as
    ``?id=NNN`` directly or embedded in a ``loginurl`` parameter), but
    we have to walk multiple URLs to find it reliably.

    Strategy: collect every URL touched during the redirect chain
    (history entries + final req.url) and check each for the new id.
    Prefer URLs that look like an object page (sensor/device/group/object)
    over login pages, because the login pages are auth-failure
    artifacts that don't always survive.
    """
    from urllib.parse import urlparse, parse_qs, unquote

    # Collect every URL from the chain. Order matters: we walk early URLs
    # (most likely the direct sensor.htm redirect from PRTG) before late
    # URLs (SSO callbacks that may not carry the id).
    urls = [h.url for h in req.history] + [req.url]

    # Filter to URLs that contain *some* id reference, then prefer object
    # URLs over login URLs.
    def _is_object_url(url: str) -> bool:
        path = urlparse(url).path
        return any(
            page in path
            for page in ("sensor.htm", "device.htm", "group.htm", "object.htm", "probe.htm")
        )

    ordered = [u for u in urls if _is_object_url(u)] + [
        u for u in urls if not _is_object_url(u)
    ]

    for url in ordered:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)

        # Strategy A: direct ?id=NNN. The request URL also contains
        # ?id=<source-id>, so we need to skip URLs that look like the
        # original duplicateobject request.
        if "duplicateobject" not in parsed.path:
            if "id" in qs and qs["id"][0].isdigit():
                return qs["id"][0]

        # Strategy B: loginurl=/object.htm?id=NNN&...
        if "loginurl" in qs:
            inner = urlparse(unquote(qs["loginurl"][0]))
            inner_qs = parse_qs(inner.query)
            if "id" in inner_qs and inner_qs["id"][0].isdigit():
                return inner_qs["id"][0]

    return None


def _graph_dimensions(size: str) -> tuple[str, str, str]:
    """Return (width, height, font) tuple for size code S/M/L."""
    sizes = {
        "L": ("1500", "500", "13"),
        "S": ("400", "300", "9"),
    }
    return sizes.get(size.upper(), ("800", "350", "13"))


def _parse_historic_csv(text: str) -> dict[str, list]:
    """Parse a PRTG ``historicdata.csv`` payload into per-column lists.

    Handles two PRTG quirks:

    * The ``Date Time`` cell may have a trailing ``" - <interval>"``
      annotation that needs stripping before strptime.
    * PRTG appends a summary footer row whose ``Date Time`` cell reads
      something like ``"Sums (of 30 values)"`` or
      ``"Averages (of N values)"``. That row has no parseable timestamp;
      we detect it by trying strptime on the date cell and skip the
      entire row if parsing fails. This keeps the per-column lists
      aligned and avoids the partial-append misalignment the original
      try/except path created.

    Dates are parsed as US-format (``%m/%d/%Y %I:%M:%S %p``), matching
    PRTG's default CSV output. Servers configured for other regional
    formats will require adjustment.
    """
    lines = [l for l in text.splitlines() if l.strip()]
    reader = csv.reader(lines)

    data: dict[str, list] = {}
    headers: list[str] = []
    datetime_idx: int | None = None

    for i, row in enumerate(reader):
        if i == 0:
            headers = row
            for header in headers:
                data[header] = []
            datetime_idx = (
                headers.index("Date Time") if "Date Time" in headers else None
            )
            continue

        # Skip footer rows whose Date Time cell isn't a parseable timestamp
        # (e.g. "Sums (of 30 values)").
        if datetime_idx is not None and datetime_idx < len(row):
            cell = row[datetime_idx]
            if " -" in cell:
                cell = cell[: cell.index(" -")]
            try:
                datetime.strptime(cell, "%m/%d/%Y %I:%M:%S %p")
            except ValueError:
                continue

        for j, cell in enumerate(row):
            if headers[j] == "Date Time":
                if " -" in cell:
                    cell = cell[: cell.index(" -")]
                data[headers[j]].append(
                    datetime.strptime(cell, "%m/%d/%Y %I:%M:%S %p")
                )
            else:
                data[headers[j]].append(cell)
    return data


def _format_prtg_date(dateobj: datetime) -> str:
    """Format a datetime in the form PRTG expects: YYYY-MM-DD-HH-MM-SS."""
    return dateobj.strftime("%Y-%m-%d-%H-%M-%S")


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------


class Channel(BaseConfig, GlobalArrays):
    type = "Channel"

    def __init__(self, channelsoup, sensorid: str, confdata: ConfData) -> None:
        self.unpack_config(confdata)
        self.sensorid = sensorid
        _absorb_simple_children(self, channelsoup)
        self.id = self.objid
        self._parse_lastvalue()

    def __repr__(self) -> str:
        return f"<Channel name={self.name!r} id={self.id}>"

    def _parse_lastvalue(self) -> None:
        if not hasattr(self, "lastvalue") or not self.lastvalue:
            return
        parts = self.lastvalue.split(" ", 1)
        try:
            self.lastvalue_float = float(parts[0].replace(",", ""))
            self.lastvalue_int = int(self.lastvalue_float)
            self.unit = parts[1] if len(parts) > 1 else ""
        except ValueError:
            # Non-numeric lastvalue (e.g. "OK", "-") — leave fields unset.
            pass

    def rename(self, newname: str) -> None:
        self.set_property(name="name", value=newname)
        self.name = newname

    def pause(self, duration: int = 0, message: str = "") -> None:
        log.warning(
            "Channels cannot be paused directly; pausing parent sensor %s",
            self.sensorid,
        )
        if duration > 0:
            path = "pauseobjectfor.htm"
            params: dict[str, Any] = {
                "id": self.sensorid,
                "duration": duration,
            }
        else:
            path = "pause.htm"
            params = {"id": self.sensorid, "action": 0}
        if message:
            params["pausemsg"] = message
        self.get_request(path, params=params)

    def resume(self) -> None:
        log.warning(
            "Channels cannot be resumed directly; resuming parent sensor %s",
            self.sensorid,
        )
        self.get_request(
            "pause.htm",
            params={"id": self.sensorid, "action": 1},
        )

    def refresh(self, channelsoup) -> None:
        _absorb_simple_children(self, channelsoup)
        self.id = self.objid
        self._parse_lastvalue()

    def delete(self, confirm: bool = True) -> None:
        raise PrtgError("Channels cannot be deleted.")


# ---------------------------------------------------------------------------
# Sensor
# ---------------------------------------------------------------------------


class Sensor(BaseConfig, GlobalArrays):
    type = "Sensor"

    def __init__(self, sensorsoup, deviceid: str, confdata: ConfData) -> None:
        self.unpack_config(confdata)
        _absorb_simple_children(self, sensorsoup)
        self.attributes = sensorsoup.attrs
        self.channels: list[Channel] = []
        self.deviceid = deviceid

    def get_channels(self) -> None:
        req = self.get_request(
            "table.xml",
            params={
                "content": "channels",
                "output": "xml",
                "columns": "name,lastvalue_,objid",
                "id": self.id,
            },
        )
        channelsoup = BeautifulSoup(req.text, "xml")

        if not self.channels:
            for item in channelsoup.find_all("item"):
                self.channels.append(Channel(item, self.id, self.confdata))
            return

        # Refresh existing channels in-place where possible.
        by_objid = {c.objid: c for c in self.channels}
        for item in channelsoup.find_all("item"):
            objid = item.find("objid").string
            existing = by_objid.get(objid)
            if existing is not None:
                existing.refresh(item)

    def refresh(self, sensorsoup=None) -> None:
        if sensorsoup is None:
            soup = self.get_tree(root=self.id)
            sensorsoup = soup.sensortree.nodes.sensor
        _absorb_simple_children(self, sensorsoup)
        self.attributes = sensorsoup.attrs
        if self.channels:
            self.get_channels()

    def set_additional_param(self, parameterstring: str) -> None:
        self.set_property(name="params", value=parameterstring)

    def acknowledge(self, message: str = "") -> None:
        """Acknowledge an alarm, then refresh status to reflect the change."""
        super().acknowledge(message)
        self.get_status()


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------


class Device(BaseConfig, GlobalArrays):
    type = "Device"

    def __init__(self, devicesoup, confdata: ConfData) -> None:
        self.unpack_config(confdata)
        self.sensors: list[Sensor] = []
        for child in _iter_named_children(devicesoup):
            if child.name == "sensor":
                sensor = Sensor(child, devicesoup.find("id").string, self.confdata)
                self.sensors.append(sensor)
                self.allsensors.append(sensor)
            else:
                if child.string is None:
                    child.string = ""
                setattr(self, child.name, child.string)

        self._build_sensors_by_status()
        self.attributes = devicesoup.attrs

    def _build_sensors_by_status(self) -> None:
        self.sensors_by_status: dict[str, list[Sensor]] = {
            "Up": [],
            "Down": [],
            "Warning": [],
            "Paused": [],
        }
        for sensor in self.sensors:
            self.sensors_by_status.setdefault(sensor.status, []).append(sensor)

    def refresh(self, devicesoup=None) -> None:
        if devicesoup is None:
            soup = self.get_tree(root=self.id)
            devicesoup = soup.sensortree.nodes.device

        sensor_soups = [c for c in _iter_named_children(devicesoup) if c.name == "sensor"]
        _reconcile_children(
            sensor_soups,
            self.sensors,
            lambda s: Sensor(s, self.id, self.confdata),
            self.allsensors,
        )

        # Refresh non-child fields
        for child in _iter_named_children(devicesoup):
            if child.name != "sensor":
                if child.string is None:
                    child.string = ""
                setattr(self, child.name, child.string)

        self.attributes = devicesoup.attrs
        self._build_sensors_by_status()

    def set_host(self, host: str) -> None:
        self.set_property(name="host", value=host)
        self.host = host


# ---------------------------------------------------------------------------
# Group / Probe
# ---------------------------------------------------------------------------


class Group(BaseConfig, GlobalArrays):
    type = "Group"

    def __init__(self, groupsoup, confdata: ConfData) -> None:
        self.unpack_config(confdata)
        self.groups: list[Group] = []
        self.devices: list[Device] = []
        for child in _iter_named_children(groupsoup):
            if child.name == "device":
                d = Device(child, self.confdata)
                self.devices.append(d)
                self.alldevices.append(d)
            elif child.name == "group":
                g = Group(child, self.confdata)
                self.groups.append(g)
                self.allgroups.append(g)
            else:
                if child.string is None:
                    child.string = ""
                setattr(self, child.name, child.string)
        self.attributes = groupsoup.attrs

    def refresh(self, groupsoup=None) -> None:
        if groupsoup is None:
            soup = self.get_tree(root=self.id)
            root_node = soup.sensortree.nodes
            groupsoup = root_node.probenode if self.type == "Probe" else root_node.group

        device_soups = [c for c in _iter_named_children(groupsoup) if c.name == "device"]
        group_soups = [c for c in _iter_named_children(groupsoup) if c.name == "group"]

        _reconcile_children(
            device_soups,
            self.devices,
            lambda s: Device(s, self.confdata),
            self.alldevices,
        )
        _reconcile_children(
            group_soups,
            self.groups,
            lambda s: Group(s, self.confdata),
            self.allgroups,
        )

        # Refresh non-child fields
        for child in _iter_named_children(groupsoup):
            if child.name not in ("device", "group"):
                if child.string is None:
                    child.string = ""
                setattr(self, child.name, child.string)

        self.attributes = groupsoup.attrs


class Probe(Group):
    """A Probe is structurally identical to a Group; only the type differs."""

    type = "Probe"


# ---------------------------------------------------------------------------
# Top-level entry points
# ---------------------------------------------------------------------------


class PrtgApi(BaseConfig, GlobalArrays):
    """
    Top-level entry point for managing a PRTG server.

    Parameters:
        host:       PRTG server hostname or IP.
        user:       PRTG username (omit when using apikey).
        passhash:   PRTG passhash from Settings > Account Settings.
        apikey:     PRTG API token (preferred over user/passhash).
        rootid:     Root id of the subtree to manage. 0 = entire tree.
        protocol:   'http' or 'https'.
        port:       TCP port as a string, e.g. '443'.
        verify_ssl: Whether to verify TLS certificates. Default False
                    (matches the original module's behaviour). Set True
                    to enable certificate verification.
        timeout:    Per-request timeout in seconds. Default 30.

    Example:
        prtg = PrtgApi(
            host="192.168.1.1",
            user="prtgadmin",
            passhash="0000000",
            rootid=53,
        )
    """

    def __init__(
        self,
        host: str,
        user: str | None = None,
        passhash: str | None = None,
        apikey: str | None = None,
        rootid: str | int = 0,
        protocol: str = "https",
        port: str = "443",
        verify_ssl: bool = False,
        timeout: float = 30.0,
    ) -> None:
        confdata = ConfData(host, port, user, passhash, protocol, apikey, verify_ssl, timeout)
        self.unpack_config(confdata)
        self.clear_arrays()

        self.probes: list[Probe] = []
        self.groups: list[Group] = []
        self.devices: list[Device] = []

        self.treesoup = self.get_tree(root=rootid)
        self._parse_tree(self.treesoup.sensortree.nodes)

    def _parse_tree(self, nodes_soup) -> None:
        """Walk the top-level <nodes> element and create child objects."""
        for parent in _iter_named_children(nodes_soup):
            for child in _iter_named_children(parent):
                if child.name == "probenode":
                    p = Probe(child, self.confdata)
                    self.probes.append(p)
                    self.allprobes.append(p)
                elif child.name == "device":
                    d = Device(child, self.confdata)
                    self.devices.append(d)
                    self.alldevices.append(d)
                elif child.name == "group":
                    g = Group(child, self.confdata)
                    self.groups.append(g)
                    self.allgroups.append(g)
                else:
                    if child.string is None:
                        child.string = ""
                    setattr(self, child.name, child.string)

    def refresh(self) -> None:
        """Re-download the sensortree and reconcile in-memory objects."""
        self.treesoup = self.get_tree(root=self.id)

        # Collect direct candidates from the tree
        probe_soups: list = []
        group_soups: list = []
        device_soups: list = []
        leftover: list = []
        for parent in _iter_named_children(self.treesoup.sensortree.nodes):
            for child in _iter_named_children(parent):
                if child.name == "probenode":
                    probe_soups.append(child)
                elif child.name == "group":
                    group_soups.append(child)
                elif child.name == "device":
                    device_soups.append(child)
                else:
                    leftover.append(child)

        _reconcile_children(
            probe_soups,
            self.probes,
            lambda s: Probe(s, self.confdata),
            self.allprobes,
        )
        _reconcile_children(
            group_soups,
            self.groups,
            lambda s: Group(s, self.confdata),
            self.allgroups,
        )
        _reconcile_children(
            device_soups,
            self.devices,
            lambda s: Device(s, self.confdata),
            self.alldevices,
        )

        for child in leftover:
            if child.string is None:
                child.string = ""
            setattr(self, child.name, child.string)

    def search_byid(self, oid: str | int):
        """Find any object in the tree by id; returns None if not found."""
        oid = str(oid)
        for obj in (
            self.allprobes + self.allgroups + self.alldevices + self.allsensors
        ):
            if obj.id == oid:
                return obj
        return None


class PrtgDevice(BaseConfig):
    """
    Separate top-level entry point to manage a single device and its sensors
    without downloading an entire group tree.
    """

    def __init__(
        self,
        host: str,
        user: str | None = None,
        passhash: str | None = None,
        apikey: str | None = None,
        deviceid: str | int = 0,
        protocol: str = "https",
        port: str = "443",
        verify_ssl: bool = False,
        timeout: float = 30.0,
    ) -> None:
        confdata = ConfData(host, port, user, passhash, protocol, apikey, verify_ssl, timeout)
        self.unpack_config(confdata)
        self.deviceid = str(deviceid)
        self.sensors: list[Sensor] = []
        self._load()

    def _load(self) -> None:
        soup = self.get_tree(root=self.deviceid)
        device_node = soup.sensortree.nodes.device
        for child in _iter_named_children(device_node):
            if child.name == "sensor":
                self.sensors.append(
                    Sensor(child, device_node.find("id").string, self.confdata)
                )
            else:
                if child.string is None:
                    child.string = ""
                setattr(self, child.name, child.string)

        self.sensors_by_status: dict[str, list[Sensor]] = {
            "Up": [],
            "Down": [],
            "Warning": [],
            "Paused": [],
        }
        for sensor in self.sensors:
            self.sensors_by_status.setdefault(sensor.status, []).append(sensor)

    def refresh(self) -> None:
        soup = self.get_tree(root=self.deviceid)
        device_node = soup.sensortree.nodes.device
        sensor_soups = [
            c for c in _iter_named_children(device_node) if c.name == "sensor"
        ]
        _reconcile_children(
            sensor_soups,
            self.sensors,
            lambda s: Sensor(s, self.id, self.confdata),
        )
        for child in _iter_named_children(device_node):
            if child.name != "sensor":
                if child.string is None:
                    child.string = ""
                setattr(self, child.name, child.string)


class PrtgSensor(BaseConfig):
    """
    Separate top-level entry point to manage a single sensor and its channels
    without downloading an entire group tree.
    """

    def __init__(
        self,
        host: str,
        user: str | None = None,
        passhash: str | None = None,
        apikey: str | None = None,
        sensorid: str | int = 0,
        protocol: str = "https",
        port: str = "443",
        verify_ssl: bool = False,
        timeout: float = 30.0,
    ) -> None:
        confdata = ConfData(host, port, user, passhash, protocol, apikey, verify_ssl, timeout)
        self.unpack_config(confdata)
        self.sensorid = str(sensorid)
        self.channels: list[Channel] = []

        soup = self.get_tree(root=self.sensorid)
        sensor_node = soup.sensortree.nodes.sensor
        _absorb_simple_children(self, sensor_node)
        self.attributes = sensor_node.attrs
        self.get_channels()

    def refresh(self) -> None:
        soup = self.get_tree(root=self.id)
        sensor_node = soup.sensortree.nodes.sensor
        _absorb_simple_children(self, sensor_node)
        self.attributes = sensor_node.attrs
        self.get_channels()

    def get_channels(self) -> None:
        req = self.get_request(
            "table.xml",
            params={
                "content": "channels",
                "output": "xml",
                "columns": "name,lastvalue_,objid",
                "id": self.id,
            },
        )
        channelsoup = BeautifulSoup(req.text, "xml")

        if not self.channels:
            for item in channelsoup.find_all("item"):
                self.channels.append(Channel(item, self.id, self.confdata))
            return

        by_objid = {c.objid: c for c in self.channels}
        for item in channelsoup.find_all("item"):
            objid = item.find("objid").string
            existing = by_objid.get(objid)
            if existing is not None:
                existing.refresh(item)


# ---------------------------------------------------------------------------
# Historic data (deprecated standalone client)
# ---------------------------------------------------------------------------


class PrtgHistoricData(ConnectionMethods):
    """
    Deprecated. Use ``sensor.get_historic_data(...)`` directly on any
    Sensor / PrtgSensor object instead.

    Kept as a thin shim for backwards compatibility. Emits
    ``DeprecationWarning`` on construction.

    Old usage:
        h = PrtgHistoricData(host=..., apikey=...)
        data = h.get_historic_data(objid=1234, startdate=..., enddate=..., timeaverage=300)

    New usage:
        sensor = PrtgSensor(host=..., apikey=..., sensorid=1234)
        data = sensor.get_historic_data(startdate=..., enddate=..., timeaverage=300)

    Or on a Sensor already loaded via PrtgApi:
        data = api.search_byid(1234).get_historic_data(...)
    """

    def __init__(
        self,
        host: str,
        user: str | None = None,
        passhash: str | None = None,
        apikey: str | None = None,
        port: str = "443",
        protocol: str = "https",
        verify_ssl: bool = False,
        timeout: float = 30.0,
    ) -> None:
        import warnings as _warnings
        _warnings.warn(
            "PrtgHistoricData is deprecated; call get_historic_data() "
            "directly on a Sensor or PrtgSensor object instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        confdata = ConfData(
            host, port, user, passhash, protocol, apikey, verify_ssl, timeout
        )
        self.unpack_config(confdata)

    @staticmethod
    def format_date(dateobj: datetime) -> str:
        """Format a datetime in the form PRTG expects: YYYY-MM-DD-HH-MM-SS."""
        return _format_prtg_date(dateobj)

    def get_historic_data(
        self,
        objid: str | int,
        startdate: datetime | str,
        enddate: datetime | str,
        timeaverage: int,
    ) -> dict[str, list]:
        """Fetch historic data for an arbitrary object id."""
        if isinstance(startdate, datetime):
            startdate = _format_prtg_date(startdate)
        if isinstance(enddate, datetime):
            enddate = _format_prtg_date(enddate)

        req = self.get_request(
            "historicdata.csv",
            params={
                "id": objid,
                "avg": timeaverage,
                "sdate": startdate,
                "edate": enddate,
            },
        )
        return _parse_historic_csv(req.text)


# ---------------------------------------------------------------------------
# Deprecated lowercase aliases
# ---------------------------------------------------------------------------
#
# The original module used PEP-8-non-conforming class names (`prtg_api`,
# `prtg_device`, `prtg_sensor`). These aliases let existing scripts keep
# working as drop-in replacements while emitting a DeprecationWarning that
# acts as a TODO marker. Update your imports to the PascalCase names at
# your convenience; the aliases will be removed in a future release.


def _make_deprecated_alias(new_cls: type, old_name: str) -> type:
    """Build a subclass of ``new_cls`` that warns on construction."""

    class _Deprecated(new_cls):  # type: ignore[valid-type, misc]
        def __init__(self, *args, **kwargs):
            import warnings as _warnings
            _warnings.warn(
                f"{old_name} is deprecated; use {new_cls.__name__} instead. "
                f"They are identical, only the class name has changed.",
                DeprecationWarning,
                stacklevel=2,
            )
            super().__init__(*args, **kwargs)

    _Deprecated.__name__ = old_name
    _Deprecated.__qualname__ = old_name
    _Deprecated.__doc__ = (
        f"Deprecated alias for {new_cls.__name__}. "
        f"Will be removed in a future release."
    )
    return _Deprecated


prtg_api = _make_deprecated_alias(PrtgApi, "prtg_api")
prtg_device = _make_deprecated_alias(PrtgDevice, "prtg_device")
prtg_sensor = _make_deprecated_alias(PrtgSensor, "prtg_sensor")
