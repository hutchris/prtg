"""
Tests for prtg.py.

The HTTP layer is mocked end-to-end — no real PRTG server is required.
Tests cover:

  * URL/parameter construction (the biggest correctness change in the
    refactor — values are now sent via ``params=`` and must be properly
    encoded).
  * Parsing the sensortree XML into nested Python objects.
  * refresh() reconciliation: existing objects updated, new ones added,
    missing ones removed, across PrtgApi, Group, Device.
  * The historic-data CSV parser.
  * The clone() id-extraction logic, including the login-page response
    shape that was producing AttributeError on `req.history[-1]` in the
    original code.

Run with:
    python -m unittest discover tests
or:
    python -m pytest tests/
"""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

import prtg


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_response(
    text: str = "",
    status_code: int = 200,
    url: str = "https://prtg.example.com/api/foo",
    history_urls: list[str] | None = None,
) -> MagicMock:
    """Build a mock requests.Response with the bits prtg.py inspects."""
    resp = MagicMock()
    resp.text = text
    resp.status_code = status_code
    resp.url = url
    resp.history = []
    if history_urls:
        for hurl in history_urls:
            h = MagicMock()
            h.url = hurl
            resp.history.append(h)
    # For save_graph streaming
    resp.iter_content = lambda chunk_size=None: iter([b""])
    resp.raise_for_status = lambda: None
    return resp


SENSORTREE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<sensortree>
  <nodes>
    <group>
      <id>0</id>
      <name>Root</name>
      <active>true</active>
      <probenode>
        <id>1</id>
        <name>Local Probe</name>
        <active>true</active>
        <group>
          <id>10</id>
          <name>Servers</name>
          <active>true</active>
          <device>
            <id>100</id>
            <name>web-01</name>
            <active>true</active>
            <host>10.0.0.1</host>
            <sensor>
              <id>1000</id>
              <name>Ping</name>
              <active>true</active>
              <status>Up</status>
            </sensor>
            <sensor>
              <id>1001</id>
              <name>HTTP</name>
              <active>true</active>
              <status>Warning</status>
            </sensor>
          </device>
          <device>
            <id>101</id>
            <name>db-01</name>
            <active>true</active>
            <host>10.0.0.2</host>
          </device>
        </group>
      </probenode>
    </group>
  </nodes>
</sensortree>
"""


# Same tree but with web-01's HTTP sensor removed and a new sensor added,
# plus the db-01 device removed entirely.
SENSORTREE_XML_AFTER_CHANGES = """<?xml version="1.0" encoding="UTF-8"?>
<sensortree>
  <nodes>
    <group>
      <id>0</id>
      <name>Root</name>
      <active>true</active>
      <probenode>
        <id>1</id>
        <name>Local Probe</name>
        <active>true</active>
        <group>
          <id>10</id>
          <name>Servers</name>
          <active>true</active>
          <device>
            <id>100</id>
            <name>web-01</name>
            <active>true</active>
            <host>10.0.0.1</host>
            <sensor>
              <id>1000</id>
              <name>Ping</name>
              <active>true</active>
              <status>Up</status>
            </sensor>
            <sensor>
              <id>1002</id>
              <name>CPU</name>
              <active>true</active>
              <status>Up</status>
            </sensor>
          </device>
        </group>
      </probenode>
    </group>
  </nodes>
