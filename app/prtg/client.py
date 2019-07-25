# pylint: disable=too-many-lines
"""
Python API client module to manage PRTG servers
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import csv
from builtins import input as safe_input
from datetime import datetime

import requests
from bs4 import BeautifulSoup


class AuthenticationError(Exception):
    """
    Raised when failing to login to the API
    """


class UnhandledStatusCode(Exception):
    """
    Raised when a non-successful status code is observed calling the API and
    no expected handling takes place.
    """


class ResourceNotFound(Exception):
    """
    Raised if requesting a node and PRTG says it is not found or it can not be
    located via an ID search
    """


class GlobalArrays(object):
    """
    class used by PRTGApi and children to manage global arrays of all objects
    """
    allprobes = []
    allgroups = []
    alldevices = []
    allsensors = []


class ConnectionMethods(object):
    """
    class used by all prtg_* objects to build urls and query prtg using
    requests
    """
    def __init__(self):
        self.host = None
        self.port = None
        self.user = None
        self.passhash = None
        self.protocol = None
        self.verify = None
        self.confdata = None
        self.base_url = None
        self.base_url_no_api = None
        self.url_auth = None

    def unpack_config(self, confdata):
        """
        Load the connection config from the config pack
        """
        self.host = confdata[0]
        self.port = confdata[1]
        self.user = confdata[2]
        self.passhash = confdata[3]
        self.protocol = confdata[4]
        self.verify = confdata[5]
        self.confdata = confdata
        self.base_url = "{protocol}://{host}:{port}/api/".format(
            protocol=self.protocol, host=self.host, port=self.port
        )
        self.base_url_no_api = "{protocol}://{host}:{port}/".format(
            protocol=self.protocol, host=self.host, port=self.port
        )
        self.url_auth = "username={username}&passhash={passhash}".format(
            username=self.user, passhash=self.passhash
        )

    def get_request(self, url_string, api=True):
        """
        global method for api calls. Provides errors for the 401 and 404
        responses
        """
        if api:
            url = "{base}{content}&{auth}".format(
                base=self.base_url, content=url_string, auth=self.url_auth
            )
        else:
            url = "{base}{content}&{auth}".format(
                base=self.base_url_no_api, content=url_string,
                auth=self.url_auth,
            )
        req = requests.get(url, verify=self.verify)
        if 200 <= req.status_code <= 299:
            return req
        if req.status_code == 401:
            raise (
                AuthenticationError(
                    "PRTG authentication failed."
                    " Check credentials in config file"
                )
            )
        if req.status_code == 404:
            raise (
                ResourceNotFound(
                    "No resource at URL used: {0}".format(url)
                )
            )
        raise UnhandledStatusCode(
            'Response code was {0}: {1}'.format(
                req.status_code, req.text,
            )
        )


class BaseConfig(ConnectionMethods):
    """
    Base class used for common PRTG functionality
    """
    def __init__(self):
        super(BaseConfig, self).__init__()
        self.id = None  # pylint: disable=invalid-name
        self.objid = None
        self.sensorid = None
        self.type = None
        self.name = None
        self.status = None
        self.status_raw = None
        self.active = None
        self.allprobes = GlobalArrays.allprobes
        self.allgroups = GlobalArrays.allgroups
        self.alldevices = GlobalArrays.alldevices
        self.allsensors = GlobalArrays.allsensors

    def __str__(self):
        return "<Name: {name}, ID: {id}, Active: {active}>".format(
            name=self.name, id=self.id, active=self.active
        )

    def __repr__(self):
        return "<Name: {name}, ID: {id}, Active: {active}>".format(
            name=self.name, id=self.id, active=self.active
        )

    def clear_arrays(self):
        """
        Remove cached data
        """
        del self.allprobes[:]
        del self.allgroups[:]
        del self.alldevices[:]
        del self.allsensors[:]

    def delete(self, confirm=True):
        """
        Called to remove this node in the PRTG tree.
        """
        if self.type == "Root":
            return "You cannot delete the root object."
        delete_url = "deleteobject.htm?id={objid}&approve=1".format(
            objid=self.id
        )
        if confirm:
            response = ""
            while response.upper() not in ["Y", "N"]:
                response = safe_input(
                    "Would you like to continue?(Y/[N])  "
                )
                if response == "":
                    response = "N"
            if response.upper() == "Y":
                _ = self.get_request(url_string=delete_url)
        else:
            _ = self.get_request(
                url_string=delete_url
            )
        return ""

    def set_property(self, name, value):
        """
        Used to call the PRTG API to update a property on the node
        """
        if self.type != "Channel":
            setprop_url = (
                "setobjectproperty.htm?id={objid}"
                "&name={propname}&value={propval}".format(
                    objid=self.id, propname=name, propval=value
                )
            )
        else:
            setprop_url = (
                "setobjectproperty.htm?id={objid}&subid={subid}"
                "&name={propname}&value={propval}".format(
                    objid=self.sensorid, subid=self.objid, propname=name,
                    propval=value,
                )
            )
        _ = self.get_request(url_string=setprop_url)
        self.name = value

    def get_property(self, name):
        """
        Used to call the PRTG API to retrieve a property on the node
        """
        if self.type != "Channel":
            getprop_url = (
                "getobjectproperty.htm?id={objid}"
                "&name={propname}&show=text".format(
                    objid=self.id, propname=name
                )
            )
        else:
            getprop_url = (
                "getobjectproperty.htm?id={objid}"
                "&subid={subid}&name={propname}".format(
                    objid=self.sensorid, subid=self.objid, propname=name
                )
            )
        req = self.get_request(url_string=getprop_url)
        soup = BeautifulSoup(req.text, "lxml")
        if soup.result.text != "(Property not found)":
            setattr(self, name, soup.result.text)
            return soup.result.text
        raise (
            ResourceNotFound(
                "No object property of name: {name}".format(name=name)
            )
        )

    def set_interval(self, interval):
        """
        note: you will still need to disable inheritance manually.
        Valid intervals are (seconds): 30, 60, 300, 600, 900, 1800, 3600,
        14400, 21600, 43200, 86400
        """
        self.set_property(name="interval", value=interval)

    def get_tree(self, root=""):
        """
        Gets `sensortree` from prtg. If no `rootid` is provided returns entire
        tree
        """
        tree_url = (
            "table.xml?content=sensortree"
            "&output=xml&id={rootid}".format(
                rootid=root
            )
        )
        req = self.get_request(url_string=tree_url)
        raw_data = req.text
        treesoup = BeautifulSoup(raw_data, "lxml")
        # returns the xml as a beautifulsoup object
        if treesoup.sensortree.nodes:
            return treesoup
        raise ResourceNotFound(
            "No objects at ID: {id}".format(id=root)
        )

    def rename(self, newname):
        """
        Used to call the API to rename an element.
        """
        rename_url = "rename.htm?id={objid}&value={name}".format(
            objid=self.id, name=newname
        )
        _ = self.get_request(url_string=rename_url)
        self.name = newname

    def pause(self, duration=0, message=""):
        """
        Used to pause a check to avoid alerts on this element.
        """
        if duration > 0:
            pause_url = "pauseobjectfor.htm?id={objid}&duration={time}".format(
                objid=self.id, time=str(duration)
            )
        else:
            pause_url = (
                "pause.htm?id={objid}&action=0".format(
                    objid=self.id
                )
            )
        if message:
            pause_url += "&pausemsg={string}".format(string=message)
        _ = self.get_request(url_string=pause_url)
        self.status = "Paused"
        self.active = "false"
        self.status_raw = "7"

    def resume(self):
        """
        Resume a paused node to receive any further alerts.
        """
        resume_url = "pause.htm?id={objid}&action=1".format(objid=self.id)
        _ = self.get_request(url_string=resume_url)
        # these are question marks because we don't know what status is after
        # resume
        self.status = "?"
        self.active = "true"
        self.status_raw = "?"

    def get_status(self, name="status"):
        """
        Retrieve the status of this element.
        """
        status_url = (
            "getobjectstatus.htm?id={objid}"
            "&name={name}&show=text".format(
                objid=self.id, name=name
            )
        )
        req = self.get_request(url_string=status_url)
        soup = BeautifulSoup(req.text, "lxml")
        status = soup.result.text.strip()
        self.status = status
        return status

    def clone(self, newname, newplaceid):
        """
        Creating elements is only possible via cloning them and
        setting their properties.
        """
        clone_url = (
            "duplicateobject.htm?id={objid}"
            "&name={name}&targetid={newparent}".format(
                objid=self.id, name=newname, newparent=newplaceid
            )
        )
        _ = self.get_request(url_string=clone_url)

    def add_tags(self, tags, clear_old=False):
        """
        Convenience method to append to the existing tags property.
        """
        if not isinstance(tags, list):
            raise Exception("Needs tags as type: list")
        if clear_old:
            old_tags = []
        else:
            old_tags = self.get_property("tags").split(" ")
        new_tags = " ".join(old_tags + tags)
        self.set_property(name="tags", value=new_tags)


class PRTGApi(GlobalArrays, BaseConfig):
    """
    Parameters:
    - host: Enter the ip address or `hostname` where PRTG is running
    - port: Enter the tcp port used to connect to prtg. (usually 80 or 443)
    - user: Enter your PRTG username
    - passhash: Enter your PRTG passhash. Can be found in PRTG
                webgui > settings > account settings
    - protocol: Enter the protocol used to connect to PRTG server (http or
                https)
    - rootid: Enter the id of the group/probe that contains all the objects
              you want to manage. Defaults to 0 (gets entire `sensortree`)

    Example:
    host = '192.168.1.1'
    port = '443'
    user = 'prtgadmin'
    passhash = '0000000'
    protocol = 'https'
    rootid = '53'
    prtg = PRTGApi(host,user,passhash,rootid,protocol,port)
    """

    def __init__(self, host, user, passhash, rootid=0, protocol="https",
                 port="443", verify=True):
        super(PRTGApi, self).__init__()
        self.confdata = (host, port, user, passhash, protocol, verify)
        self.unpack_config(self.confdata)
        self.probes = []
        self.groups = []
        self.devices = []
        self.treesoup = None
        self.id = rootid
        self.initialize()

    def initialize(self):
        """
        Called to load the local cache
        """
        self.clear_arrays()
        # get `sensortree` from root id downwards
        self.treesoup = self.get_tree(root=self.id)
        # Finds all the direct child nodes in `sensortree` and creates python
        # objects, passes each object its xml data
        for child in self.treesoup.sensortree.nodes.children:
            if child.name is not None:
                for childr in child.children:
                    if childr.name == "probenode":
                        probeobj = Probe(childr, self.confdata)
                        self.allprobes.append(probeobj)
                        self.probes.append(probeobj)
                    elif childr.name == "device":
                        deviceobj = Device(childr, self.confdata)
                        self.devices.append(deviceobj)
                        self.alldevices.append(deviceobj)
                    elif childr.name == "group":
                        groupobj = Group(childr, self.confdata)
                        self.groups.append(groupobj)
                        self.allgroups.append(groupobj)
                    elif childr.name is not None:
                        if childr.string is None:
                            childr.string = ""
                        setattr(self, childr.name, childr.string)

    def refresh(self, refreshsoup=None):
        """
        Used to supply or obtain and update local cache
        """
        if refreshsoup is None:
            # download fresh `sensortree`
            refreshsoup = self.get_tree(root=self.id)
        self.treesoup = refreshsoup
        probeids = []
        newprobeids = []
        groupids = []
        newgroupids = []
        deviceids = []
        newdeviceids = []
        # get ids of existing probes
        for aprobe in self.probes:
            probeids.append(aprobe.id)
        for agroup in self.groups:
            groupids.append(agroup.id)
        for adevice in self.devices:
            deviceids.append(adevice.id)
        # for all the child objects in `sensortree`, if it already exists
        # refresh the object, otherwise create a new one
        for child in self.treesoup.sensortree.nodes.children:
            if child.name is not None:
                for childr in child.children:
                    if childr.name == "probenode":
                        if childr.find("id").string in probeids:
                            for aprobe in self.probes:
                                if aprobe.id == childr.find("id").string:
                                    aprobe.refresh(childr)
                        else:
                            probeobj = Probe(childr, self.confdata)
                            self.probes.append(probeobj)
                            self.allprobes.append(probeobj)
                        # add all probe ids from the `sensortree` to this list
                        newprobeids.append(childr.find("id").string)
                    elif childr.name == "group":
                        if childr.find("id").string in groupids:
                            for agroup in self.groups:
                                if agroup.id == childr.find("id").string:
                                    agroup.refresh(childr)
                        else:
                            groupobj = Group(childr, self.confdata)
                            self.allgroups.append(groupobj)
                            self.groups.append(groupobj)
                        # add all probe ids from the `sensortree` to this list
                        newgroupids.append(childr.find("id").string)
                    elif childr.name == "device":
                        if childr.find("id").string in deviceids:
                            for adevice in self.devices:
                                if adevice.id == childr.find("id").string:
                                    adevice.refresh(childr)
                        else:
                            deviceobj = Device(childr, self.confdata)
                            self.alldevices.append(deviceobj)
                            self.devices.append(deviceobj)
                        # add all probe ids from the `sensortree` to this list
                        newdeviceids.append(childr.find("id").string)
                    elif childr.name is not None:
                        if childr.string is None:
                            childr.string = ""
                        setattr(self, childr.name, childr.string)
        # if existing probes were not in the new `sensortree`, remove from
        # `allprobes`
        for idval in probeids:
            if idval not in newprobeids:
                for aprobe in self.probes:
                    if aprobe.id == idval:
                        self.allprobes.remove(aprobe)
                        self.probes.remove(aprobe)
        for idval in groupids:
            if idval not in newgroupids:
                for agroup in self.groups:
                    if agroup.id == idval:
                        self.allgroups.remove(agroup)
                        self.groups.remove(agroup)
        for idval in deviceids:
            if idval not in newdeviceids:
                for adevice in self.devices:
                    if adevice.id == idval:
                        self.devices.remove(adevice)
                        self.devices.remove(adevice)

    def search_byid(self, idval):
        """
        Find an element with the specified ID looking in all the cached kinds
        of data.
        """
        idval = str(idval)
        for obj in (self.allprobes + self.allgroups + self.alldevices +
                    self.allsensors):
            if obj.id == idval:
                return obj
        raise ResourceNotFound(
            'Object with ID {0} not found'.format(idval)
        )


class Channel(PRTGApi):
    """
    A channel is a PRTG concept, sensors have a series of channels.
    """
    def __init__(self, channelsoup, sensorid, confdata):
        self.unpack_config(confdata)
        self.sensorid = sensorid
        self.lastvalue = None
        self.id = None
        self.channelsoup = channelsoup
        super(Channel, self).__init__(
            host=self.host, user=self.user, passhash=self.passhash,
            protocol=self.protocol, port=self.port, verify=self.verify,
        )

    def initialize(self):
        """
        Called to load the local cache
        """
        for child in self.channelsoup.children:
            if child.string is None:
                child.string = ""
            if child.name is not None:
                setattr(self, child.name, child.string)
        self.id = self.objid
        if self.lastvalue is not None:
            if self.lastvalue.replace(".", "").isdigit():
                try:
                    self.lastvalue_int = int(
                        self.lastvalue.split(" ")[0].replace(",", "")
                    )
                    self.lastvalue_float = float(self.lastvalue_int)
                except ValueError:
                    self.lastvalue_float = float(
                        self.lastvalue.split(" ")[0].replace(",", "")
                    )
                    self.lastvalue_int = int(self.lastvalue_float)
                self.unit = self.lastvalue.split(" ")[1]
        self.type = "Channel"

    def __str__(self):
        return "<Name: {name}, ID: {id}>".format(name=self.name, id=self.id)

    def __repr__(self):
        return "<Name: {name}, ID: {id}>".format(name=self.name, id=self.id)

    def rename(self, newname):
        self.set_property(name="name", value=newname)
        self.name = newname

    def pause(self, duration=0, message=""):
        print("Channels cannot be paused, pausing parent sensor.")
        if duration > 0:
            pause_url = "pauseobjectfor.htm?id={objid}&duration={time}".format(
                objid=self.sensorid, time=duration
            )
        else:
            pause_url = (
                "pause.htm?id={objid}&action=0&".format(
                    objid=self.sensorid
                )
            )
        if message:
            pause_url += "&pausemsg={string}".format(string=message)
        _ = self.get_request(url_string=pause_url)

    def resume(self):
        print("Channels cannot be resumed, resuming parent sensor.")
        resume_url = (
            "pause.htm?id={objid}&action=1".format(objid=self.sensorid)
        )
        _ = self.get_request(url_string=resume_url)

    def refresh(self, refreshsoup=None):
        """
        Used to supply or obtain and update local cache
        """
        channelsoup = refreshsoup
        for child in channelsoup.children:
            if child.string is None:
                child.string = ""
            if child.name is not None:
                setattr(self, child.name, child.string)
        self.id = self.objid

    def delete(self, confirm=True):
        return "You cannot delete a channel"


class Sensor(PRTGApi):
    """
    Used to monitor a target in PRTG.
    """
    def __init__(self, sensorsoup, deviceid, confdata):
        self.unpack_config(confdata)
        self.channels = []
        self.type = "Sensor"
        self.deviceid = deviceid
        self.filepath = None
        self.sensorsoup = sensorsoup
        super(Sensor, self).__init__(
            host=self.host, user=self.user, passhash=self.passhash,
            protocol=self.protocol, port=self.port, verify=self.verify,
        )

    def initialize(self):
        """
        Called to load the local cache
        """
        for child in self.sensorsoup.children:
            if child.string is None:
                child.string = ""
            if child.name is not None:
                setattr(self, child.name, child.string)
        setattr(self, "attributes", self.sensorsoup.attrs)

    def get_channels(self):
        """
        Get the channels for this sensor.
        """
        channel_url = (
            "table.xml?content=channels&output=xml"
            "&columns=name,lastvalue_,objid&id={sensorid}".format(
                sensorid=self.id
            )
        )
        req = self.get_request(url_string=channel_url)
        channelsoup = BeautifulSoup(req.text, "lxml")
        if not self.channels:
            for child in channelsoup.find_all("item"):
                self.channels.append(Channel(child, self.id, self.confdata))
        else:
            for child in channelsoup.find_all("item"):
                for achannel in self.channels:
                    if achannel.objid == child.find("objid").string:
                        achannel.refresh(child)
        return self.channels

    def refresh(self, refreshsoup=None):
        """
        Used to supply or obtain and update local cache
        """
        sensorsoup = refreshsoup
        if sensorsoup is None:
            soup = self.get_tree(root=self.id)
            sensorsoup = soup.sensortree.nodes.sensor
        for child in sensorsoup.children:
            if child.string is None:
                child.string = ""
            if child.name is not None:
                setattr(self, child.name, child.string)
        setattr(self, "attributes", sensorsoup.attrs)
        if self.channels:
            self.get_channels()

    def set_additional_param(self, parameterstring):
        """
        Set the params property
        """
        self.set_property(name="params", value=parameterstring)

    def acknowledge(self, message=""):
        """
        Used indicate a response to an alarm
        """
        acknowledge_url = (
            "acknowledgealarm.htm?id={objid}"
            "&ackmsg={string}".format(
                objid=self.id, string=message
            )
        )
        _ = self.get_request(url_string=acknowledge_url)
        self.get_status()

    def save_graph(self, graphid, filepath, size, hidden_channels="",
                   filetype="svg"):
        """
        Size options: S,M,L
        """
        if size.upper() == "L":
            width = "1500"
            height = "500"
            font = "13"
        elif size.upper() == "S":
            width = "400"
            height = "300"
            font = "9"
        else:
            width = "800"
            height = "350"
            font = "13"
        if hidden_channels:
            hidden_channels = "&hide={hc}".format(hc=hidden_channels)
        chart_url = (
            "chart.{ft}?type=graph&graphid={gid}&id={sid}&width={w}"
            "&height={h}{hc}&plotcolor=%23ffffff&gridcolor=%23ffffff"
            "&graphstyling=showLegend%3D%271%27"
            "+baseFontSize%3D%27{f}%27".format(
                ft=filetype,
                gid=graphid,
                sid=self.id,
                w=width,
                h=height,
                hc=hidden_channels,
                f=font,
            )
        )
        req = self.get_request(url_string=chart_url, api=False)
        with open(filepath, "wb") as imgfile:
            for chunk in req:
                imgfile.write(chunk)
        self.filepath = filepath


class Device(PRTGApi):
    """
    A physical device that can be monitored by a sensor
    """
    def __init__(self, devicesoup, confdata):
        self.unpack_config(confdata)
        self.sensors = []
        self.devicesoup = devicesoup
        super(Device, self).__init__(
            host=self.host, user=self.user, passhash=self.passhash,
            protocol=self.protocol, port=self.port, verify=self.verify,
        )

    def initialize(self):
        """
        Called to load the local cache
        """
        for child in self.devicesoup.children:
            if child.name == "sensor":
                sensorobj = Sensor(child, self.id, self.confdata)
                self.sensors.append(sensorobj)
                self.allsensors.append(sensorobj)
            elif child.name is not None:
                if child.string is None:
                    child.string = ""
                setattr(self, child.name, child.string)
        # Adds sensors to a dictionary based on their status
        self.sensors_by_status = {
            "Up": [], "Down": [], "Warning": [], "Paused": []
        }
        for asensor in self.sensors:
            if asensor.status in self.sensors_by_status.keys():
                self.sensors_by_status[asensor.status].append(asensor)
            else:
                self.sensors_by_status[asensor.status] = [asensor]
        setattr(self, "attributes", self.devicesoup.attrs)
        self.type = "Device"

    def refresh(self, refreshsoup=None):
        """
        Used to supply or obtain and update local cache
        """
        devicesoup = refreshsoup
        if devicesoup is None:
            soup = self.get_tree(root=self.id)
            devicesoup = soup.sensortree.nodes.device
        sensorids = []
        newsensorids = []
        for asensor in self.sensors:
            sensorids.append(asensor.id)
        for child in devicesoup.children:
            if child.name == "sensor":
                if child.find("id").string in sensorids:
                    for asensor in self.sensors:
                        if asensor.id == child.find("id").string:
                            asensor.refresh(child)
                else:
                    sensorobj = Sensor(child, self.id, self.confdata)
                    self.sensors.append(sensorobj)
                    self.allsensors.append(sensorobj)
                newsensorids.append(child.find("id").string)
            elif child.name is not None:
                if child.string is None:
                    child.string = ""
                setattr(self, child.name, child.string)
        for idval in sensorids:
            if idval not in newsensorids:
                for asensor in self.sensors:
                    if asensor.id == idval:
                        sensortoremove = asensor
                self.sensors.remove(sensortoremove)
                self.allsensors.remove(sensortoremove)
        setattr(self, "attributes", devicesoup.attrs)

    def set_host(self, host):
        """
        Set the host property and update the local cache
        """
        self.set_property(name="host", value=host)
        self.host = host


class Group(PRTGApi):
    """
    A Tree Nesting Feature - Groups can contain other Groups and Devices
    """
    def __init__(self, groupsoup, confdata):
        self.unpack_config(confdata)
        self.groups = []
        self.devices = []
        self.groupsoup = groupsoup
        super(Group, self).__init__(
            host=self.host, user=self.user, passhash=self.passhash,
            protocol=self.protocol, port=self.port, verify=self.verify,
        )

    def initialize(self):
        """
        Called to load the local cache
        """
        # `groupsoup` is passed into `__init__` method
        # The children objects are either added to this object as an attribute
        # or a device/group object is created
        for child in self.groupsoup.children:
            if child.name == "device":
                deviceobj = Device(child, self.confdata)
                self.devices.append(deviceobj)
                self.alldevices.append(deviceobj)
            elif child.name == "group":
                groupobj = Group(child, self.confdata)
                self.groups.append(groupobj)
                self.allgroups.append(groupobj)
            elif child.name is not None:
                if child.string is None:
                    child.string = ""
                setattr(self, child.name, child.string)
        setattr(self, "attributes", self.groupsoup.attrs)
        self.type = "Group"

    def refresh(self, refreshsoup=None):
        """
        Used to supply or obtain and update local cache
        """
        groupsoup = refreshsoup
        if groupsoup is None:
            if self.type == "Group":
                soup = self.get_tree(root=self.id)
                groupsoup = soup.sensortree.nodes.group
            elif self.type == "Probe":
                soup = self.get_tree(root=self.id)
                groupsoup = soup.sensortree.nodes.probenode
        deviceids = []
        newdeviceids = []
        for adevice in self.devices:
            deviceids.append(adevice.id)
        groupids = []
        newgroupids = []
        for agroup in self.groups:
            groupids.append(agroup.id)
        for child in groupsoup.children:
            if child.name == "device":
                if child.find("id").string in deviceids:
                    for adevice in self.devices:
                        if adevice.id == child.find("id").string:
                            adevice.refresh(child)
                else:
                    deviceobj = Device(child, self.confdata)
                    self.devices.append(deviceobj)
                    self.alldevices.append(deviceobj)
                newdeviceids.append(child.find("id").string)
            elif child.name == "group":
                if child.find("id").string in groupids:
                    for agroup in self.groups:
                        if agroup.id == child.find("id").string:
                            agroup.refresh(child)
                else:
                    groupobj = Group(child, self.confdata)
                    self.groups.append(groupobj)
                    self.allgroups.append(groupobj)
                newgroupids.append(child.find("id").string)
            elif child.name is not None:
                if child.string is None:
                    child.string = ""
                setattr(self, child.name, child.string)
        for idval in deviceids:
            if idval not in newdeviceids:
                for adevice in self.devices:
                    if adevice.id == idval:
                        devicetoremove = adevice
                self.devices.remove(devicetoremove)
                self.alldevices.remove(devicetoremove)
        for idval in groupids:
            if idval not in newgroupids:
                for agroup in self.groups:
                    if agroup.id == idval:
                        grouptoremove = agroup
                self.groups.remove(grouptoremove)
                self.allgroups.remove(grouptoremove)
        setattr(self, "attributes", groupsoup.attrs)


class Probe(Group):
    """
    Probe is the same as group so it inherits all methods and attributes except
    type
    """
    type = "Probe"


class PRTGDevice(BaseConfig):
    """
    Separate top level object to manage just a device and its sensors instead
    of downloading details for an entire group
    """

    def __init__(self, host, user, passhash, deviceid, protocol="https",
                 port="443", verify=True):
        self.confdata = (host, port, user, passhash, protocol, verify)
        self.unpack_config(self.confdata)
        self.sensors = []
        self.sensors_by_status = {
            "Up": [], "Down": [], "Warning": [], "Paused": []
        }
        self.deviceid = deviceid
        super(PRTGDevice, self).__init__(
            host=self.host, user=self.user, passhash=self.passhash,
            protocol=self.protocol, port=self.port, verify=self.verify,
        )

    def initialize(self):
        """
        Called to load the local cache
        """
        soup = self.get_tree(root=self.deviceid)
        for child in soup.sensortree.nodes.device:
            if child.name == "sensor":
                sensorobj = Sensor(child, self.id, self.confdata)
                self.sensors.append(sensorobj)
            elif child.name is not None:
                if child.string is None:
                    child.string = ""
                setattr(self, child.name, child.string)
        for asensor in self.sensors:
            if asensor.status in self.sensors_by_status.keys():
                self.sensors_by_status[asensor.status].append(asensor)
            else:
                self.sensors_by_status[asensor.status] = [asensor]

    def refresh(self, refreshsoup=None):
        """
        Used to supply or obtain and update local cache
        """
        soup = refreshsoup
        if soup is None:
            soup = self.get_tree(root=self.deviceid)
        sensorids = []
        for asensor in self.sensors:
            sensorids.append(asensor.id)
        for child in soup.sensortree.nodes.device:
            if child.name == "sensor":
                if child.find("id").string in sensorids:
                    for asensor in self.sensors:
                        if asensor.id == child.find("id").string:
                            asensor.refresh(child)
                else:
                    sensorobj = Sensor(child, self.id, self.confdata)
                    self.sensors.append(sensorobj)
            elif child.name is not None:
                if child.string is None:
                    child.string = ""
                setattr(self, child.name, child.string)


class PRTGSensor(BaseConfig):
    """Separate top level object to manage just a sensor and its channels
    instead of downloading details for an entire group"""

    def __init__(self, host, user, passhash, sensorid, protocol="https",
                 port="443", verify=True):
        self.confdata = (host, port, user, passhash, protocol, verify)
        self.unpack_config(self.confdata)
        self.channels = []
        self.sensorid = sensorid
        self.filepath = None
        super(PRTGSensor, self).__init__()

    def initialize(self):
        """
        Called to load the local cache
        """
        soup = self.get_tree(root=self.sensorid)
        for child in soup.sensortree.nodes.sensor:
            if child.name is not None:
                if child.string is None:
                    child.string = ""
                setattr(self, child.name, child.string)
        self.get_channels()

    def refresh(self, refreshsoup=None):
        """
        Used to supply or obtain and update local cache
        """
        soup = refreshsoup
        if soup is None:
            soup = self.get_tree(root=self.id)
        sensorsoup = soup.sensortree.nodes.sensor
        for child in sensorsoup.children:
            if child.string is None:
                child.string = ""
            if child.name is not None:
                setattr(self, child.name, child.string)
        setattr(self, "attributes", sensorsoup.attrs)
        self.get_channels()

    def get_channels(self):
        """
        Lookup the channels the sensor has.
        """
        channel_url = (
            "table.xml?content=channels&output=xml"
            "&columns=name,lastvalue_,objid&id={sensorid}".format(
                sensorid=self.id
            )
        )
        req = self.get_request(url_string=channel_url)
        channelsoup = BeautifulSoup(req.text, "lxml")
        if not self.channels:
            for child in channelsoup.find_all("item"):
                self.channels.append(Channel(child, self.id, self.confdata))
        else:
            for child in channelsoup.find_all("item"):
                for achannel in self.channels:
                    if achannel.objid == child.find("objid").string:
                        achannel.refresh(child)

    def acknowledge(self, message=""):
        """
        Used to indicate a response to a sensor being investigated.
        """
        acknowledge_url = (
            "acknowledgealarm.htm?id={objid}"
            "&ackmsg={string}".format(
                objid=self.id, string=message
            )
        )
        _ = self.get_request(url_string=acknowledge_url)

    def save_graph(self, graphid, filepath, size, hidden_channels="",
                   filetype="svg"):
        """
        Size options: S,M,L
        """
        if size.upper() == "L":
            width = "1500"
            height = "500"
            font = "13"
        elif size.upper() == "S":
            width = "400"
            height = "300"
            font = "9"
        else:
            width = "800"
            height = "350"
            font = "13"
        if hidden_channels:
            hidden_channels = "&hide={hc}".format(hc=hidden_channels)
        chart_url = (
            "chart.{ft}?type=graph&graphid={gid}&id={sid}"
            "&width={w}&height={h}{hc}&plotcolor=%23ffffff"
            "&gridcolor=%23ffffff&graphstyling=showLegend"
            "%3D%271%27+baseFontSize%3D%27{f}%27".format(
                ft=filetype,
                gid=graphid,
                sid=self.id,
                w=width,
                h=height,
                hc=hidden_channels,
                f=font,
            )
        )
        req = self.get_request(url_string=chart_url, api=False)
        with open(filepath, "wb") as imgfile:
            for chunk in req:
                imgfile.write(chunk)
        self.filepath = filepath


class PRTGHistoricData(ConnectionMethods):
    """class used for calls to the historic data api.
    Call the class first using connection params then use
    methods to get/process data. yyyy-mm-dd-hh-mm-ss"""

    def __init__(self, host, port, user, passhash, protocol, verify=True):
        self.confdata = (host, port, user, passhash, protocol, verify)
        self.unpack_config(self.confdata)
        super(PRTGHistoricData, self).__init__(
            host=self.host, user=self.user, passhash=self.passhash,
            protocol=self.protocol, port=self.port, verify=self.verify,
        )

    @staticmethod
    def format_date(dateobj):
        """Pass a datetime object and this will format appropriately
        for use with the historic data api"""
        return dateobj.strftime("%Y-%m-%d-%H-%M-%S")

    def get_historic_data(self, objid, startdate, enddate, timeaverage):
        """
        Call PRTG API to load historic data
        """
        if isinstance(startdate, datetime):
            startdate = self.format_date(startdate)
        if isinstance(enddate, datetime):
            enddate = self.format_date(enddate)
        historic_url = (
            "historicdata.csv?id={id}&avg={avg}"
            "&sdate={sdate}&edate={edate}".format(
                id=objid, avg=timeaverage, sdate=startdate, edate=enddate
            )
        )
        req = self.get_request(url_string=historic_url)
        csv_raw = req.text
        csv_lines = (csv_raw.split("\n"))[:-2]
        csv_reader = csv.reader(csv_lines)
        data = {}
        for ind, row in enumerate(csv_reader):
            if ind == 0:
                headers = row
                for header in headers:
                    data[header] = []
            else:
                for inde, cell in enumerate(row):
                    if headers[inde] == "Date Time":
                        if "-" in cell:
                            cell = cell[: cell.index(" -")]
                        data[headers[inde]].append(
                            datetime.strptime(cell, "%m/%d/%Y %I:%M:%S %p")
                        )
                    else:
                        data[headers[inde]].append(cell)
        return data
