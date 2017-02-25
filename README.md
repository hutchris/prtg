# prtg
Python module to manage PRTG servers

Prerequisites:
- bs4 (BeautifulSoup)
- requests
- lxml
- yml

Tested only on Python 3.5.2 so far.

This is a Python module to facilitate in managing PRTG servers from CLI or for automating changes.

The first thing you should do is edit the config.yml file and add your username and passhash. You can find this in the settings page for your user account. There is also an API call you can make which returns it. 

Upon initialisation the entire device tree is downloaded and each probe, group, device, sensor and channel is provided as a modifiable object. From the main object (called prtg in example) you can access all objects in the tree using the prtg.allprobes, prtg.allgroups, prtg.alldevices and prtg.allsensors attributes. The channels are not available by default, you must run sensor.get_channels() to the get the child channels of that sensor.

When you are accessing an object further down the tree you only have access to the direct children of that object. This for example will show the devices that are in the 4th group of the allgroups array:
```
from prtg import prtg_api

prtg = prtg_api()

prtg.allgroups[3].devices
```
Probe and group objects can have groups and devices as children, device objects have sensors as children and sensors can have channels as children.
```
from prtg import prtg_api

prtg = prtg_api()

probeobject = prtg.allprobes[0]
groups = probobject.groups
devices = probobject.devices

deviceobject = devices[0]
sensors = deviceobject.sensors

sensorobject = sensors[0]
sensorobject.get_channels()

channel = sensorobject.channels[0]
```


Current methods on all objects include:
- rename
- pause (pause and resume on a channel will change the parent sensor)
- resume
- clone
- delete
- refresh
- set_property

To come:
- move

If you are making small changes such as pause, resume, rename; the local data will update as you go. If you are doing larger changes you should refresh the data after each change. If you refresh the main prtg object it will refresh everything otherwise you can just refresh an object further down the tree to only refresh part of the local data. To refresh an object call the .refresh() method.

The set_property method is very powerful and flexible. You can change anything for an object that you can change in the objects settings tab in the web ui. I will add the more commonly used settings as seperate methods.

There are delays with some actions such as resuming so you should add time delays where appropriate.

example usage:
```
import time
from prtg import prtg_api

prtg = prtg_api()

for device in prtg.alldevices:
  if device.id == "1234":
    deviceobj = device

deviceobj.pause()
deviceobj.clone(newname="cloned device",newplaceid="2468")

time.sleep(10)

prtg.refresh()

for device in prtg.alldevices:
  if device.name = "cloned device":
    device.resume()

```
