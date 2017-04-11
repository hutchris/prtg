import os
import csv
import requests
from datetime import datetime,timedelta
from bs4 import BeautifulSoup
from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

#class used by prtg_api and children to manage global arrays of all objects
class global_arrays(object):
	allprobes = []
	allgroups = []
	alldevices = []
	allsensors = []

#class used by all prtg_* objects to build urls and query prtg using requests	
class connection_methods(object):
	def unpack_config(self,confdata):
		self.host = confdata[0]
		self.port = confdata[1]
		self.user = confdata[2]
		self.passhash = confdata[3]
		self.protocol = confdata[4]
		self.confdata = confdata
		self.base_url = "{protocol}://{host}:{port}/api/".format(protocol=self.protocol,host=self.host,port=self.port)
		self.base_url_no_api = "{protocol}://{host}:{port}/".format(protocol=self.protocol,host=self.host,port=self.port)
		self.url_auth = "username={username}&passhash={passhash}".format(username=self.user,passhash=self.passhash)
	def get_request(self,url_string,api=True):
		#global method for api calls. Provides errors for the 401 and 404 responses
		if api:
			url = "{base}{content}&{auth}".format(base=self.base_url,content=url_string,auth=self.url_auth)
		else:
			url = "{base}{content}&{auth}".format(base=self.base_url_no_api,content=url_string,auth=self.url_auth)
		req = requests.get(url,verify=False)
		if req.status_code == 200:
			return(req)
		elif req.status_code == 401:
			raise(self.AuthenticationError("PRTG authentication failed. Check credentials in config file"))
		elif req.status_code == 404:
			raise(self.ResourceNotFound("No resource at URL used: {0}".format(tree_url)))

class baseconfig(connection_methods):
	def __str__(self):
		return("<Name: {name}, ID: {id}, Active: {active}>".format(name=self.name,id=self.id,active=self.active))
	def __repr__(self):
		return("<Name: {name}, ID: {id}, Active: {active}>".format(name=self.name,id=self.id,active=self.active))
	def clear_arrays(self):
		del self.allprobes[:]
		del self.allgroups[:]
		del self.alldevices[:]
		del self.allsensors[:]
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
		self.name = value
	def get_property(self,name):
		if self.type != "Channel":
			getprop_url = "getobjectproperty.htm?id={objid}&name={propname}&show=text".format(objid=self.id,propname=name)
		else:
			getprop_url = "getobjectproperty.htm?id={objid}&subid={subid}&name={propname}".format(objid=self.sensorid,subid=self.objid,propname=name)
		req = self.get_request(url_string=getprop_url)
		soup = BeautifulSoup(req.text,'lxml')
		if soup.result.text != "(Property not found)":
			setattr(self,name,soup.result.text)
			return(soup.result.text)
		else:
			raise(self.ResourceNotFound("No object property of name: {name}".format(name=name)))
	def set_interval(self,interval):
		'''note: you will still need to disable inheritance manually.
		Valid intervals are (seconds): 30, 60, 300, 600, 900, 1800, 3600, 14400, 21600, 43200, 86400'''
		self.set_property(name="interval",value=interval)
	def get_tree(self,root=''):
		#gets sensortree from prtg. If no rootid is provided returns entire tree
		tree_url = "table.xml?content=sensortree&output=xml&id={rootid}".format(rootid=root)
		req = self.get_request(url_string=tree_url)
		raw_data = req.text
		treesoup = BeautifulSoup(raw_data,"lxml")
		#returns the xml as a beautifulsoup object
		if len(treesoup.sensortree.nodes) > 0:
			return(treesoup)
		else:
			raise(self.ResourceNotFound("No objects at ID: {id}".format(id=root)))
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
	#define global arrays, inherited to all objects
	class AuthenticationError(Exception):
		pass
	class ResourceNotFound(Exception):
		pass
		
