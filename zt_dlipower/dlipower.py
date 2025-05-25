#!/usr/bin/python
# Copyright (c) 2009-2015, Dwight Hubbard
# Copyrights licensed under the New BSD License
# See the accompanying LICENSE.txt file for terms.
"""
Digital Loggers Web Power Switch Management

The module provides a python class named
powerswitch that allows managing the web power
switch from python programs.

When run as a script this acts as a command line utility to
manage the DLI Power switch.

Notes
-----
This module has been tested against the following
Digital Loggers Power network power switches:
  WebPowerSwitch II
  WebPowerSwitch III
  WebPowerSwitch IV
  WebPowerSwitch V
  Ethernet Power Controller III

Examples
--------

*Connecting to a Digital Loggers Power switch*

>>> from zt_dlipower import PowerSwitch
>>> switch = PowerSwitch(hostname='lpc.digital-loggers.com', userid='admin', password='4321')

*Getting the power state (status) from the switch*
Printing the switch object will print a table with the
Outlet Number, Name and Power State

>>> switch
DLIPowerSwitch at lpc.digital-loggers.com
Outlet	Name           	State
1	Battery Charger	     OFF
2	K3 Power ON    	     ON
3	Cisco Router   	     OFF
4	WISP access poi	     ON
5	Shack Computer 	     OFF
6	Router         	     OFF
7	2TB Drive      	     ON
8	Cable Modem1   	     ON

*Getting the name and powerswitch of the first outlet*
The PowerSwitch has a series of Outlet objects, they
will display their name and state if printed.

>>> switch[0]
<dlipower_outlet 'Traffic light:OFF'>

*Renaming the first outlet*
Changing the "name" attribute of an outlet will
rename the outlet on the powerswitch.

>>> switch[0].name = 'Battery Charger'
>>> switch[0]
<dlipower_outlet 'Battery Charger:OFF'>

*Turning the first outlet on*
Individual outlets can be accessed uses normal
list slicing operators.

>>> switch[0].on()
False
>>> switch[0]
<dlipower_outlet 'Battery Charger:ON'>

*Turning all outlets off*
The PowerSwitch() object supports iterating over
the available outlets.

>>> for outlet in switch:
...     outlet.off()
...
False
False
False
False
False
False
False
False
>>> switch
DLIPowerSwitch at lpc.digital-loggers.com
Outlet	Name           	State
1	Battery Charger	OFF
2	K3 Power ON    	OFF
3	Cisco Router   	OFF
4	WISP access poi	OFF
5	Shack Computer 	OFF
6	Router         	OFF
7	2TB Drive      	OFF
8	Cable Modem1   	OFF
"""
import hashlib
import json
import logging
import multiprocessing
import os
import time
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union
from urllib.parse import quote

import requests.exceptions
import urllib3
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# Global settings
CONFIG_DEFAULTS = {
    "retries": 3,
    "timeout": 2,
    "cycletime": 3,
    "userid": "admin",
    "password": "4321",
    "hostname": "192.168.0.100",
}
CONFIG_FILE = os.path.expanduser(os.getenv("ZTDLIPOWER_CONFIG", "~/.dlipower.conf"))


def _call_it(params):  # pragma: no cover
    """indirect caller for instance methods and multiprocessing"""
    instance, name, args = params
    kwargs = {}
    return getattr(instance, name)(*args, **kwargs)


class DLIPowerException(Exception):
    """
    An error occurred talking the the DLI Power switch
    """


