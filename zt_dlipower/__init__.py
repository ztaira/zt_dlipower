# Copyright (c) 2009-2015, Dwight Hubbard
# Copyrights licensed under the New BSD License
# See the accompanying LICENSE.txt file for terms.
from .dlipower import DLIPowerException
from .dlipower import Outlet
from .dlipower import PowerSwitch

try:
    import pkg_resources

    __version__ = pkg_resources.get_distribution("zt_dlipower").version
except ImportError:
    __version__ = str("0.0.0")

__all__ = ["dlipower"]
