# prtg
Python module to manage PRTG servers

Python module to facilitate managing PRTG servers from CLI or for automating changes.

Upon initialisation the entire device tree is downloaded and each probe, group, device, sensor and channel is provided as a modifiable object.

Current methods include:
- rename
- pause
- resume
- clone

To come:
- delete
- set property
- move

example usage:
```
from prtg import prtg_api

prtg = prtg_api()

sensorlist = []

for device in prtg.devices:
  if device.id = "1234":
    sensorlist = device.sensors
    
for sensor in sensorlist:
  sensor.pause()
```
