#!/usr/bin/env python
# Copyright (c) 2009-2015, Dwight Hubbard
# Copyrights licensed under the New BSD License
# See the accompanying LICENSE.txt file for terms.
"""
###############################################################
Digital Loggers Web Power Switch management
###############################################################
 Description: This is both a module and a script

              The module provides a python class named
              PowerSwitch that allows managing the web power
              switch from python programs.

              When run as a script this acts as a command
              line utility to manage the DLI Power switch.

              This module has been tested against the following
              Digital Loggers Power network power switches:
                WebPowerSwitch II
                WebPowerSwitch III
                WebPowerSwitch IV
                WebPowerSwitch V
                Ethernet Power Controller III
"""
from __future__ import print_function

import optparse  # pylint: disable=deprecated-module
import sys

from zt_dlipower import DLIPowerException
from zt_dlipower import PowerSwitch

# TODO: replace with argparse or something


def _block_to_list(block):
    """Convert a range block into a numeric list

    >>> _block_to_list("1,2,3,4,5")
    ['1', '2', '3', '4', '5']
    >>> _block_to_list("6-9")
    ['6', '7', '8', '9']
    >>> _block_to_list("6-10")
    ['06', '07', '08', '09', '10']
    >>> _block_to_list("1-3,17,19-20")
    ['1', '2', '3', '17', '19', '20']
    """
    block += ","
    result = []
    val = ""
    in_range = False
    for letter in block:
        if letter in [",", "-"]:
            if in_range:
                val2 = val
                val2_len = len(val2)
                # result += range(int(val1),int(val2)+1)
                for value in range(int(val1), int(val2) + 1):
                    result.append(str(value).zfill(val2_len))
                val = ""
                val1 = None
                in_range = False
            else:
                val1 = val
                val1_len = len(val1)
                val = ""
            if letter == ",":
                if val1 is not None:
                    result.append(val1.zfill(val1_len))
            else:
                in_range = True
        else:
            val += letter
    return result


def __command_on_outlets(action, outlet_range, switch, debug: bool = True):
    """Execute given action on switch with range argument.  Handle exceptions."""
    try:
        return switch.command_on_outlets(action, outlet_range)
    except DLIPowerException as err:
        # TODO: convert to actual logging calls
        if debug:
            print(err, file=sys.stderr)
        sys.exit(1)


def main():
    usage = "usage: %prog [options] [status|on|off|cycle|get_outlet_name|set_outlet_name] [range|arg]"
    parser = optparse.OptionParser(usage=usage)
    parser.add_option(
        "--hostname",
        dest="hostname",
        default=None,
        help="hostname/ip of the power switch (default %default)",
    )
    parser.add_option(
        "--timeout",
        dest="timeout",
        default=None,
        help="Timeout for value for power switch communication (default %default)",
    )
    parser.add_option(
        "--cycletime",
        dest="cycletime",
        default=None,
        type=int,
        help="Delay betwween off/on states for power cycle operations (default %default)",
    )
    parser.add_option(
        "--user",
        dest="user",
        default=None,
        help="userid to connect with (default %default)",
    )
    parser.add_option(
        "--password", dest="password", default=None, help="password (default %default)"
    )
    parser.add_option(
        "--save_settings",
        dest="save_settings",
        default=False,
        action="store_true",
        help="Save the settings to the configuration file",
    )
    parser.add_option(
        "--ssl",
        default=False,
        action="store_true",
        help="Use ssl to connect to the switch",
    )
    (options, args) = parser.parse_args()

    switch = PowerSwitch(
        userid=options.user,
        password=options.password,
        hostname=options.hostname,
        timeout=options.timeout,
        cycletime=options.cycletime,
        use_https=options.ssl,
    )
    if options.save_settings:
        switch.save_configuration()
    if len(args):
        operation = args[0].lower()
        outlet_range = _block_to_list(",".join(args[1:]))
        if len(args) > 1:
            if operation in ["status"]:
                print(",".join(__command_on_outlets("status", outlet_range, switch)))
            elif operation in ["on", "poweron"]:
                rc = __command_on_outlets("on", outlet_range, switch)
                if rc:
                    print("Power on operation failed", file=sys.stderr)
                sys.exit(rc)
            elif operation in ["off", "poweroff"]:
                rc = __command_on_outlets("off", outlet_range, switch)
                if rc:
                    print("Power off operation failed", file=sys.stderr)
            elif operation in ["cycle"]:
                sys.exit(__command_on_outlets("cycle", outlet_range, switch))
            elif operation in [
                "get_name",
                "getname",
                "get_outlet_name",
                "getoutletname",
            ]:
                print(
                    ",".join(
                        __command_on_outlets("get_outlet_name", outlet_range, switch)
                    )
                )
            elif operation in [
                "set_name",
                "setname",
                "set_outlet_name",
                "setoutletname",
            ]:
                sys.exit(switch.set_outlet_name(args[1], args[2]))
            else:
                print("Unknown argument %s" % args[0])
    else:
        switch.printstatus()