</sensortree>
"""


# ---------------------------------------------------------------------------
# Construction & parsing
# ---------------------------------------------------------------------------


class TestPrtgApiConstruction(unittest.TestCase):
    """Verify the sensortree XML is parsed into nested objects correctly."""

    def setUp(self) -> None:
        prtg.GlobalArrays.allprobes.clear()
        prtg.GlobalArrays.allgroups.clear()
        prtg.GlobalArrays.alldevices.clear()
        prtg.GlobalArrays.allsensors.clear()

    @patch("prtg.requests.get")
    def test_constructs_tree(self, mock_get):
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(
            host="prtg.example.com",
            apikey="testtoken",
            rootid=0,
        )
        self.assertEqual(len(api.probes), 1)
        probe = api.probes[0]
        self.assertEqual(probe.id, "1")
        self.assertEqual(probe.name, "Local Probe")
        self.assertEqual(probe.type, "Probe")
        self.assertEqual(len(probe.groups), 1)
        group = probe.groups[0]
        self.assertEqual(group.name, "Servers")
        self.assertEqual(len(group.devices), 2)
        web = next(d for d in group.devices if d.name == "web-01")
        self.assertEqual(web.host, "10.0.0.1")
        self.assertEqual(len(web.sensors), 2)

    @patch("prtg.requests.get")
    def test_global_arrays_populated(self, mock_get):
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        self.assertEqual(len(api.allprobes), 1)
        self.assertEqual(len(api.allgroups), 1)
        self.assertEqual(len(api.alldevices), 2)
        self.assertEqual(len(api.allsensors), 2)

    @patch("prtg.requests.get")
    def test_search_byid(self, mock_get):
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        self.assertEqual(api.search_byid(100).name, "web-01")
        self.assertEqual(api.search_byid("1001").name, "HTTP")
        self.assertIsNone(api.search_byid(99999))


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class TestAuth(unittest.TestCase):
    def test_no_credentials_raises(self):
        with self.assertRaises(prtg.AuthenticationError):
            prtg.PrtgApi(host="x")

    def test_partial_credentials_raises(self):
        with self.assertRaises(prtg.AuthenticationError):
            prtg.PrtgApi(host="x", user="u")  # no passhash, no apikey

    @patch("prtg.requests.get")
    def test_apikey_used_in_params(self, mock_get):
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        prtg.PrtgApi(host="x", apikey="MYTOKEN")
        # The first call's params should include the apitoken
        call = mock_get.call_args_list[0]
        params = call.kwargs["params"]
        self.assertEqual(params["apitoken"], "MYTOKEN")
        self.assertNotIn("username", params)

    @patch("prtg.requests.get")
    def test_userpass_used_in_params(self, mock_get):
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        prtg.PrtgApi(host="x", user="bob", passhash="abc123")
        call = mock_get.call_args_list[0]
        params = call.kwargs["params"]
        self.assertEqual(params["username"], "bob")
        self.assertEqual(params["passhash"], "abc123")
        self.assertNotIn("apitoken", params)

    @patch("prtg.requests.get")
    def test_401_raises_authentication_error(self, mock_get):
        mock_get.return_value = make_response(text="nope", status_code=401)
        with self.assertRaises(prtg.AuthenticationError):
            prtg.PrtgApi(host="x", apikey="t")

    @patch("prtg.requests.get")
    def test_404_raises_resource_not_found(self, mock_get):
        mock_get.return_value = make_response(text="", status_code=404)
        with self.assertRaises(prtg.ResourceNotFound):
            prtg.PrtgApi(host="x", apikey="t")

    @patch("prtg.requests.get")
    def test_400_raises_malformed(self, mock_get):
        mock_get.return_value = make_response(text="", status_code=400)
        with self.assertRaises(prtg.MalformedRequest):
            prtg.PrtgApi(host="x", apikey="t")


# ---------------------------------------------------------------------------
# URL / parameter construction
# ---------------------------------------------------------------------------


class TestParameterEncoding(unittest.TestCase):
    """
    The biggest behavioural change in the refactor: values are sent via
    ``params=`` so requests handles URL-encoding. These tests verify
    callers can pass values with special characters without breaking
    the request or injecting extra parameters.
    """

    def setUp(self) -> None:
        prtg.GlobalArrays.allprobes.clear()
        prtg.GlobalArrays.allgroups.clear()
        prtg.GlobalArrays.alldevices.clear()
        prtg.GlobalArrays.allsensors.clear()

    def _make_api(self, mock_get) -> prtg.PrtgApi:
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        return prtg.PrtgApi(host="prtg.example.com", apikey="t")

    @patch("prtg.requests.get")
    def test_rename_passes_value_through_params(self, mock_get):
        api = self._make_api(mock_get)
        device = api.alldevices[0]
        # Rename with a value containing spaces and an ampersand
        device.rename("web & app server")
        last_call = mock_get.call_args_list[-1]
        self.assertEqual(last_call.kwargs["params"]["value"], "web & app server")
        # The URL itself should NOT contain the raw &, because it's in params
        self.assertNotIn("&value=", last_call.args[0])

    @patch("prtg.requests.get")
    def test_pause_message_handled(self, mock_get):
        api = self._make_api(mock_get)
        device = api.alldevices[0]
        device.pause(duration=60, message="rolling out v2.0 — please wait")
        last_call = mock_get.call_args_list[-1]
        params = last_call.kwargs["params"]
        self.assertEqual(params["pausemsg"], "rolling out v2.0 — please wait")
        self.assertEqual(params["duration"], 60)

    @patch("prtg.requests.get")
    def test_set_property_with_special_chars(self, mock_get):
        api = self._make_api(mock_get)
        device = api.alldevices[0]
        # A tag string containing characters that would have broken the
        # old string-format approach
        device.set_property("tags", "env=prod team=ops alert=on&off")
        last_call = mock_get.call_args_list[-1]
        self.assertEqual(
            last_call.kwargs["params"]["value"],
            "env=prod team=ops alert=on&off",
        )

    @patch("prtg.requests.get")
    def test_add_tags_deduplicates(self, mock_get):
        api = self._make_api(mock_get)
        device = api.alldevices[0]
        # First call returns existing tags (from get_property)
        mock_get.return_value = make_response(
            text="<result>foo bar</result>",
        )
        device.add_tags(["bar", "baz"])
        # The last call is set_property — tags value should be deduped
        last_call = mock_get.call_args_list[-1]
        self.assertEqual(last_call.kwargs["params"]["value"], "foo bar baz")

    @patch("prtg.requests.get")
    def test_pause_endpoint_choice(self, mock_get):
        """duration=0 hits pause.htm, duration>0 hits pauseobjectfor.htm."""
        api = self._make_api(mock_get)
        device = api.alldevices[0]

        device.pause()  # duration=0
        endpoint = mock_get.call_args_list[-1].args[0]
        self.assertTrue(endpoint.endswith("pause.htm"))

        device.pause(duration=300)
        endpoint = mock_get.call_args_list[-1].args[0]
        self.assertTrue(endpoint.endswith("pauseobjectfor.htm"))

    @patch("prtg.requests.get")
    def test_verify_ssl_propagated_false(self, mock_get):
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        prtg.PrtgApi(host="x", apikey="t", verify_ssl=False)
        self.assertEqual(mock_get.call_args_list[0].kwargs["verify"], False)

    @patch("prtg.requests.get")
    def test_verify_ssl_propagated_true(self, mock_get):
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        prtg.PrtgApi(host="x", apikey="t", verify_ssl=True)
        self.assertEqual(mock_get.call_args_list[0].kwargs["verify"], True)

    @patch("prtg.requests.get")
    def test_verify_ssl_default_false(self, mock_get):
        """Default matches the original module's behaviour."""
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        prtg.PrtgApi(host="x", apikey="t")
        self.assertEqual(mock_get.call_args_list[0].kwargs["verify"], False)


