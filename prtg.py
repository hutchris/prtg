import os
import yaml
import requests
from bs4 import BeautifulSoup
from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

class baseconfig(object):
	def __init__(self):
		directory = os.path.dirname(os.path.abspath(__file__))
		with open(os.path.join(directory,"config.yml"), 'r') as ymlfile:
			cfg = yaml.load(ymlfile)
		self.protocol = cfg['protocol']
		self.port = cfg['port']
		self.prtg_host = cfg['prtg_host']
		self.prtg_user = cfg['prtg_user']
		self.prtg_hash = cfg['prtg_hash']
		self.port = ":{0}".format(self.port)
		self.base_url = "{protocol}://{host}{port}/api/".format(protocol=self.protocol,host=self.prtg_host,port=self.port)
		self.url_auth = "username={username}&passhash={passhash}".format(username=self.prtg_user,passhash=self.prtg_hash)
	allprobes = []
	allgroups = []
	alldevices = []
	allsensors = []
		
class prtg_api(baseconfig):
	def __init__(self):
		baseconfig.__init__(self)
		self.treesoup = self.get_tree()
		for child in self.treesoup.find_all("probenode"):
			probeobj = probe(child)
			self.allprobes.append(probeobj)
		self.name = "Root"
		self.id = "0"
		self.status_raw = self.treesoup.group.status_raw.string
		self.active = self.treesoup.group.active.string
		self.type = "Root"
	def __str__(self):
		return(self.id)
	def __repr__(self):
		return(self.id)
	def get_tree(self,root=''):
		if len(str(root)) > 0:
			tree_url = "table.xml?content=sensortree&output=xml&id={rootid}".format(rootid=root)
		else:
			tree_url = "table.xml?content=sensortree&output=xml"
		req = self.get_request(url_string=tree_url)
		raw_data = req.text
		treesoup = BeautifulSoup(raw_data,"lxml")
		return(treesoup)
	def get_request(self,url_string):
		url = "{base}{content}&{auth}".format(base=self.base_url,content=url_string,auth=self.url_auth)
		req = requests.get(url,verify=False)
		if req.status_code == 200:
			return(req)
		elif req.status_code == 401:
			raise(AuthenticationError("PRTG authentication failed. Check credentials in config file"))
		elif req.status_code == 404:
			raise(ResourceNotFound("No resource at URL used: {0}".format(tree_url)))
	def rename(self,newname):
		rename_url = "rename.htm?id={objid}&value={name}".format(objid=self.id,name=newname)
		req = self.get_request(url_string=rename_url)
		self.name = newname
	def pause(self,duration=0,message=""):
		if duration > 0:
			pause_url = "pauseobjectfor.htm?id={objid}&duration={time}".format(objid=self.id,time=str(duration))
		else:
			pause_url = "pause.htm?id={objid}&action=0".format(objid=self.id)
		if message:
			pause_url += "&pausemsg={string}".format(string=message)
		req = self.get_request(url_string=pause_url)
		self.status = "Paused"
		self.active = "false"
		self.status_raw = "7"
	def resume(self):
		resume_url = "pause.htm?id={objid}&action=1".format(objid=self.id)
		req = self.get_request(url_string=resume_url)
		self.status = "?"
		self.active = "true"
		self.status_raw = "?"
	def clone(self,newname,newplaceid):
		clone_url = "duplicateobject.htm?id={objid}&name={name}&targetid={newparent}".format(objid=self.id,name=newname,newparent=newplaceid)
		req = self.get_request(url_string=clone_url)
	def refresh(self):
		self.treesoup = self.get_tree()
		probeids = []
		newprobeids = []
		for aprobe in self.allprobes:
			probeids.append(aprobe.id)
		for child in self.treesoup.find_all("probenode"):
			if child.find("id").string in probeids:
				for aprobe in self.allprobes:
					if aprobe.id == child.find("id").string:
						aprobe.refresh()
			else:
				probeobj = probe(child)
				self.allprobes.append(probeobj)
			newprobeids.append(child.find("id").string)
		for id in probeids:
			if id not in newprobeids:
				for aprobe in self.allprobes:
					if aprobe.id == id:
						self.allprobes.remove(aprobe)
	def delete(self,confirm=True):
		if self.type == "Root":
			return("You cannot delete the root object.")
		else:
			delete_url = "deleteobject.htm?id={objid}&approve=1}".format(objid=self.id)
			if confirm:
				response = str(input("Would you like to continue?(Y/[N])  "))
				while response.upper() not in ["Y","N"]:
					response = str(input("Would you like to continue?(Y/[N])  "))
				if response.upper() == "Y":
					req = self.get_request(url_string=delete_url)
			else:
				req = self.get_request(url_string=delete_url)
	def set_property(self,name,value):
		if self.type != "Channel":
			setprop_url = "setobjectproperty.htm?id={objid}&name={propname}&value={propval}".format(objid=self.id,propname=name,propval=value)
		else:
			setprop_url = "setobjectproperty.htm?id={objid}&subid={subid}&name={propname}&value={propval}".format(objid=self.sensorid,subid=self.objid,propname=name,propval=value)
		req = self.get_request(url_string=setprop_url)
				
