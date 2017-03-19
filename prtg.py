import os
import requests
from bs4 import BeautifulSoup
from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

class baseconfig(object):
	def set_config(self,host,port,user,passhash,protocol):
		self.confdata = (host,port,user,passhash,protocol)
	def unpack_config(self,confdata):
		self.host = confdata[0]
		self.port = confdata[1]
		self.user = confdata[2]
		self.passhash = confdata[3]
		self.protocol = confdata[4]
		self.confdata = confdata
		self.base_url = "{protocol}://{host}:{port}/api/".format(protocol=self.protocol,host=self.host,port=self.port)
		self.url_auth = "username={username}&passhash={passhash}".format(username=self.user,passhash=self.passhash)
	#define global arrays, inherited to all objects
	allprobes = []
	allgroups = []
	alldevices = []
	allsensors = []
		
class prtg_api(baseconfig):
	def __init__(self,host,port,user,passhash,protocol,rootid=0):
		self.confdata = (host,port,user,passhash,protocol)
		self.unpack_config(self.confdata)
		self.probes = []
		self.groups = []
		self.devices = []
		#get sensortree from root id downwards
		self.treesoup = self.get_tree(root=rootid)
		#Finds all the direct child nodes in sensortree and creates python objects, passes each object its xml data
		for child in self.treesoup.sensortree.nodes.children:
			if child.name is not None:
				for childr in child.children:
					if childr.name == "probenode":
						probeobj = probe(childr,self.confdata)
						self.allprobes.append(probeobj)
						self.probes.append(probeobj)
					elif childr.name == "device":
						deviceobj = device(childr,self.confdata)
						self.devices.append(deviceobj)
						self.alldevices.append(deviceobj)
					elif childr.name == "group":
						groupobj = group(childr,self.confdata)
						self.groups.append(groupobj)
						self.allgroups.append(groupobj)
					elif childr.name is not None:
						if childr.string is None:
							childr.string = ""
						setattr(self,childr.name,childr.string)
	#str and repr allow the object id to show when viewing in arrays or printing
	def __str__(self):
		return(self.id)
	def __repr__(self):
		return(self.id)
	def get_tree(self,root=''):
		#gets sensortree from prtg. If no rootid is provided returns entire tree
		tree_url = "table.xml?content=sensortree&output=xml&id={rootid}".format(rootid=root)
		req = self.get_request(url_string=tree_url)
		raw_data = req.text
		treesoup = BeautifulSoup(raw_data,"lxml")
		#returns the xml as a beautifulsoup object
		return(treesoup)
	def get_request(self,url_string):
		#global method for api calls. Provides errors for the 401 and 404 responses
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
		#these are question marks because we don't know what status is after resume
		self.status = "?"
		self.active = "true"
		self.status_raw = "?"
	def clone(self,newname,newplaceid):
		clone_url = "duplicateobject.htm?id={objid}&name={name}&targetid={newparent}".format(objid=self.id,name=newname,newparent=newplaceid)
		req = self.get_request(url_string=clone_url)
	def refresh(self):
		#download fresh sensortree
		self.treesoup = self.get_tree()
		probeids = []
		newprobeids = []
		#get ids of existing probes
		for aprobe in self.allprobes:
			probeids.append(aprobe.id)
		#for all the probes in sensortree, if it already exists refresh the object, otherwise create a new one	
		for child in self.treesoup.find_all("probenode"):
			if child.find("id").string in probeids:
				for aprobe in self.allprobes:
					if aprobe.id == child.find("id").string:
						aprobe.refresh(child)
			else:
				probeobj = probe(child,self.confdata)
				self.allprobes.append(probeobj)
			#add all probe ids from the sensortree to this list
			newprobeids.append(child.find("id").string)
		#if existing probes were not in the new sensortree, remove from allprobes
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
				response = ""
				while response.upper() not in ["Y","N"]:
					response = str(input("Would you like to continue?(Y/[N])  "))
					if response == "":
						response = "N"
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
	def set_interval(self,interval):
		'''note: you will still need to disable inheritance manually.
		Valid intervals are (seconds): 30, 60, 300, 600, 900, 1800, 3600, 14400, 21600, 43200, 86400'''
		self.set_property(name="interval",value=interval)
				
class channel(prtg_api):
	def __init__(self,channelsoup,sensorid,confdata):
		self.unpack_config(confdata)
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
	def __init__(self,sensorsoup,deviceid,confdata):
		self.unpack_config(confdata)
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
				self.channels.append(channel(child,self.id,self.confdata))
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
	def set_additional_param(self,parameterstring):
		self.set_property(name="params",value=parameterstring)

class device(prtg_api):
	def __init__(self,devicesoup,confdata):
		self.unpack_config(confdata)
		self.sensors = []
		for child in devicesoup.children:
			if child.name == "sensor":
				sensorobj = sensor(child,self.id,self.confdata)
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
					sensorobj = sensor(child,self.id,self.confdata)
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
	def set_host(self,host):
		self.set_property(name="host",value=host)
		self.host = host

class group(prtg_api):
	def __init__(self,groupsoup,confdata):
		self.unpack_config(confdata)
		self.groups = []
		self.devices = []
		#groupsoup is passed into __init__ method
		#The children objects are either added to this object as an attribute
		#or a device/group object is created
		for child in groupsoup.children:
			if child.name == "device":
				deviceobj = device(child,self.confdata)
				self.devices.append(deviceobj)
				self.alldevices.append(deviceobj)
			elif child.name == "group":
				groupobj = group(child,self.confdata)
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
					deviceobj = device(child,self.confdata)
					self.devices.append(deviceobj)
					self.alldevices.append(deviceobj)
				newdeviceids.append(child.find("id").string)
			elif child.name == "group":
				if child.find("id").string in groupids:
					for agroup in self.groups:
						if agroup.id == child.find("id").string:
							agroup.refresh(child)
				else:
					groupobj = group(child,self.confdata)
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
			
#probe is the same as group so it inherits all methods and attributes except type				
class probe(group):		
	type = "Probe"
			
class AuthenticationError(Exception):
	pass

class ResourceNotFound(Exception):
	pass