# ---------------------------------------------------------------------------
# Refresh / reconciliation
# ---------------------------------------------------------------------------


class TestRefresh(unittest.TestCase):
    """
    Exercise _reconcile_children through the various refresh() paths.
    A sensor is added, another is removed, a device disappears — the
    in-memory tree should match the new XML afterwards.
    """

    def setUp(self) -> None:
        prtg.GlobalArrays.allprobes.clear()
        prtg.GlobalArrays.allgroups.clear()
        prtg.GlobalArrays.alldevices.clear()
        prtg.GlobalArrays.allsensors.clear()

    @patch("prtg.requests.get")
    def test_device_refresh_adds_and_removes_sensors(self, mock_get):
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        web = next(d for d in api.alldevices if d.name == "web-01")
        self.assertEqual(
            {s.name for s in web.sensors}, {"Ping", "HTTP"}
        )

        # Now return the updated tree on refresh — but the device-level
        # refresh fetches just the device subtree, so build a small one
        device_only_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <sensortree><nodes><device>
            <id>100</id><name>web-01</name><active>true</active>
            <host>10.0.0.1</host>
            <sensor><id>1000</id><name>Ping</name>
                <active>true</active><status>Up</status></sensor>
            <sensor><id>1002</id><name>CPU</name>
                <active>true</active><status>Up</status></sensor>
        </device></nodes></sensortree>
        """
        mock_get.return_value = make_response(text=device_only_xml)
        web.refresh()
        self.assertEqual(
            {s.name for s in web.sensors}, {"Ping", "CPU"}
        )

    @patch("prtg.requests.get")
    def test_group_refresh_removes_missing_devices(self, mock_get):
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        group = api.allgroups[0]
        self.assertEqual(len(group.devices), 2)

        group_only_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <sensortree><nodes><group>
            <id>10</id><name>Servers</name><active>true</active>
            <device>
                <id>100</id><name>web-01</name><active>true</active>
                <host>10.0.0.1</host>
            </device>
        </group></nodes></sensortree>
        """
        mock_get.return_value = make_response(text=group_only_xml)
        group.refresh()
        self.assertEqual(len(group.devices), 1)
        self.assertEqual(group.devices[0].name, "web-01")