class Outlet:
    """
    A power outlet class
    """

    use_description = True

    def __init__(
        self,
        switch: "PowerSwitch",
        outlet_number: int,
        description: Optional[str] = None,
        state: Optional[str] = None,
    ):
        self.switch = switch
        self.outlet_number = outlet_number
        self.description = description
        if not description:
            self.description = str(outlet_number)
        self._state = state

    def __unicode__(self):
        name = None
        if self.use_description and self.description:  # pragma: no cover
            name = "%s" % self.description
        if not name:
            name = "%d" % self.outlet_number
        return "%s:%s" % (name, self._state)

    def __str__(self):
        return self.__unicode__()

    def __repr__(self):
        return "<dlipower_outlet '%s'>" % self.__unicode__()

    def _repr_html_(self) -> str:  # pragma: no cover
        """Display representation as an html table when running in ipython"""
        return """<table>
    <tr><th>Description</th><th>Outlet Number</th><th>State</th></tr>
    <tr><td>{0:s}</td><td>{1:s}</td><td>{2:s}</td></tr>
</table>""".format(
            self.description, self.outlet_number, self.state
        )

    @property
    def state(self) -> Optional[str]:
        """Return the outlet state"""
        return self._state

    @state.setter
    def state(self, value):
        """Set the outlet state"""
        self._state = value
        if value in ["off", "OFF", "0"]:
            self.off()
        if value in ["on", "ON", "1"]:
            self.on()

    def off(self) -> bool:
        """Turn the outlet off"""
        return self.switch.off(self.outlet_number)

    def on(self) -> bool:  # pylint: disable=invalid-name
        """Turn the outlet on"""
        return self.switch.on(self.outlet_number)

    def rename(self, new_name) -> bool:
        """
        Rename the outlet
        :param new_name: New name for the outlet
        :return:
        """
        return self.switch.set_outlet_name(self.outlet_number, new_name)

    @property
    def name(self) -> str:
        """Return the name or description of the outlet"""
        return self.switch.get_outlet_name(self.outlet_number)

    @name.setter
    def name(self, new_name):
        """Set the name of the outlet"""
        self.rename(new_name)


