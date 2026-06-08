# prtg

Python module to manage PRTG servers.

## Prerequisites

- Python 3.7+
- `requests`
- `beautifulsoup4`
- `lxml`
- `urllib3`

Install with:

```
pip install -r requirements.txt
```

## Overview

This is a Python module to facilitate managing PRTG servers from the CLI or for automating changes. It's useful for scripting changes to PRTG objects.

The module no longer uses a config file. Instead you supply PRTG connection parameters when initialising the `PrtgApi` class. This lets you manage multiple PRTG instances from one script, or wrap the parameters in your own config loader if you prefer. The signature is:

```python
PrtgApi(
    host,
    user=None,
    passhash=None,
    apikey=None,
    rootid=0,
    protocol='https',
    port='443',
    verify_ssl=False,
    timeout=30.0,
)
```

Parameters:

- `host` — PRTG hostname or IP
- `user`, `passhash` — credentials from PRTG webgui > Settings > Account Settings. Either supply both, or supply `apikey` instead
- `apikey` — PRTG API token (preferred over user/passhash where available)
- `rootid` — ID of the group/probe that contains all the objects you want to manage. Defaults to 0 (the entire sensortree)
- `protocol` — `'http'` or `'https'`
- `port` — TCP port as a string
- `verify_ssl` — verify TLS certificates. Defaults to `False` (matches the original module). Set to `True` to opt in to verification.
- `timeout` — per-request timeout in seconds. Defaults to 30

Upon initialisation the entire sensortree (or the subtree rooted at `rootid`) is downloaded and each probe, group, device, sensor and channel is provided as a modifiable Python object. From the main object (called `prtg` in the examples below) you can access all objects in the tree via `prtg.allprobes`, `prtg.allgroups`, `prtg.alldevices`, and `prtg.allsensors`. Channels are not loaded by default — call `sensor.get_channels()` to populate them.

You can also set the root of your sensor tree to a group that isn't the PRTG root. This is useful when your PRTG server has many objects, or to provide access to a user with restricted permissions. When you access an object further down the tree, you only have access to its direct children. For example, this shows the devices in the 4th group:

```python
from prtg import PrtgApi

prtg = PrtgApi('192.168.1.1', 'prtgadmin', '0000000000')
# or with an API key:
prtg = PrtgApi('192.168.1.1', apikey='AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA======')

prtg.allgroups[3].devices
```

Probes and groups can have groups and devices as children; devices have sensors; sensors have channels.

```python
from prtg import PrtgApi

prtg = PrtgApi('192.168.1.1', 'prtgadmin', '0000000000')

probeobject = prtg.allprobes[0]
groups = probeobject.groups
devices = probeobject.devices

deviceobject = devices[0]
sensors = deviceobject.sensors

sensorobject = sensors[0]
sensorobject.get_channels()

channel = sensorobject.channels[0]
```

## Methods

Methods available on all objects (`*` marks required parameters):