# ---------------------------------------------------------------------------
# clone()  — the user's original bug
# ---------------------------------------------------------------------------


class TestClone(unittest.TestCase):
    """
    Original failure was:
        AttributeError: 'NoneType' object has no attribute 'history'
    Actually: req.history was empty (no redirects), so req.history[-1]
    raised IndexError, OR PRTG returned a login-page URL with the id
    embedded in a ``loginurl`` parameter. We now handle multiple shapes
    including the SSO redirect chain seen in real-world Azure-AD-backed
    PRTG installations.
    """

    def setUp(self) -> None:
        prtg.GlobalArrays.allprobes.clear()
        prtg.GlobalArrays.allgroups.clear()
        prtg.GlobalArrays.alldevices.clear()
        prtg.GlobalArrays.allsensors.clear()

    @patch("prtg.requests.get")
    def test_clone_with_classic_redirect(self, mock_get):
        # 302 → final URL has ?id=9999
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        device = api.alldevices[0]

        mock_get.return_value = make_response(
            text="ok",
            url="https://prtg.example.com/device.htm?id=9999",
            history_urls=[
                "https://prtg.example.com/api/duplicateobject.htm?id=100&name=foo&targetid=10",
            ],
        )
        new_id = device.clone("new-name", "10")
        self.assertEqual(new_id, "9999")

    @patch("prtg.requests.get")
    def test_clone_with_sso_redirect_chain(self, mock_get):
        """
        Real-world Azure-AD SSO redirect chain captured from a production
        PRTG install (blackwall.io, June 2026). The chain goes:

          1. duplicateobject.htm  (request URL — has SOURCE id, must skip)
          2. sensor.htm?id=NNN    (the new id — direct redirect from PRTG)
          3. login.htm?loginurl=/sensor.htm?id=NNN
          4. Azure AD authorize  (no id at all)
          5. /cb?error=login_required  (no id)
          6. local_login.htm?loginurl=/sensor.htm?id=NNN  (final, id in loginurl)

        Our extractor must NOT pick up the source id from URL 1, must
        find the new id from one of 2/3/6, and must skip 4/5.
        """
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        device = api.alldevices[0]

        mock_get.return_value = make_response(
            text="<html>...</html>",
            url=(
                "https://prtg.example.com/public/local_login.htm"
                "?loginurl=%2Fsensor.htm%3Fid%3D39338"
            ),
            history_urls=[
                "https://prtg.example.com/api/duplicateobject.htm?id=100&name=foo&targetid=10",
                "https://prtg.example.com/sensor.htm?id=39338",
                "https://prtg.example.com/public/login.htm?loginurl=%2Fsensor.htm%3Fid%3D39338&errorid=0",
                "https://login.microsoftonline.com/abc/oauth2/v2.0/authorize?response_type=code",
                "https://prtg.example.com/cb?error=login_required&state=xxx",
            ],
        )
        new_id = device.clone("new-name", "10")
        self.assertEqual(new_id, "39338")

    @patch("prtg.requests.get")
    def test_clone_skips_source_id_in_request_url(self, mock_get):
        """
        Critical: must NOT pick up the source id from the original
        duplicateobject.htm request URL (which has ?id=<source>).
        """
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        device = api.alldevices[0]  # device id is "100"

        # Final URL is the duplicateobject request itself (PRTG returned
        # immediately without redirecting). No "real" new id available.
        mock_get.return_value = make_response(
            text="ok",
            url="https://prtg.example.com/api/duplicateobject.htm?id=100&name=foo&targetid=10",
        )
        # Should NOT return "100" (that's the source). Should return None.
        self.assertIsNone(device.clone("new-name", "10"))

    @patch("prtg.requests.get")
    def test_clone_with_login_page_response(self, mock_get):
        """The Paessler-KB-documented shape: final URL is a login page."""
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        device = api.alldevices[0]

        # No redirect; PRTG returned a login page whose query string
        # contains the new id inside loginurl=.
        mock_get.return_value = make_response(
            text="<html>Login</html>",
            url=(
                "https://prtg.example.com/public/login.htm"
                "?loginurl=%2Fobject.htm%3Fid%3D9999&errormsg="
            ),
            history_urls=None,
        )
        new_id = device.clone("new-name", "10")
        self.assertEqual(new_id, "9999")

    @patch("prtg.requests.get")
    def test_clone_with_direct_id_url(self, mock_get):
        """No redirects, but the final URL has ?id=NNN directly."""
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        device = api.alldevices[0]

        mock_get.return_value = make_response(
            text="ok",
            url="https://prtg.example.com/device.htm?id=8888",
        )
        self.assertEqual(device.clone("n", "10"), "8888")

    @patch("prtg.requests.get")
    def test_clone_with_unparseable_response_returns_none(self, mock_get):
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        device = api.alldevices[0]

        mock_get.return_value = make_response(
            text="progress info only",
            url="https://prtg.example.com/api/duplicateobject.htm",
        )
        self.assertIsNone(device.clone("n", "10"))