class prtg_api(global_arrays,baseconfig):
	'''
	Parameters:
	- host: Enter the ip address or hostname where PRTG is running
	- port: Enter the tcp port used to connect to prtg. (usually 80 or 443)
	- user: Enter your PRTG username
	- passhash: Enter your PRTG passhash. Can be found in PRTG webgui > settings > account settings
	- protocol: Enter the protocol used to connect to PRTG server (http or https)
	- rootid: Enter the id of the group/probe that contains all the objects you want to manage. Defaults to 0 (gets entire sensortree)
	
	Example:
	host = '192.168.1.1'
	port = '443'
	user = 'prtgadmin'
	passhash = '0000000'
	protocol = 'https'
	rootid = '53'
	prtg = prtg_api(host,port,user,passhash,protocol,rootid)
	'''
	def __init__(self,host,port,user,passhash,protocol,rootid=0):
		self.confdata = (host,port,user,passhash,protocol)
		self.unpack_config(self.confdata)
		self.clear_arrays()
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
	def refresh(self):
		#download fresh sensortree
		self.treesoup = self.get_tree(root=self.id)
		probeids = []
		newprobeids = []
		groupids = []
		newgroupids = []
		deviceids = []
		newdeviceids = []
		#get ids of existing probes
		for aprobe in self.probes:
			probeids.append(aprobe.id)
		for agroup in self.groups:
			groupids.append(agroup.id)
		for adevice in self.devices:
			deviceids.append(adevice.id)
		#for all the child objects in sensortree, if it already exists refresh the object, otherwise create a new one	
		for child in self.treesoup.sensortree.nodes.children:
			if child.name is not None:
				for childr in child.children:
					if childr.name == "probenode":
						if childr.find("id").string in probeids:
							for aprobe in self.probes:
								if aprobe.id == childr.find("id").string:
									aprobe.refresh(childr)
						else:
							probeobj = probe(childr,self.confdata)
							self.probes.append(probeobj)
							self.allprobes.append(probeobj)
						#add all probe ids from the sensortree to this list
						newprobeids.append(childr.find("id").string)
					elif childr.name == "group":
						if childr.find("id").string in groupids:
							for agroup in self.groups:
								if agroup.id == childr.find("id").string:
									agroup.refresh(childr)
						else:
							groupobj = group(childr,self.confdata)
							self.allgroups.append(groupobj)
							self.groups.append(groupobj)
						#add all probe ids from the sensortree to this list
						newgroupids.append(childr.find("id").string)
					elif childr.name == "device":
						if childr.find("id").string in deviceids:
							for adevice in self.devices:
								if adevice.id == childr.find("id").string:
									adevice.refresh(childr)
						else:
							deviceobj = device(childr,self.confdata)
							self.alldevices.append(devicebj)
							self.device.append(deviceobj)
						#add all probe ids from the sensortree to this list
						newdeviceids.append(childr.find("id").string)
					elif childr.name is not None:
						if childr.string is None:
							childr.string = ""
						setattr(self,childr.name,childr.string)
		#if existing probes were not in the new sensortree, remove from allprobes
		for id in probeids:
			if id not in newprobeids:
				for aprobe in self.probes:
					if aprobe.id == id:
						self.allprobes.remove(aprobe)
						self.probes.remove(aprobe)
		for id in groupids:
			if id not in newgroupids:
				for agroup in self.groups:
					if agroup.id == id:
						self.allgroups.remove(agroup)
						self.groups.remove(agroup)
		for id in deviceids:
			if id not in newdeviceids:
				for adevice in self.devices:
					if adevice.id == id:
						self.alldevice.remove(adevice)
						self.devices.remove(adevice)
	def search_byid(self,id):
		id = str(id)
		for obj in self.allprobes + self.allgroups + self.alldevices + self.allsensors:
			if obj.id == id:
				return(obj)
				
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
		if hasattr(self,'lastvalue'):
			self.lastvalue_int = int(self.lastvalue.split(" ")[0])
			self.unit = self.lastvalue.split(" ")[1]
		self.type = "Channel"
	def __str__(self):
		return("<Name: {name}, ID: {id}>".format(name=self.name,id=self.id))
	def __repr__(self):
		return("<Name: {name}, ID: {id}>".format(name=self.name,id=self.id))
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
	def save_graph(self,graphid,filepath,size,hidden_channels='',filetype='svg'):
		'''
		Size options: S,M,L
		'''
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
		chart_url = "chart.{ft}?type=graph&graphid={gid}&id={sid}&width={w}&height={h}{hc}&plotcolor=%23ffffff&gridcolor=%23ffffff&graphstyling=showLegend%3D%271%27+baseFontSize%3D%27{f}%27".format(
			ft=filetype,gid=graphid,sid=self.id,w=width,h=height,hc=hidden_channels,f=font)
		req = self.get_request(url_string=chart_url,api=False)
		with open(filepath,"wb") as imgfile:
			for chunk in req:
				imgfile.write(chunk)
		self.filepath = filepath

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
	