class PowerSwitch:
    """Powerswitch class to manage the Digital Loggers Web power switch"""

    __len = 0
    login_timeout = 2.0
    secure_login = False

    def __init__(
        self,
        userid: Optional[str] = None,
        password: Optional[str] = None,
        hostname: Optional[str] = None,
        timeout: Optional[float] = None,
        cycletime: Optional[float] = None,
        retries: Optional[int] = None,
        use_https: bool = False,
    ):
        """
        Class initializaton
        """
        config = self.load_configuration()
        if userid:
            self.userid = str(userid)
        else:
            self.userid = str(config["userid"])
        if password:
            self.password = str(password)
        else:
            self.password = str(config["password"])
        if hostname:
            self.hostname = str(hostname)
        else:
            self.hostname = str(config["hostname"])
        if timeout:
            self.timeout = float(timeout)
        else:
            self.timeout = float(config["timeout"])
        if cycletime:
            self.cycletime = float(cycletime)
        else:
            self.cycletime = float(config["cycletime"])
        if retries:
            self.retries = int(retries)
        else:
            self.retries = int(config["retries"])
        self.scheme: str = "http"
        if use_https:
            self.scheme = "https"
        self.base_url: str = "%s://%s" % (self.scheme, self.hostname)
        self._is_admin: bool = True
        self.session: Optional[requests.Session] = requests.Session()
        self.login()

    def __len__(self):
        """
        :return: Number of outlets on the switch
        """
        if self.__len == 0:
            self.__len = len(self.statuslist())
        return self.__len

    def __repr__(self):
        """
        display the representation
        """
        if not self.statuslist():
            return "Digital Loggers Web Powerswitch " "%s (UNCONNECTED)" % self.hostname
        output = "DLIPowerSwitch at %s\n" "Outlet\t%-15.15s\tState\n" % (
            self.hostname,
            "Name",
        )
        for item in self.statuslist():
            output += "%d\t%-15.15s\t%s\n" % (item[0], item[1], item[2])
        return output

    def _repr_html_(self) -> str:
        """
        __repr__ in an html table format
        """
        if not self.statuslist():
            return "Digital Loggers Web Powerswitch " "%s (UNCONNECTED)" % self.hostname
        output = (
            "<table>"
            '<tr><th colspan="3">DLI Web Powerswitch at %s</th></tr>'
            "<tr>"
            "<th>Outlet Number</th>"
            "<th>Outlet Name</th>"
            "<th>Outlet State</th></tr>\n" % self.hostname
        )
        for item in self.statuslist():
            output += "<tr><td>%d</td><td>%s</td><td>%s</td></tr>\n" % (
                item[0],
                item[1],
                item[2],
            )
        output += "</table>\n"
        return output

    def __getitem__(self, index):
        outlets = []
        if isinstance(index, slice):
            status = self.statuslist()[index.start : index.stop]
        else:
            status = [self.statuslist()[index]]
        for outlet_status in status:
            power_outlet = Outlet(
                switch=self,
                outlet_number=outlet_status[0],
                description=outlet_status[1],
                state=outlet_status[2],
            )
            outlets.append(power_outlet)
        if len(outlets) == 1:
            return outlets[0]
        return outlets

    def login(self) -> None:
        self.secure_login = False
        self.session = requests.Session()
        try:
            response = self.session.get(
                self.base_url,
                verify=False,
                timeout=self.login_timeout,
                allow_redirects=False,
            )
            if response.is_redirect:
                self.base_url = response.headers["Location"].rstrip("/")
                logger.debug(f"Redirecting to: {self.base_url}")
                response = self.session.get(
                    self.base_url, verify=False, timeout=self.login_timeout
                )
        except (
            requests.exceptions.ConnectTimeout,
            requests.exceptions.ConnectionError,
        ):
            self.session = None
            return
        soup = BeautifulSoup(response.text, "html.parser")
        fields = {}
        for field in soup.find_all("input"):
            name = field.get("name", None)
            value = field.get("value", "")
            if name:
                fields[name] = value

        fields["Username"] = self.userid
        fields["Password"] = self.password

        form_response = (
            fields["Challenge"]
            + fields["Username"]
            + fields["Password"]
            + fields["Challenge"]
        )

        md5hash = hashlib.md5()  # nosec - The switch we are talking to uses md5 hashes
        md5hash.update(form_response.encode())
        data = {"Username": f"{self.userid}", "Password": md5hash.hexdigest()}
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            response = self.session.post(
                "%s/login.tgi" % self.base_url,
                headers=headers,
                data=data,
                timeout=self.timeout,
                verify=False,
            )
        except requests.exceptions.ConnectTimeout:
            self.secure_login = False
            self.session = None
            return

        if response.status_code == 200:
            if "Set-Cookie" in response.headers:
                self.secure_login = True

    def load_configuration(self) -> Dict:
        """Return a configuration dictionary"""
        if os.path.isfile(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as file_h:
                try:
                    config = json.load(file_h)
                except ValueError:
                    # Failed
                    return CONFIG_DEFAULTS
            return config
        return CONFIG_DEFAULTS

    def save_configuration(self) -> None:
        """Update the configuration file with the object's settings"""
        # Get the configuration from the config file or set to the defaults
        config = self.load_configuration()

        # Overwrite the objects configuration over the existing config values
        config["userid"] = self.userid
        config["password"] = self.password
        config["hostname"] = self.hostname
        config["timeout"] = self.timeout

        # Write it to disk
        with open(CONFIG_FILE, "w") as file_h:
            # Make sure the file perms are correct before we write data
            # that can include the password into it.
            if hasattr(os, "fchmod"):
                os.fchmod(file_h.fileno(), 0o0600)
            json.dump(config, file_h, sort_keys=True, indent=4)

    def verify(self) -> bool:
        """Verify we can reach the switch, returns true if ok"""
        if self.geturl():
            return True
        return False

    def geturl(self, url="index.htm"):
        """
        Get a URL from the userid/password protected powerswitch page Return None on failure
        """
        full_url = "%s/%s" % (self.base_url, url)
        result = None
        request = None
        logger.debug(f"Requesting url: {full_url}")
        for retry_num in range(0, self.retries):
            try:
                if self.secure_login and self.session:
                    request = self.session.get(
                        full_url,
                        timeout=self.timeout,
                        verify=False,
                        allow_redirects=True,
                    )
                else:
                    request = requests.get(
                        full_url,
                        auth=(
                            self.userid,
                            self.password,
                        ),
                        timeout=self.timeout,
                        verify=False,
                        allow_redirects=True,
                    )  # nosec
            except requests.exceptions.RequestException as err:
                logger.warning(
                    "Request timed out - %d retries left.", self.retries - retry_num - 1
                )
                logger.exception("Caught exception %s", str(err))
                continue
            if request.status_code == 200:
                result = request.content
                break
        if request is not None:
            logger.debug("Response code: %s", request.status_code)
        logger.debug(f"Response content: {result}")
        return result

    def determine_outlet(self, outlet: Union[str, int]) -> int:
        """Get the correct outlet number from the outlet passed in, this
        allows specifying the outlet by the name and making sure the
        returned outlet is an int
        """
        outlets = self.statuslist()
        if outlet and outlets and isinstance(outlet, (int, str)):
            for plug in outlets:
                plug_name = plug[1]
                plug_number = int(plug[0])
                if isinstance(outlet, str):
                    if plug_name and plug_name.strip() == outlet.strip():
                        return plug_number
                elif isinstance(outlet, int):
                    if plug_number and plug_number == outlet:
                        return plug_number
        try:
            outlet_int = int(outlet)
            if outlet_int <= 0 or outlet_int > len(self):
                raise DLIPowerException("Outlet number %d out of range" % outlet_int)
            return outlet_int
        except ValueError as err:
            raise DLIPowerException("Outlet name '%s' unknown" % outlet) from err

    def get_outlet_name(self, outlet: int = 0) -> str:
        """Return the name of the outlet"""
        outlet = self.determine_outlet(outlet)
        outlets = self.statuslist()
        if outlets and outlet:
            for plug in outlets:
                if int(plug[0]) == outlet:
                    return plug[1]
        return "Unknown"

    def set_outlet_name(self, outlet=0, name="Unknown") -> bool:
        """Set the name of an outlet"""
        self.determine_outlet(outlet)
        self.geturl(url="unitnames.cgi?outname%s=%s" % (outlet, quote(name)))
        return self.get_outlet_name(outlet) == name

    def off(self, outlet=0) -> bool:
        """Turn off a power to an outlet
        False = Success
        True = Fail
        """
        self.geturl(url="outlet?%d=OFF" % self.determine_outlet(outlet))
        return self.status(outlet) != "OFF"

    def on(self, outlet=0) -> bool:  # pylint: disable=invalid-name
        """Turn on power to an outlet
        False = Success
        True = Fail
        """
        self.geturl(url="outlet?%d=ON" % self.determine_outlet(outlet))
        return self.status(outlet) != "ON"

    def cycle(self, outlet=0) -> bool:
        """Cycle power to an outlet
        False = Power off Success
        True = Power off Fail
        Note, does not return any status info about the power on part of
        the operation by design
        """
        if self.off(outlet):
            return True
        time.sleep(self.cycletime)
        self.on(outlet)
        return False

    def statuslist(self) -> List[Tuple[int, str, str]]:
        """Return the status of all outlets in a list,
        each item will contain 3 items plugnumber, hostname and state"""
        outlets = []
        url = self.geturl("index.htm")
        if not url:
            return []
        soup = BeautifulSoup(url, "html.parser")
        # Get the root of the table containing the port status info
        try:
            root = soup.findAll("td", text="1")[0].parent.parent.parent
        except IndexError:
            # Finding the root of the table with the outlet info failed
            # try again assuming we're seeing the table for a user
            # account instead of the admin account (tables are different)
            try:
                self._is_admin = False
                root = soup.findAll("th", text="#")[0].parent.parent.parent
            except IndexError:
                return []
        for temp in root.findAll("tr"):
            columns = temp.findAll("td")
            if len(columns) == 5:
                plugnumber = columns[0].string
                hostname = columns[1].string
                state = columns[2].find("font").string.upper()
                outlets.append((int(plugnumber), hostname, state))
        if self.__len == 0:
            self.__len = len(outlets)
        return outlets

    def printstatus(self) -> None:
        """Print the status off all the outlets as a table to stdout"""
        if not self.statuslist():
            print("Unable to communicate to the Web power switch at %s" % self.hostname)
            return
        print("Outlet\t%-15.15s\tState" % "Name")
        for item in self.statuslist():
            print("%d\t%-15.15s\t%s" % (item[0], item[1], item[2]))
        return

    def status(self, outlet: int = 1) -> str:
        """
        Return the status of an outlet, returned value will be one of:
        ON, OFF, Unknown
        """
        outlet = self.determine_outlet(outlet)
        outlets = self.statuslist()
        if outlets and outlet:
            for plug in outlets:
                if plug[0] == outlet:
                    return plug[2]
        return "Unknown"

    def command_on_outlets(self, command, outlets):
        """
        If a single outlet is passed, handle it as a single outlet and
        pass back the return code.  Otherwise run the operation on multiple
        outlets in parallel the return code will be failure if any operation
        fails.  Operations that return a string will return a list of strings.
        """
        if len(outlets) == 1:
            result = getattr(self, command)(outlets[0])
            if isinstance(result, bool):
                return result
            return [result]
        with multiprocessing.Pool(processes=len(outlets)) as pool:
            result = list(
                pool.imap(
                    _call_it,
                    [(self, command, (outlet,)) for outlet in outlets],
                    chunksize=1,
                )
            )
            pool.close()
            pool.join()
        if isinstance(result[0], bool):
            for value in result:
                if value:
                    return True
            return result[0]
        return result


if __name__ == "__main__":  # pragma: no cover
    PowerSwitch().printstatus()
    print(CONFIG_FILE)