# ---------------------------------------------------------------------------
# Channel value parsing
# ---------------------------------------------------------------------------


class TestChannelLastValueParsing(unittest.TestCase):
    """The original parser exploded on values without units or negatives."""

    def _make_channel(self, lastvalue: str) -> prtg.Channel:
        # Build a minimal channelsoup
        from bs4 import BeautifulSoup
        xml = f"""<item>
            <objid>1</objid>
            <name>c</name>
            <lastvalue>{lastvalue}</lastvalue>
        </item>"""
        soup = BeautifulSoup(xml, "lxml").item
        confdata = prtg.ConfData("h", "443", None, None, "https", "t", True, 30.0)
        return prtg.Channel(soup, sensorid="1", confdata=confdata)

    def test_value_with_unit(self):
        c = self._make_channel("42 ms")
        self.assertEqual(c.lastvalue_int, 42)
        self.assertEqual(c.unit, "ms")

    def test_value_without_unit(self):
        # The original code raised IndexError here
        c = self._make_channel("42")
        self.assertEqual(c.lastvalue_int, 42)
        self.assertEqual(c.unit, "")

    def test_value_with_comma_thousands(self):
        c = self._make_channel("1,234 kbit/s")
        self.assertEqual(c.lastvalue_int, 1234)

    def test_value_with_decimal(self):
        c = self._make_channel("42.5 ms")
        self.assertEqual(c.lastvalue_float, 42.5)

    def test_non_numeric_value_doesnt_crash(self):
        # The original code didn't crash here, but didn't set any of the
        # numeric attrs either. Make sure we behave the same way.
        c = self._make_channel("OK")
        self.assertFalse(hasattr(c, "lastvalue_int"))


# ---------------------------------------------------------------------------
# Historic data
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Historic data
# ---------------------------------------------------------------------------


