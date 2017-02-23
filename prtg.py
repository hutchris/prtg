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
		if (self.protocol == "https" and self.port == "443") or (self.protocol == "http" and self.port == "80"):
			self.port == ""
		else:
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
	def get_tree(self,root=''):
		if len(root) > 0:
			tree_url = "{base}table.xml?content=sensortree&output=xml&id={rootid}&{auth}".format(base=self.base_url,rootid=root,auth=self.url_auth)
		else:
			tree_url = "{base}table.xml?content=sensortree&output=xml&{auth}".format(base=self.base_url,auth=self.url_auth)
		req = requests.get(tree_url,verify=False)
		if req.status_code == 401:
			raise(AuthenticationError("PRTG authentication failed. Check credentials in config file"))
		elif req.status_code == 404:
			raise(ResourceNotFound("No resource at URL used: {0}".format(tree_url)))
		raw_data = req.text
		treesoup = BeautifulSoup(raw_data,"lxml")
		return(treesoup)
	def rename(self,newname):
		rename_url = "{base}rename.htm?id={objid}&value={name}&{auth}".format(base=self.base_url,auth=self.url_auth,objid=self.id,name=newname)
		req = requests.get(rename_url,verify=False)
		if "OK" in req.text:
			self.name = newname
		else:
			print("Unexpected response: {response}".format(response=req.text))
	def pause(self,duration=0,message=""):
		if duration > 0:
			pause_url = "{base}pauseobjectfor.htm?id={objid}&duration={time}&{auth}".format(base=self.base_url,objid=self.id,time=duration,auth=self.url_auth)
		else:
			pause_url = "{base}pause.htm?id={objid}&action=0&{auth}".format(base=self.base_url,objid=self.id,auth=self.url_auth)
		if message:
			pause_url += "&pausemsg={string}".format(string=message)
		req = requests.get(pause_url,verify=False)
		self.status = "Paused"
		self.active = "false"
		self.status_raw = "7"
	def resume(self):
		resume_url = "{base}pause.htm?id={objid}&action=1&{auth}".format(base=self.base_url,objid=self.id,auth=self.url_auth)
		req = requests.get(resume_url,verify=False)
		self.status = "?"
		self.active = "true"
		self.status_raw = "?"
	def clone(self,newname,newplaceid):
		clone_url = "{base}duplicateobject.htm?id={objid}&name={name}&targetid={newparent}&{auth}".format(base=self.base_url,objid=self.id,name=newname,newparent=newplaceid,auth=self.url_auth)
		req = requests.get(clone_url,verify=False)
	def refresh(self):
		self.treesoup = self.get_tree()
		probeids = []
		newprobeids = []
		for probe in self.allprobes:
			probeids.append(probe.id)
		for child in self.treesoup.find_all("probenode"):
			if child.find("id").string in probeids:
				for probe in self.allprobes:
					if probe.id == child.find("id").string:
						probe.refresh()
			else:
				probeobj = probe(child)
				self.allprobes.append(probeobj)
			newprobeids.append(child.find("id").string)
		for id in probeids:
			if id not in newprobeids:
				for probe in self.allprobes:
					if probe.id == id:
						self.allprobes.remove(probe)
	def delete(self,confirm=True):
		if self.id == "0":
			return("You cannot delete the root object.")
		else:
			delete_url = "{base}deleteobject.htm?id={objid}&approve=1{auth}".format(base=self.base_url,objid=self.id,auth=self.url_auth)
			if confirm:
				response = str(input("Would you like to continue?(Y/[N])  "))
				while response.upper() not in ["Y","N"]:
					response = str(input("Would you like to continue?(Y/[N])  "))
				if response.upper() == "Y":
					req = requests.get(delete_url,verify=False)
				
class channel(prtg_api):
	def __init__(self,channelsoup,sensorid):
		baseconfig.__init__(self)
		self.sensorid = sensorid
		for child in channelsoup.children:
			if child.string is None:
				child.string = ""
			if child.name is not None:
				setattr(self,child.name,child.string)
	def rename(self,newname):
		rename_url = "{base}setobjectproperty.htm?id={sensorid}&subid={channelid}&subtype=channel&name=name&value={name}&{auth}".format(base=self.base_url,sensorid=self.sensorid,channelid=self.objid,auth=self.url_auth)
		req = requests.get(rename_url,verify=False)
		if "OK" in req.text:
			self.name = newname
		else:
			print("Unexpected response: {response}".format(response=req.text))
	def pause(self,duration=0,message=""):
		print("Channels cannot be paused, pausing parent sensor.")
		if duration > 0:
			pause_url = "{base}pauseobjectfor.htm?id={objid}&duration={time}&{auth}".format(base=self.base_url,objid=self.sensorid,time=duration,auth=self.url_auth)
		else:
			pause_url = "{base}pause.htm?id={objid}&action=0&{auth}".format(base=self.base_url,objid=self.sensorid,auth=self.url_auth)
		if message:
			pause_url += "&pausemsg={string}".format(string=message)
		req = requests.get(pause_url,verify=False)
	def resume(self):
		print("Channels cannot be resumed, resuming parent sensor.")
		resume_url = "{base}pause.htm?id={objid}&action=1&{auth}".format(base=self.base_url,objid=self.sensorid,auth=self.url_auth)
		req = requests.get(resume_url,verify=False)

