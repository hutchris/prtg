# prtg
Python module to manage PRTG servers

Prerequisites:
- bs4 (BeautifulSoup)
- requests
- lxml

Tested only on Python 3.5.2 so far. Works with python 2.7, not tested extensively.

This is a Python module to facilitate in managing PRTG servers from CLI or for automating changes. It is really useful for scripting changes to prtg objects.

The prtg_api no longer uses a config file. Instead you need to enter your PRTG parameters when initiating the prtg_api class. This change was to allow this to be used in a more flexible way, or to manage multiple PRTG instances, you can still set up a local config file for your parameters if you wish. The positional parameters for initiating the prtg_api class are:

```
prtg_api(prtg_host,port,prtg_user,prtg_hash,protocol,rootid=0)
```

Upon initialisation the entire device tree is downloaded and each probe, group, device, sensor and channel is provided as a modifiable object. From the main object (called prtg in example) you can access all objects in the tree using the prtg.allprobes, prtg.allgroups, prtg.alldevices and prtg.allsensors attributes. The channels are not available by default, you must run sensor.get_channels() to the get the child channels of that sensor.

You can also set the root of your sensor tree as a group that is not the root of PRTG. This was added to allow a partial sensortree to be downloaded where your PRTG server may have many objects or to provide access to a user with restricted permissions.

When you are accessing an object further down the tree you only have access to the direct children of that object. This for example will show the devices that are in the 4th group of the allgroups array:

```
from prtg import prtg_api

prtg = prtg_api('192.168.1.1','80','prtgadmin','0000000000','http')

prtg.allgroups[3].devices
```

Probe and group objects can have groups and devices as children, device objects have sensors as children and sensors can have channels as children. 

```
from prtg import prtg_api

prtg = prtg_api('192.168.1.1','80','prtgadmin','0000000000','http')

probeobject = prtg.allprobes[0]
groups = probeobject.groups
devices = probeobject.devices

deviceobject = devices[0]
sensors = deviceobject.sensors

sensorobject = sensors[0]
sensorobject.get_channels()

channel = sensorobject.channels[0]
```


Current methods and parameters (* = required) on all objects include:
- rename
- pause (pause and resume on a channel will change the parent sensor)
 - duration=0
 - message=''
- resume
- clone
 - newname=''*
 - newplaceid=''*
- delete (you can't delete the root object or channels)
 - confirm=True
- refresh
- set_property
 - name*
 - value*
- set_additional_param (for custom script sensors)
 - param*
- set_interval
 - interval*
- set_host (ip address or hostname)
 - host*

To come:
- move

If you are making small changes such as pause, resume, rename; the local data will update as you go. If you are doing larger changes you should refresh the data after each change. If you refresh the main prtg object it will refresh everything otherwise you can just refresh an object further down the tree to only refresh part of the local data. To refresh an object call the .refresh() method.

The set_property method is very powerful and flexible. You can change anything for an object that you can change in the objects settings tab in the web ui. I will add the more commonly used settings as seperate methods.

There are delays with some actions such as resuming so you should add time delays where appropriate.

example usage:

```
import time
from prtg import prtg_api

prtg = prtg_api('192.168.1.1','80','prtgadmin','0000000000','http')

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