class TestHistoricDataOnSensor(unittest.TestCase):
    """Preferred path: sensor.get_historic_data() inherited from BaseConfig."""

    def setUp(self) -> None:
        prtg.GlobalArrays.allprobes.clear()
        prtg.GlobalArrays.allgroups.clear()
        prtg.GlobalArrays.alldevices.clear()
        prtg.GlobalArrays.allsensors.clear()

    @patch("prtg.requests.get")
    def test_sensor_get_historic_data(self, mock_get):
        from datetime import datetime
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        sensor = api.allsensors[0]

        csv_text = (
            'Date Time,"Traffic In (kbit/s)","Traffic Out (kbit/s)"\n'
            '"05/29/2026 10:00:00 AM",100,200\n'
            '"05/29/2026 10:05:00 AM",110,210\n'
        )
        mock_get.return_value = make_response(text=csv_text)
        data = sensor.get_historic_data(
            startdate="2026-05-29-00-00-00",
            enddate="2026-05-29-23-59-59",
            timeaverage=300,
        )
        self.assertEqual(len(data["Date Time"]), 2)
        self.assertEqual(data["Traffic In (kbit/s)"], ["100", "110"])
        self.assertEqual(data["Date Time"][0], datetime(2026, 5, 29, 10, 0, 0))

        # Verify the request used the sensor's own id, not a manually-passed one
        last_call = mock_get.call_args_list[-1]
        self.assertEqual(last_call.kwargs["params"]["id"], sensor.id)

    @patch("prtg.requests.get")
    def test_skips_summary_footer_row(self, mock_get):
        """PRTG appends a footer like 'Sums (of 30 values)' that isn't a date."""
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        sensor = api.allsensors[0]

        csv_text = (
            'Date Time,"Traffic In (kbit/s)","Traffic Out (kbit/s)"\n'
            '"05/29/2026 10:00:00 AM",100,200\n'
            '"05/29/2026 10:05:00 AM",110,210\n'
            '"05/29/2026 10:10:00 AM",120,220\n'
            '"Sums (of 30 values)",330,630\n'
        )
        mock_get.return_value = make_response(text=csv_text)
        data = sensor.get_historic_data(
            startdate="2026-05-29-00-00-00",
            enddate="2026-05-29-23-59-59",
            timeaverage=300,
        )
        # Footer should be skipped entirely; lists stay aligned at length 3
        self.assertEqual(len(data["Date Time"]), 3)
        self.assertEqual(len(data["Traffic In (kbit/s)"]), 3)
        self.assertEqual(len(data["Traffic Out (kbit/s)"]), 3)
        # Footer's numeric cells must NOT appear
        self.assertNotIn("330", data["Traffic In (kbit/s)"])

    @patch("prtg.requests.get")
    def test_skips_averages_footer_row(self, mock_get):
        """Variant footer: 'Averages (of N values)'."""
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        sensor = api.allsensors[0]

        csv_text = (
            'Date Time,"Traffic In (kbit/s)"\n'
            '"05/29/2026 10:00:00 AM",100\n'
            '"Averages (of 12 values)",105\n'
        )
        mock_get.return_value = make_response(text=csv_text)
        data = sensor.get_historic_data(
            startdate="2026-05-29-00-00-00",
            enddate="2026-05-29-23-59-59",
            timeaverage=300,
        )
        self.assertEqual(len(data["Date Time"]), 1)
        self.assertEqual(data["Traffic In (kbit/s)"], ["100"])

    @patch("prtg.requests.get")
    def test_datetime_argument_auto_formatted(self, mock_get):
        from datetime import datetime
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        sensor = api.allsensors[0]

        mock_get.return_value = make_response(text='Date Time\n"01/01/2026 12:00:00 PM"\n')
        sensor.get_historic_data(
            startdate=datetime(2026, 1, 1),
            enddate=datetime(2026, 1, 2),
            timeaverage=0,
        )
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["sdate"], "2026-01-01-00-00-00")
        self.assertEqual(params["edate"], "2026-01-02-00-00-00")

    @patch("prtg.requests.get")
    def test_strips_date_time_interval_annotation(self, mock_get):
        """Date Time cells may have a trailing ' - <interval>' suffix."""
        from datetime import datetime
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        sensor = api.allsensors[0]

        csv_text = (
            'Date Time,Value\n'
            '"05/29/2026 10:00:00 AM - 05/29/2026 10:05:00 AM",100\n'
        )
        mock_get.return_value = make_response(text=csv_text)
        data = sensor.get_historic_data(
            startdate="2026-05-29-00-00-00",
            enddate="2026-05-29-23-59-59",
            timeaverage=300,
        )
        self.assertEqual(data["Date Time"][0], datetime(2026, 5, 29, 10, 0, 0))


class TestHistoricDataDeprecated(unittest.TestCase):
    """The PrtgHistoricData shim still works but warns."""

    def test_construction_warns(self):
        with self.assertWarns(DeprecationWarning):
            prtg.PrtgHistoricData(host="x", apikey="t")

    @patch("prtg.requests.get")
    def test_legacy_class_still_parses(self, mock_get):
        import warnings as _w
        from datetime import datetime
        csv_text = (
            'Date Time,"Traffic In"\n'
            '"05/29/2026 10:00:00 AM",100\n'
            '"Sums (of 30 values)",100\n'
        )
        mock_get.return_value = make_response(text=csv_text)

        with _w.catch_warnings():
            _w.simplefilter("ignore", DeprecationWarning)
            h = prtg.PrtgHistoricData(host="x", apikey="t")

        data = h.get_historic_data(
            objid=1000,
            startdate="2026-05-29-00-00-00",
            enddate="2026-05-29-23-59-59",
            timeaverage=300,
        )
        # Footer-skip applies here too via the shared helper
        self.assertEqual(len(data["Date Time"]), 1)

    def test_format_date(self):
        from datetime import datetime
        self.assertEqual(
            prtg.PrtgHistoricData.format_date(datetime(2026, 1, 2, 3, 4, 5)),
            "2026-01-02-03-04-05",
        )


# ---------------------------------------------------------------------------
# delete()
# ---------------------------------------------------------------------------


