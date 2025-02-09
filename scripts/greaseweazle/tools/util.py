# greaseweazle/tools/util.py
#
# Greaseweazle control script: Utility functions.
#
# Written & released by Keir Fraser <keir.xen@gmail.com>
#
# This is free and unencumbered software released into the public domain.
# See the file COPYING for more details, or visit <http://unlicense.org>.

import os, sys, serial

from greaseweazle import version
from greaseweazle import usb as USB
from greaseweazle.image.scp import SCP
from greaseweazle.image.hfe import HFE


def get_image_class(name):
    image_types = { '.scp': SCP, '.hfe': HFE }
    _, ext = os.path.splitext(name)
    if not ext.lower() in image_types:
        print("**Error: Unrecognised file suffix '%s'" % ext)
        return None
    return image_types[ext.lower()]


def with_drive_selected(fn, usb, args):
    try:
        usb.drive_select(True)
        usb.drive_motor(True)
        fn(usb, args)
    except KeyboardInterrupt:
        print()
        usb.reset()
        usb.ser.close()
        usb.ser.open()
    finally:
        usb.drive_motor(False)
        usb.drive_select(False)


def usb_open(devicename, is_update=False):

    usb = USB.Unit(serial.Serial(devicename))

    print("** %s v%u.%u, Host Tools v%u.%u"
          % (("Greaseweazle", "Bootloader")[usb.update_mode],
             usb.major, usb.minor,
             version.major, version.minor))

    if usb.update_mode and not is_update:
        print("Greaseweazle is in Firmware Update Mode:")
        print(" The only available action is \"update <update_file>\"")
        if usb.update_jumpered:
            print(" Remove the Update Jumper for normal operation")
        else:
            print(" Main firmware is erased: You *must* perform an update!")
        sys.exit(1)

    if is_update and not usb.update_mode:
        print("Greaseweazle is in Normal Mode:")
        print(" To \"update\" you must install the Update Jumper")
        sys.exit(1)

    if not usb.update_mode and usb.update_needed:
        print("Firmware is out of date: Require v%u.%u"
              % (version.major, version.minor))
        print("Install the Update Jumper and \"update <update_file>\"")
        sys.exit(1)

    return usb
    


# Local variables:
# python-indent: 4
# End:
