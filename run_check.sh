#!/bin/bash
export XDG_RUNTIME_DIR="/run/user/1000"
export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/1000/bus"
/usr/bin/python3 /home/ginhikari/.config/nexus-mod-checker/check_updates.py >> /home/ginhikari/.config/nexus-mod-checker/last_check.log 2>&1
