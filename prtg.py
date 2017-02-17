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
		self.prtg_host = cfg['prtg_host']
		self.prtg_user = cfg['prtg_user']
		self.prtg_hash = cfg['prtg_hash']
		self.include_channels = cfg['include_channels']
		self.base_url = "https://{host}/api/".format(host=self.prtg_host)
		self.url_auth = "username={username}&passhash={passhash}".format(username=self.prtg_user,passhash=self.prtg_hash)
		
class prtg_api(baseconfig):
	def __init__(self):
		baseconfig.__init__(self)
		tree_url = "{base}table.xml?content=sensortree&output=xml&{auth}".format(base=self.base_url,auth=self.url_auth)
		req = requests.get(tree_url,verify=False)
		self.raw_data = req.text
		self.treesoup = BeautifulSoup(self.raw_data,"lxml")
		self.probes = []
		self.groups = []
		self.devices = []
		self.sensors = []
		for child in self.treesoup.find_all("probenode"):
			probeobj = probe(child)
			self.probes.append(probeobj)
			for agroup in probeobj.groups:
				self.groups.append(agroup)
			for adevice in probeobj.devices:
				self.devices.append(adevice)
			for asensor in probeobj.sensors:
				self.sensors.append(asensor)
		self.name = "Root"
		self.id = "0"
		self.status_raw = self.treesoup.group.status_raw.string
		self.active = self.treesoup.group.active.string
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
		self.status = "Up"
		self.active = "true"
		self.status_raw = "3"
	def clone(self,newname,newplaceid):
		clone_url = "{base}duplicateobject.htm?id={objid}&name={name}&targetid={newparent}&{auth}".format(base=self.base_url,objid=self.id,name=newname,newparent=newplaceid,auth=self.url_auth)
		req = requests.get(clone_url,verify=False)
			
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
	def pause(self):
		return("Pause method not supported for channels, pause parent sensor instead")

class sensor(prtg_api):
	def __init__(self,sensorsoup):
		baseconfig.__init__(self)
		self.channels = []
		for child in sensorsoup.children:
			if child.string is None:
				child.string = ""
			if child.name is not None:
				setattr(self,child.name,child.string)
		setattr(self,"attributes",sensorsoup.attrs)
		if self.include_channels:
			channel_url = "{base}table.xml?content=channels&output=xml&columns=name,lastvalue_,objid&id={sensorid}&{auth}".format(base=self.base_url,sensorid=self.id,auth=self.url_auth)
			req = requests.get(channel_url,verify=False)
			channelsoup = BeautifulSoup(req.text,"lxml")
			for child in channelsoup.find_all("item"):
				self.channels.append(channel(child,self.id))

class device(prtg_api):
	def __init__(self,devicesoup):
		baseconfig.__init__(self)
		self.sensors = []
		for child in devicesoup.children:
			if child.name == "sensor":
				self.sensors.append(sensor(child))
			elif child.name is not None:
				if child.string is None:
					child.string = ""
				setattr(self,child.name,child.string)
		setattr(self,"attributes",devicesoup.attrs)

class group(prtg_api):
	def __init__(self,groupsoup):
		baseconfig.__init__(self)
		self.groups = []
		self.devices = []
		self.sensors = []
		for child in groupsoup.children:
			if child.name == "device":
				deviceobj = device(child)
				self.devices.append(deviceobj)
				for sensor in deviceobj.sensors:
					self.sensors.append(sensor)
			elif child.name == "group":
				groupobj = group(child)
				self.groups.append(groupobj)
				for adevice in groupobj.devices:
					for asensor in adevice.sensors:
						self.sensors.append(asensor)
					self.devices.append(adevice)				
			elif child.name is not None:
				if child.string is None:
					child.string = ""
				setattr(self,child.name,child.string)
		setattr(self,"attributes",groupsoup.attrs)

class probe(prtg_api):		
	def __init__(self,probesoup):
		baseconfig.__init__(self)
		self.groups = []
		self.devices = []
		self.sensors = []			
		for child in probesoup.children:
			if child.name == "group":
				groupobj = group(child)
				self.groups.append(groupobj)
				for adevice in groupobj.devices:
					for asensor in adevice.sensors:
						self.sensors.append(asensor)
					self.devices.append(adevice)
				for agroup in groupobj.groups:
					self.groups.append(agroup)
			elif child.name == "device":
				self.devices.append(device(child))
			elif child.name is not None:
				if child.string is None:
					child.string = ""
				setattr(self,child.name,child.string)
		setattr(self,"attributes",probesoup.attrs)
		
if __name__ == "__main__":
	prtg = prtg_api()