class channel(prtg_api):
	def __init__(self,channelsoup,sensorid):
		baseconfig.__init__(self)
		self.sensorid = sensorid
		for child in channelsoup.children:
			if child.string is None:
				child.string = ""
			if child.name is not None:
				setattr(self,child.name,child.string)
		self.id = self.objid
		self.type = "Channel"
	def rename(self,newname):
		self.set_property(name="name",value=newname)
		self.name = newname
	def pause(self,duration=0,message=""):
		print("Channels cannot be paused, pausing parent sensor.")
		if duration > 0:
			pause_url = "pauseobjectfor.htm?id={objid}&duration={time}".format(objid=self.sensorid,time=duration)
		else:
			pause_url = "pause.htm?id={objid}&action=0&".format(objid=self.sensorid)
		if message:
			pause_url += "&pausemsg={string}".format(string=message)
		req = self.get_request(url_string=pause_url)
	def resume(self):
		print("Channels cannot be resumed, resuming parent sensor.")
		resume_url = "pause.htm?id={objid}&action=1".format(objid=self.sensorid)
		req = self.get_request(url_string=resume_url)
	def refresh(self,channelsoup):
		for child in channelsoup.children:
			if child.string is None:
				child.string = ""
			if child.name is not None:
				setattr(self,child.name,child.string)
		self.id = self.objid
	def delete(self):
		return("You cannot delete a channel")

class sensor(prtg_api):
	def __init__(self,sensorsoup,deviceid):
		baseconfig.__init__(self)
		for child in sensorsoup.children:
			if child.string is None:
				child.string = ""
			if child.name is not None:
				setattr(self,child.name,child.string)
		setattr(self,"attributes",sensorsoup.attrs)
		self.channels = []
		self.type = "Sensor"
		self.deviceid = deviceid
	def get_channels(self):
		channel_url = "table.xml?content=channels&output=xml&columns=name,lastvalue_,objid&id={sensorid}".format(sensorid=self.id)
		req = self.get_request(url_string=channel_url)
		channelsoup = BeautifulSoup(req.text,"lxml")
		if len(self.channels) == 0:
			for child in channelsoup.find_all("item"):
				self.channels.append(channel(child,self.id))
		else:
			for child in channelsoup.find_all("item"):
				for achannel in self.channels:
					if achannel.objid == child.find("objid").string:
						achannel.refresh(child)
	def refresh(self,sensorsoup=None):
		if sensorsoup is None:
			soup = self.get_tree(root=self.id)
			sensorsoup = soup.sensortree.nodes.sensor
		for child in sensorsoup.children:
			if child.string is None:
				child.string = ""
			if child.name is not None:
				setattr(self,child.name,child.string)
		setattr(self,"attributes",sensorsoup.attrs)
		if len(self.channels) > 0:
			self.get_channels()

class device(prtg_api):
	def __init__(self,devicesoup):
		baseconfig.__init__(self)
		self.sensors = []
		for child in devicesoup.children:
			if child.name == "sensor":
				sensorobj = sensor(child,self.id)
				self.sensors.append(sensorobj)
				self.allsensors.append(sensorobj)
			elif child.name is not None:
				if child.string is None:
					child.string = ""
				setattr(self,child.name,child.string)
		setattr(self,"attributes",devicesoup.attrs)
		self.type = "Device"
	def refresh(self,devicesoup=None):
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
					sensorobj = sensor(child,self.id)
					self.sensors.append(sensorobj)
					self.allsensors.append(sensorobj)
				newsensorids.append(child.find("id").string)
			elif child.name is not None:
				if child.string is None:
					child.string = ""
				setattr(self,child.name,child.string)
		for id in sensorids:
			if id not in newsensorids:
				for asensor in self.sensors:
					if asensor.id == id:
						sensortoremove = asensor
				self.sensors.remove(sensortoremove)
				self.allsensors.remove(sensortoremove)
		setattr(self,"attributes",devicesoup.attrs)

class group(prtg_api):
	def __init__(self,groupsoup):
		baseconfig.__init__(self)
		self.groups = []
		self.devices = []
		for child in groupsoup.children:
			if child.name == "device":
				deviceobj = device(child)
				self.devices.append(deviceobj)
				self.alldevices.append(deviceobj)
			elif child.name == "group":
				groupobj = group(child)
				self.groups.append(groupobj)
				self.allgroups.append(groupobj)				
			elif child.name is not None:
				if child.string is None:
					child.string = ""
				setattr(self,child.name,child.string)
		setattr(self,"attributes",groupsoup.attrs)
		self.type = "Group"
	def refresh(self,groupsoup=None):
		if groupsoup is None:
			soup = self.get_tree(root=self.id)
			groupsoup = soup.sensortree.nodes.group
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
					deviceobj = device(child)
					self.devices.append(deviceobj)
					self.alldevices.append(deviceobj)
				newdeviceids.append(child.find("id").string)
			elif child.name == "group":
				if child.find("id").string in groupids:
					for agroup in self.groups:
						if agroup.id == child.find("id").string:
							agroup.refresh(child)
				else:
					groupobj = group(child)
					self.groups.append(groupobj)
					self.allgroups.append(groupobj)
				newgroupids.append(child.find("id").string)
			elif child.name is not None:
				if child.string is None:
					child.string = ""
				setattr(self,child.name,child.string)
		for id in deviceids:
			if id not in newdeviceids:
				for adevice in self.devices:
					if adevice.id == id:
						devicetoremove = adevice
				self.devices.remove(devicetoremove)
				self.alldevices.remove(devicetoremove)
		for id in groupids:
			if id not in newgroupids:
				for agroup in self.groups:
					if agroup.id == id:
						grouptoremove = agroup
				self.groups.remove(grouptoremove)
				self.allgroups.remove(grouptoremove)
		setattr(self,"attributes",groupsoup.attrs)
			
				
class probe(group):		
	def __init__(self,groupsoup):
		group.__init__(self,groupsoup)
		self.type = "Probe"
			
class AuthenticationError(Exception):
	pass

class ResourceNotFound(Exception):
	pass