class TestDelete(unittest.TestCase):
    def setUp(self) -> None:
        prtg.GlobalArrays.allprobes.clear()
        prtg.GlobalArrays.allgroups.clear()
        prtg.GlobalArrays.alldevices.clear()
        prtg.GlobalArrays.allsensors.clear()

    @patch("prtg.requests.get")
    def test_delete_root_raises(self, mock_get):
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        api.type = "Root"
        with self.assertRaises(prtg.PrtgError):
            api.delete(confirm=False)

    @patch("prtg.requests.get")
    def test_delete_channel_raises(self, mock_get):
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        from bs4 import BeautifulSoup
        channelsoup = BeautifulSoup(
            "<item><objid>1</objid><name>c</name></item>", "lxml"
        ).item
        c = prtg.Channel(channelsoup, sensorid="1", confdata=api.confdata)
        with self.assertRaises(prtg.PrtgError):
            c.delete()

    @patch("prtg.requests.get")
    def test_delete_calls_endpoint_with_approve(self, mock_get):
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        device = api.alldevices[0]
        device.delete(confirm=False)
        last_call = mock_get.call_args_list[-1]
        self.assertTrue(last_call.args[0].endswith("deleteobject.htm"))
        self.assertEqual(last_call.kwargs["params"]["approve"], 1)
        self.assertEqual(last_call.kwargs["params"]["id"], device.id)


# ---------------------------------------------------------------------------
# Timeout / connection errors
# ---------------------------------------------------------------------------


class TestTimeouts(unittest.TestCase):
    def setUp(self) -> None:
        prtg.GlobalArrays.allprobes.clear()
        prtg.GlobalArrays.allgroups.clear()
        prtg.GlobalArrays.alldevices.clear()
        prtg.GlobalArrays.allsensors.clear()

    @patch("prtg.requests.get")
    def test_timeout_passed_to_requests(self, mock_get):
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        prtg.PrtgApi(host="x", apikey="t", timeout=5.0)
        self.assertEqual(mock_get.call_args_list[0].kwargs["timeout"], 5.0)

    @patch("prtg.requests.get")
    def test_timeout_default_30(self, mock_get):
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        prtg.PrtgApi(host="x", apikey="t")
        self.assertEqual(mock_get.call_args_list[0].kwargs["timeout"], 30.0)

    @patch("prtg.requests.get")
    def test_timeout_exception_wrapped(self, mock_get):
        import requests as _requests
        mock_get.side_effect = _requests.exceptions.Timeout("slow")
        with self.assertRaises(prtg.PrtgError) as ctx:
            prtg.PrtgApi(host="x", apikey="t", timeout=1.0)
        self.assertIn("timed out", str(ctx.exception))

    @patch("prtg.requests.get")
    def test_connection_error_wrapped(self, mock_get):
        import requests as _requests
        mock_get.side_effect = _requests.exceptions.ConnectionError("refused")
        with self.assertRaises(prtg.PrtgError) as ctx:
            prtg.PrtgApi(host="x", apikey="t")
        self.assertIn("Connection to PRTG failed", str(ctx.exception))


# ---------------------------------------------------------------------------
# Login-page-on-200 detection
# ---------------------------------------------------------------------------


class TestLoginPageDetection(unittest.TestCase):
    """PRTG sometimes returns 200 with a login page on auth failure."""

    def setUp(self) -> None:
        prtg.GlobalArrays.allprobes.clear()
        prtg.GlobalArrays.allgroups.clear()
        prtg.GlobalArrays.alldevices.clear()
        prtg.GlobalArrays.allsensors.clear()

    @patch("prtg.requests.get")
    def test_login_page_on_200_raises_auth_error(self, mock_get):
        mock_get.return_value = make_response(
            text="<html>Login</html>",
            url="https://prtg.example.com/public/login.htm?errormsg=invalid",
        )
        with self.assertRaises(prtg.AuthenticationError):
            prtg.PrtgApi(host="x", apikey="bad")

    @patch("prtg.requests.get")
    def test_clone_bypasses_login_check(self, mock_get):
        """clone() must accept login-page responses since the id is in the URL."""
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        device = api.alldevices[0]

        mock_get.return_value = make_response(
            text="<html>Login</html>",
            url=(
                "https://prtg.example.com/public/login.htm"
                "?loginurl=%2Fobject.htm%3Fid%3D7777&errormsg="
            ),
        )
        # Should not raise — clone passes check_login_page=False
        self.assertEqual(device.clone("n", "10"), "7777")


# ---------------------------------------------------------------------------
# save_graph is now on BaseConfig and inherited by all objects
# ---------------------------------------------------------------------------


