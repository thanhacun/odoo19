#!/bin/sh
# Regenerate the mechanically converted views of kdvn_hr_attendance from the Odoo 12 originals (only until hand edits start).
V=/home/thcn/odoo12/addons/kderp_hr_attendance/views; D=addons/kdvn_hr_attendance/views
for f in "$@"; do python3 tools/port_view.py $V/$f.xml $D/$f.xml kderp_hr_attendance=kdvn_hr_attendance kderp_hr.=kdvn_hr. | grep -v INHERITS; done
sed -i 's/id="hr_attendance\.menu_hr_attendance_view_attendances"/id="menu_hr_attendance_view_attendances"/g' $D/*.xml
[ -f $D/hr_attendance_view.xml ] && python3 tools/primary_attendance_views.py $D/hr_attendance_view.xml
