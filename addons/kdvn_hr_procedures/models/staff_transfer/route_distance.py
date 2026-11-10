"""Driving distance between two addresses, cached.

Used by the staff transfer request: main office of the staff -> address of the new project.
Provider = System Parameter `kderp_hr_procedures.route_provider`:
  * `osm` (default): OpenStreetMap, Nominatim (address -> point) + OSRM (route). No key, no billing. The public
    servers are for light use only (about 1 request a second, User-Agent required): fine here (a few calls a day,
    result cached 90 days). Own servers: `kderp_hr_procedures.nominatim_url` / `kderp_hr_procedures.osrm_url`.
  * `goong`: Goong.io (Vietnam), geocode + direction; key in `kderp_hr_procedures.goong_api_key`.
Google Maps is not used (not available to our billing account).
Never raises to the caller: `get_km` returns (km or None, message).
"""
import logging
import re
import time
from datetime import timedelta

import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

CACHE_DAYS = 90
FAILURE_MINUTES = 60
MAX_VARIANTS = 5
PARAM_PROVIDER = 'kderp_hr_procedures.route_provider'
PARAM_GOONG_KEY = 'kderp_hr_procedures.goong_api_key'
PARAM_NOMINATIM = 'kderp_hr_procedures.nominatim_url'
PARAM_OSRM = 'kderp_hr_procedures.osrm_url'
NOMINATIM_URL = 'https://nominatim.openstreetmap.org'
OSRM_URL = 'https://router.project-osrm.org'
GOONG_URL = 'https://rsapi.goong.io'
USER_AGENT = 'KDERP-Odoo/19 (staff transfer distance)'
PROVIDERS = ('osm', 'goong')


class TransferRouteDistance(models.Model):
    _name = 'transfer.route.distance'
    _description = 'Cached driving distance between two addresses'
    _order = 'fetched_at desc'

    origin = fields.Char(required=True, index=True)
    destination = fields.Char(required=True, index=True)
    distance_km = fields.Float(digits=(12, 1))
    duration_min = fields.Integer()
    fetched_at = fields.Datetime(required=True, default=fields.Datetime.now)
    failure = fields.Char(help="Reason of a failed lookup, remembered for a short time so that saving a draft again does not call the map service again")

    @api.model
    def _param(self, name, default=''):
        return (self.env['ir.config_parameter'].sudo().get_param(name) or default).strip()

    @api.model
    def _provider(self):
        value = self._param(PARAM_PROVIDER, 'osm').lower()
        return value if value in PROVIDERS else 'osm'

    @api.model
    def _api_key(self):
        """Key of the chosen provider ('' when none is needed or set)."""
        return self._param(PARAM_GOONG_KEY) if self._provider() == 'goong' else ''

    @api.model
    def _get_json(self, name, url, params=None, headers=None):
        """GET and decode JSON. Errors say the provider and the reason, never the URL (it may carry a key)."""
        try:
            response = requests.get(url, params=params, headers=headers, timeout=15)
        except requests.RequestException as error:
            raise ValueError('%s not reachable (%s)' % (name, error.__class__.__name__))
        try:
            data = response.json()
        except ValueError:
            data = {}
        if response.status_code != 200:
            reason = data.get('message') or data.get('error') or data.get('status') or 'HTTP %s' % response.status_code
            raise ValueError('%s refused the request: %s' % (name, str(reason)[:200]))
        return data

    @api.model
    def _address_variants(self, address):
        """Addresses to try on the map, best first (at most MAX_VARIANTS).
        The map data does not know our English wording: the words ward / district / commune / province / city and a repeated
        "Vietnam" are removed; an industrial park is also tried by its Vietnamese form (Khu cong nghiep ...); then the address
        is tried without its first parts (house number, building, plot)."""
        parts = []
        for part in address.split(','):
            part = re.sub(r'\b(ward|district|commune|province|city|town)\b', '', part, flags=re.I)
            part = re.sub(r'\s+', ' ', part).strip()
            if part and part.lower() not in [p.lower() for p in parts if p.lower() == 'vietnam']:
                parts.append(part)
        variants = []
        for i in range(0, max(len(parts) - 1, 1)):
            rest = parts[i:]
            for j, part in enumerate(rest):
                match = re.match(r'(.+?)\s+industrial\s+(?:park|zone)\b\s*(.*)', part, flags=re.I)
                if match:
                    name = ('Khu cong nghiep %s %s' % match.groups()).strip()
                    variants.append(', '.join([name] + rest[-2:]))
                    variants.append(name)
                    break
            variants.append(', '.join(rest))
        seen, result = set(), []
        for variant in variants:
            if variant.lower() not in seen:
                seen.add(variant.lower())
                result.append(variant)
        return result[:MAX_VARIANTS]

    # ---- OpenStreetMap
    @api.model
    def _osm_geocode(self, address):
        base = self._param(PARAM_NOMINATIM, NOMINATIM_URL).rstrip('/')
        for variant in self._address_variants(address):
            data = self._get_json('OpenStreetMap geocoder', base + '/search',
                                  params={'q': variant, 'format': 'json', 'limit': 1, 'countrycodes': 'vn'},
                                  headers={'User-Agent': USER_AGENT})
            time.sleep(1.1)  # public Nominatim policy: at most 1 request a second
            if data:
                return float(data[0]['lat']), float(data[0]['lon'])
        raise ValueError('Address not found on the map: %s' % address[:120])

    @api.model
    def _osm_route(self, start, end):
        base = self._param(PARAM_OSRM, OSRM_URL).rstrip('/')
        url = '%s/route/v1/driving/%s,%s;%s,%s' % (base, start[1], start[0], end[1], end[0])
        data = self._get_json('OpenStreetMap router', url, params={'overview': 'false'}, headers={'User-Agent': USER_AGENT})
        routes = data.get('routes') or []
        if data.get('code') != 'Ok' or not routes:
            raise ValueError('OpenStreetMap found no driving route between the two addresses')
        return routes[0]['distance'], routes[0].get('duration') or 0

    # ---- Goong
    @api.model
    def _goong_geocode(self, address, key):
        for variant in self._address_variants(address):
            data = self._get_json('Goong geocoder', GOONG_URL + '/geocode', params={'address': variant, 'api_key': key})
            results = data.get('results') or []
            if results:
                location = results[0]['geometry']['location']
                return float(location['lat']), float(location['lng'])
        raise ValueError('Address not found on the map: %s' % address[:120])

    @api.model
    def _goong_route(self, start, end, key):
        data = self._get_json('Goong router', GOONG_URL + '/Direction', params={
            'origin': '%s,%s' % start, 'destination': '%s,%s' % end, 'vehicle': 'car', 'api_key': key})
        routes = data.get('routes') or []
        legs = routes[0].get('legs') if routes else None
        if not legs:
            raise ValueError('Goong found no driving route between the two addresses')
        distance = sum(leg['distance']['value'] for leg in legs)
        duration = sum(leg['duration']['value'] for leg in legs)
        return distance, duration

    @api.model
    def _fetch(self, origin, destination, key):
        """Returns (meters, seconds) or raises ValueError with a short reason (never contains the key)."""
        if self._provider() == 'goong':
            return self._goong_route(self._goong_geocode(origin, key), self._goong_geocode(destination, key), key)
        return self._osm_route(self._osm_geocode(origin), self._osm_geocode(destination))

    @api.model
    def get_km(self, origin, destination, force=False):
        """(km, message): km is None when it cannot be computed, message then says why (shown on the form).
        A success is cached CACHE_DAYS, a failure FAILURE_MINUTES (force=True ignores that memory)."""
        origin, destination = (origin or '').strip(), (destination or '').strip()
        if not origin:
            return None, 'Office address not set'
        if not destination:
            return None, 'The project has no address'
        now = fields.Datetime.now()
        cached = self.sudo().search([('origin', '=', origin), ('destination', '=', destination)], limit=1)
        if cached and not cached.failure and cached.fetched_at > now - timedelta(days=CACHE_DAYS):
            return cached.distance_km, ''
        if cached and cached.failure and not force and cached.fetched_at > now - timedelta(minutes=FAILURE_MINUTES):
            return None, cached.failure
        key = self._api_key()
        if self._provider() == 'goong' and not key:
            return None, 'Goong API key not set (System Parameter %s)' % PARAM_GOONG_KEY
        try:
            meters, seconds = self._fetch(origin, destination, key)
        except (ValueError, KeyError, TypeError) as error:
            _logger.warning("Route distance %r -> %r failed: %s", origin, destination, error)
            message = str(error) if isinstance(error, ValueError) else 'Unexpected answer of the map service'
            vals = {'distance_km': 0.0, 'duration_min': 0, 'fetched_at': now, 'failure': message}
            if cached:
                cached.write(vals)
            else:
                self.sudo().create(dict(vals, origin=origin, destination=destination))
            return None, message
        vals = {'distance_km': round(meters / 1000.0, 1), 'duration_min': int(round(seconds / 60.0)),
                'fetched_at': now, 'failure': False}
        if cached:
            cached.write(vals)
        else:
            self.sudo().create(dict(vals, origin=origin, destination=destination))
        return vals['distance_km'], ''
