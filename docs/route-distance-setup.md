# Distance by car for the staff transfer: setup (Odoo 19 port of the Odoo 12 feature; parameter names are the same)

The staff transfer form shows the distance **by car** from the staff's main office to the new project
(`kdvn_hr_procedures`, model `transfer.route.distance`). Odoo asks a map service from the server, once per
(office address, project address) pair; the answer is cached 90 days. Google Maps is not used (our billing account is refused).

## Provider
E-Approval > Configuration > Settings (the E-Approval settings screen), block **Staff Transfer: Distance by Car**: choose the provider and,
for Goong, type the key (it shows only "Saved" afterwards). These write the System Parameters below, which you can also edit directly
(developer mode, Settings > Technical > Parameters):

| Key | Value |
|---|---|
| `kderp_hr_procedures.route_provider` | empty or `osm` (default) / `goong` |
| `kderp_hr_procedures.goong_api_key` | only for `goong` |
| `kderp_hr_procedures.nominatim_url`, `kderp_hr_procedures.osrm_url` | optional, own OSM servers |

### OpenStreetMap (default, nothing to set up)
Nominatim finds the point of each address, OSRM computes the route. No key, no account. The public servers are for light use
(about 1 request a second): enough for a few transfers a day. The address is tried in full, then without its first parts
(house number / building), so the distance can be approximate when the map does not know the building.
Vietnamese street addresses are sometimes not found: the form then says "Address not found on the map".

### Goong.io (option if OSM does not find the project addresses)
1. Register at https://goong.io, create a project and an **API key** (REST/Maps key). Check their current free quota and price.
2. On the settings screen choose Goong and type the key. Never put the key in git, a ticket or a chat; it is stored as
   plain text in the database, so remove it on copies of the database (neutralize).

## Offices and project address
- Head Office = the company's own address. Hai Phong = a second address of the company with **City = Hai Phong** and the street filled in:
  Settings > Users & Companies > Companies > the company > tab **Office Addresses** > button *Show / add office addresses* > Create.
- The project address comes from the remote job (`project_address_id`), pulled by `kdvn_remote_sync`. It must be a real address.

## Test
On the lab database: create a staff transfer with a New Project that has an address and save. The "Distance by car" line shows
km per office; "Recalculate" retries. Quick check from a shell:
`env['transfer.route.distance']._fetch('<office address>', '<project address>', '')` returns (meters, seconds).
