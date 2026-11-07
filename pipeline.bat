echo on
cd "04 - QueryDNS"
python get_mx.py
python get_ns.py
python get_cname.py
python geo_lookup.py
cd ..
cd "05 - ISDC"
python isdc.py
cd ..
cd "06 - BuildGeojson"
python Generate_geojson.py
cd ..
cd "07 - StatsJson"
python StatJson.py
cd ..
pause