- `rename(newname*)`
- `pause(duration=0, message='')` — pause/resume on a channel acts on its parent sensor
- `resume()`
- `clone(newname*, newplaceid*)` — returns the new object's ID, or `None` if it can't be determined
- `delete(confirm=True)` — can't delete the root object or channels
- `refresh()`
- `set_property(name*, value*)`
- `get_property(name*)`
- `set_interval(interval*)`
- `add_tags(['tag1', 'tag2']*, clear_old=False)`
- `acknowledge(message='')` — for sensors
- `save_graph(graphid*, filepath*, size*, hidden_channels='', filetype='svg')`
- `get_details()` — fetches the JSON sensordata blob
- `get_historic_data(startdate*, enddate*, timeaverage*)` — historic CSV data; only meaningful on sensors. See [Historic data](#historic-data) below.

Device-only:

- `set_host(host*)` — IP address or hostname

Sensor-only:

- `set_additional_param(param*)` — for custom script sensors

Top-level (`PrtgApi`) only:

- `search_byid(oid*)`

If you make small changes such as pause, resume, or rename, the local data updates as you go. For larger changes, call `.refresh()` afterwards. Refreshing the top-level object refreshes everything; refreshing a child only refreshes that subtree.

`set_property` is powerful: you can change anything for an object that you can change in its Settings tab in the web UI. The common ones are exposed as dedicated methods. Use `get_property` to test a property name first:

```python
from prtg import PrtgApi

prtg = PrtgApi('192.168.1.1', 'prtgadmin', '0000000000')
prtg.get_property(name='location')
# returns the location and sets prtg.location to the result

prtg.set_property(name='location', value='Canada')
```

Some actions (like resume) take time to take effect server-side; add `time.sleep(...)` where appropriate.

## Example

```python
import time
from prtg import PrtgApi

prtg = PrtgApi('192.168.1.1', 'prtgadmin', '0000000000')

deviceobj = prtg.search_byid("1234")

deviceobj.pause()
newid = deviceobj.clone(newname="cloned device", newplaceid="2468")

time.sleep(3)
prtg.refresh()

newdevice = prtg.search_byid(newid)
newdevice.resume()
```

## Managing a single device or sensor

If you only want to manage one device or sensor and don't want to download the full sensortree, use `PrtgDevice` or `PrtgSensor`:

```python
from prtg import PrtgDevice, PrtgSensor

host = '192.168.1.1'
user = 'prtgadmin'
passhash = '0000000'
apikey = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA======'

deviceid = '2025'
device = PrtgDevice(host, user=user, passhash=passhash, deviceid=deviceid)
# or with API Key
device = PrtgDevice(host, apikey=apikey, deviceid=deviceid)

sensorid = '2123'
sensor = PrtgSensor(host, user=user, passhash=passhash, sensorid=sensorid)
# or with API Key
sensor = PrtgSensor(host, apikey=apikey, sensorid=sensorid)
```

## Historic data

Use `get_historic_data` directly on any sensor object. It returns a dict keyed by column header, with parallel lists of values:

```python
from datetime import datetime, timedelta

sensor = PrtgSensor(host, apikey=apikey, sensorid='2123')

end = datetime.now()
start = end - timedelta(hours=24)

data = sensor.get_historic_data(
    startdate=start,
    enddate=end,
    timeaverage=300,  # 5-minute averages
)

for ts, value in zip(data['Date Time'], data['Traffic In (kbit/s)']):
    print(ts, value)
```

Date arguments may be `datetime` instances or pre-formatted `YYYY-MM-DD-HH-MM-SS` strings. `timeaverage` is the averaging interval in seconds (`0` = raw).

**Note:** PRTG returns dates in US format (`MM/DD/YYYY HH:MM:SS AM/PM`) by default; servers with different regional settings may need adjustment in the parser. PRTG also appends a summary footer row (e.g. `"Sums (of 30 values)"`) which the parser detects and skips automatically.

The previous standalone `PrtgHistoricData` class still exists but emits a `DeprecationWarning`. Migrate to `sensor.get_historic_data(...)` when convenient.

## SSL / self-signed certificates

`verify_ssl` defaults to `False` (matching the original module's behaviour — PRTG installs commonly use self-signed certs or chains that `requests` doesn't accept). Pass `verify_ssl=True` to opt in to certificate verification:

```python
prtg = PrtgApi('192.168.1.1', apikey='...', verify_ssl=True)
```

When `verify_ssl=False` the urllib3 `InsecureRequestWarning` is also suppressed for the process.

If your PRTG server has a valid cert but `requests` rejects it, the most common cause is a missing intermediate certificate in the server's chain — browsers fix this automatically by fetching the intermediate, but `requests` doesn't. Run `openssl s_client -connect yourprtg:443 -showcerts` to check the chain.

## Notes

- Past versions used class names like `prtg_api`, `prtg_device`, `prtg_sensor`. These have been renamed to PEP-8 PascalCase: `PrtgApi`, `PrtgDevice`, `PrtgSensor`. **The old names still work as drop-in aliases** but emit `DeprecationWarning` on construction — use them as TODO markers to update your scripts at your own pace. The aliases will be removed in a future release.
- All requests now have a configurable timeout (default 30 s). A hung PRTG server will raise `PrtgError` instead of blocking forever.
- All API calls now use proper URL parameter encoding, so values with `&`, spaces, or unicode (in tag names, pause messages, etc.) round-trip correctly.

## Repo layout

```
prtg/
├── prtg.py             # the module
├── README.md
├── requirements.txt
├── tests/
│   └── test_prtg.py    # mocked unit tests
```

## Running tests

The repo includes a unittest suite that mocks the HTTP layer — no live PRTG server needed. From the repo root:

```
python -m unittest discover tests
```

or with pytest:

```
pytest tests/
```

The tests cover URL parameter encoding, sensortree parsing, refresh reconciliation, the historic-data CSV parser (including the summary-footer-skip case), and the multi-shape `clone()` id extraction.