class TestInheritedSaveGraph(unittest.TestCase):
    def setUp(self) -> None:
        prtg.GlobalArrays.allprobes.clear()
        prtg.GlobalArrays.allgroups.clear()
        prtg.GlobalArrays.alldevices.clear()
        prtg.GlobalArrays.allsensors.clear()

    @patch("prtg.requests.get")
    def test_device_can_save_graph(self, mock_get):
        """Now that save_graph is on BaseConfig, devices/groups can use it too."""
        import tempfile, os
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        device = api.alldevices[0]

        # Mock the binary download
        binary_resp = make_response(text="")
        binary_resp.iter_content = lambda chunk_size=8192: iter([b"FAKEPNG"])
        mock_get.return_value = binary_resp

        with tempfile.NamedTemporaryFile(delete=False, suffix=".svg") as f:
            tmppath = f.name
        try:
            device.save_graph(graphid="0", filepath=tmppath, size="M")
            with open(tmppath, "rb") as f:
                self.assertEqual(f.read(), b"FAKEPNG")
        finally:
            os.unlink(tmppath)

    @patch("prtg.requests.get")
    def test_sensor_acknowledge_calls_get_status(self, mock_get):
        """Sensor.acknowledge overrides the base to refresh status afterwards."""
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        api = prtg.PrtgApi(host="x", apikey="t")
        sensor = api.allsensors[0]

        mock_get.return_value = make_response(text="<result>Up</result>")
        sensor.acknowledge("test ack")
        # Two calls: acknowledgealarm.htm then getobjectstatus.htm
        endpoints = [c.args[0] for c in mock_get.call_args_list[-2:]]
        self.assertTrue(endpoints[0].endswith("acknowledgealarm.htm"))
        self.assertTrue(endpoints[1].endswith("getobjectstatus.htm"))


# ---------------------------------------------------------------------------
# Deprecated lowercase aliases
# ---------------------------------------------------------------------------


class TestDeprecatedAliases(unittest.TestCase):
    """The old prtg_api / prtg_device / prtg_sensor names still work."""

    def setUp(self) -> None:
        prtg.GlobalArrays.allprobes.clear()
        prtg.GlobalArrays.allgroups.clear()
        prtg.GlobalArrays.alldevices.clear()
        prtg.GlobalArrays.allsensors.clear()

    @patch("prtg.requests.get")
    def test_prtg_api_alias_warns(self, mock_get):
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        with self.assertWarns(DeprecationWarning):
            prtg.prtg_api(host="x", apikey="t")

    @patch("prtg.requests.get")
    def test_prtg_api_alias_returns_working_object(self, mock_get):
        """Alias is a true subclass — instances behave identically."""
        import warnings as _w
        mock_get.return_value = make_response(text=SENSORTREE_XML)
        with _w.catch_warnings():
            _w.simplefilter("ignore", DeprecationWarning)
            api = prtg.prtg_api(host="x", apikey="t")
        # All the usual attributes work
        self.assertIsInstance(api, prtg.PrtgApi)
        self.assertEqual(len(api.probes), 1)
        self.assertEqual(api.probes[0].name, "Local Probe")

    @patch("prtg.requests.get")
    def test_prtg_device_alias_warns(self, mock_get):
        # PrtgDevice's constructor fetches a tree, so we need to provide a
        # device-shaped XML response.
        device_only_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <sensortree><nodes><device>
            <id>100</id><name>web-01</name><active>true</active>
            <host>10.0.0.1</host>
        </device></nodes></sensortree>
        """
        mock_get.return_value = make_response(text=device_only_xml)
        with self.assertWarns(DeprecationWarning):
            prtg.prtg_device(host="x", apikey="t", deviceid=100)

    @patch("prtg.requests.get")
    def test_prtg_sensor_alias_warns(self, mock_get):
        sensor_only_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <sensortree><nodes><sensor>
            <id>1000</id><name>Ping</name><active>true</active>
            <status>Up</status>
        </sensor></nodes></sensortree>
        """
        # Constructor calls get_channels too, which needs another response.
        # Easier to just patch out get_channels.
        mock_get.return_value = make_response(text=sensor_only_xml)
        with patch.object(prtg.PrtgSensor, "get_channels"):
            with self.assertWarns(DeprecationWarning):
                prtg.prtg_sensor(host="x", apikey="t", sensorid=1000)


if __name__ == "__main__":
    unittest.main()