class sensor(prtg_api):
	def __init__(self,sensorsoup):
		baseconfig.__init__(self)
		for child in sensorsoup.children:
			if child.string is None:
				child.string = ""
			if child.name is not None:
				setattr(self,child.name,child.string)
		setattr(self,"attributes",sensorsoup.attrs)
		self.channels = []
	def get_channels(self):
		channel_url = "{base}table.xml?content=channels&output=xml&columns=name,lastvalue_,objid&id={sensorid}&{auth}".format(base=self.base_url,sensorid=self.id,auth=self.url_auth)
		req = requests.get(channel_url,verify=False)
		channelsoup = BeautifulSoup(req.text,"lxml")
		for child in channelsoup.find_all("item"):
			self.channels.append(channel(child,self.id))
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
				sensorobj = sensor(child)
				self.sensors.append(sensorobj)
				self.allsensors.append(sensorobj)
			elif child.name is not None:
				if child.string is None:
					child.string = ""
				setattr(self,child.name,child.string)
		setattr(self,"attributes",devicesoup.attrs)
	def refresh(self,devicesoup=None):
		if devicesoup is None:
			soup = self.get_tree(root=self.id)
			devicesoup = soup.sensortree.nodes.device
		sensorids = []
		newsensorids = []
		for sensor in self.sensors:
			sensorids.append(sensor.id)
		for child in devicesoup.children:
			if child.name == "sensor":
				if child.find("id").string in sensorids:
					for sensor in self.sensors:
						if sensor.id == child.find("id").string:
							sensor.refresh(child)
				else:
					sensorobj = sensor(child)
					self.sensors.append(sensorobj)
					self.allsensors.append(sensorobj)
				newsensorids.append(child.find("id").string)
			elif child.name is not None:
				if child.string is None:
					child.string = ""
				setattr(self,child.name,child.string)
		for id in sensorids:
			if id not in newsensorids:
				for sensor in self.sensors:
					if sensor.id == id:
						sensortoremove = sensor
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
	def refresh(self,groupsoup=None):
		if groupsoup is None:
			soup = self.get_tree(root=self.id)
			groupsoup = soup.sensortree.nodes.group
		deviceids = []
		newdeviceids = []
		for device in self.devices:
			deviceids.append(device.id)
		groupids = []
		newgroupids = []
		for group in self.groups:
			groupids.append(group.id)
		for device in self.devices:
			deviceids.append(device.id)
		for group in self.groups:
			groupids.append(group.id)
		for child in groupsoup.children:
			if child.name == "device":
				if child.find("id").string in deviceids:
					for device in self.devices:
						if device.id == child.find("id").string:
							device.refresh(child)
				else:
					deviceobj = device(child)
					self.devices.append(deviceobj)
					self.alldevices.append(deviceobj)
				newdeviceids.append(child.find("id"))
			elif child.name == "group":
				if child.find("id").string in groupids:
					for group in self.groups:
						if group.id == child.find("id").string:
							group.refresh(child)
				else:
					groupobj = group(child)
					self.groups.append(groupobj)
					self.allgroups.append(groupobj)
				newgroupids.append(child.find("id"))
			elif child.name is not None:
				if child.string is None:
					child.string = ""
				setattr(self,child.name,child.string)
		for id in deviceids:
			if id not in newdeviceids:
				for device in self.devices:
					if device.id == id:
						devicetoremove = device
				self.devices.remove(devicetoremove)
				self.alldevices.remove(devicetoremove)
		for id in groupids:
			if id not in newgroupids:
				for group in self.groups:
					if group.id == id:
						grouptoremove = group
				self.groups.remove(grouptoremove)
				self.allgroups.remove(grouptoremove)
		setattr(self,"attributes",groupsoup.attrs)
			
				
class probe(group):		
	pass
			
class AuthenticationError(Exception):
	pass

class ResourceNotFound(Exception):
	pass