class prtg_device(baseconfig):
	'''Seperate top level object to manage just a device and its sensors instead of
	downloading details for an entire group'''
	def __init__(self,host,port,user,passhash,protocol,deviceid):
		self.confdata = (host,port,user,passhash,protocol)
		self.unpack_config(self.confdata)
		self.sensors = []
		soup = self.get_tree(root=deviceid)
		for child in soup.sensortree.nodes.device:
			if child.name == "sensor":
				sensorobj = sensor(child,self.id,self.confdata)
				self.sensors.append(sensorobj)
			elif child.name is not None:
				if child.string is None:
					child.string = ""
				setattr(self,child.name,child.string)
	def refresh(self):
		soup = self.get_tree(root=deviceid)
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
					sensorobj = sensor(child,self.id,self.confdata)
					self.sensors.append(sensorobj)
			elif child.name is not None:
				if child.string is None:
					child.string = ""
				setattr(self,child.name,child.string)

class prtg_sensor(baseconfig):
	'''Seperate top level object to manage just a sensor and its channels instead of
	downloading details for an entire group'''
	def __init__(self,host,port,user,passhash,protocol,sensorid):
		self.confdata = (host,port,user,passhash,protocol)
		self.unpack_config(self.confdata)
		self.channels = []
		soup = self.get_tree(root=sensorid)
		for child in soup.sensortree.nodes.sensor:
			if child.name is not None:
				if child.string is None:
					child.string = ""
				setattr(self,child.name,child.string)
		self.get_channels()
	def refresh(self):
		soup = self.get_tree(root=self.id)
		for child in soup.sensortree.nodes.sensor.children:
			if child.string is None:
				child.string = ""
			if child.name is not None:
				setattr(self,child.name,child.string)
		setattr(self,"attributes",sensorsoup.attrs)
		self.get_channels()
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
	def save_graph(self,graphid,filepath,size,hidden_channels='',filetype='svg'):
		'''
		Size options: S,M,L
		'''
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
		chart_url = "chart.{ft}?type=graph&graphid={gid}&id={sid}&width={w}&height={h}{hc}&plotcolor=%23ffffff&gridcolor=%23ffffff&graphstyling=showLegend%3D%271%27+baseFontSize%3D%27{f}%27".format(
			ft=filetype,gid=graphid,sid=self.id,w=width,h=height,hc=hidden_channels,f=font)
		req = self.get_request(url_string=chart_url,api=False)
		with open(filepath,"wb") as imgfile:
			for chunk in req:
				imgfile.write(chunk)
		self.filepath = filepath

class prtg_historic_data(connection_methods):
	'''class used for calls to the historic data api.
	Call the class first using connection params then use
	methods to get/process data. yyyy-mm-dd-hh-mm-ss'''
	def __init__(self,host,port,user,passhash,protocol):
		self.confdata = (host,port,user,passhash,protocol)
		self.unpack_config(self.confdata)
	def format_date(self,dateobj):
		'''Pass a datetime object and this will format appropriately
		for use with the historic data api'''
		return(dateobj.strftime("%Y-%m-%d-%H-%M-%S"))
	def get_historic_data(self,objid,startdate,enddate,timeaverage):
		if type(startdate) == datetime:
			startdate = self.format_date(startdate)
		if type(enddate) == datetime:
			enddate = self.format_date(enddate)	
		historic_url = "historicdata.csv?id={id}&avg={avg}&sdate={sdate}&edate={edate}".format(id=objid,avg=timeaverage,sdate=startdate,edate=enddate)
		req = self.get_request(url_string=historic_url)
		csvRaw = req.text
		csvLines = (csvRaw.split("\n"))[:-2]
		csvReader = csv.reader(csvLines)
		data = {}
		for ind,row in enumerate(csvReader):
			if ind == 0:
				headers = row
				for header in headers:
					data[header] = []
			else:
				for inde,cell in enumerate(row):
					if headers[inde] == "Date Time":
						if "-" in cell:
							cell = cell[:cell.index(" -")]
						data[headers[inde]].append(datetime.strptime(cell,"%m/%d/%Y %I:%M:%S %p"))
					else:
						data[headers[inde]].append(cell)
		return(data)
	