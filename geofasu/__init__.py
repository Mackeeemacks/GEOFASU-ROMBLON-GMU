# -*- coding: utf-8 -*-

import os
import sys

# ⭐ Use bundled libraries (offline-safe)
vendor_path = os.path.join(os.path.dirname(__file__), "vendor")
if vendor_path not in sys.path:
    sys.path.insert(0, vendor_path)


# noinspection PyPep8Naming
def classFactory(iface):
    from .geofasu import geofasu
    return geofasu(iface)