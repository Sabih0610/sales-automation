"""
salesnav_extractor.py

Turns a captured Sales Navigator search JSON payload into clean lead dicts.
Walks the whole JSON tree and picks objects that look like a person, then reads
fields by trying several known key names, so a LinkedIn field rename does not
break everything at once. This is the same logic proven against real payloads.
"""

import re

FULLNAME_KEYS = ("fullName", "full_name")
FIRST_KEYS = ("firstName", "first_name")
LAST_KEYS = ("lastName", "last_name")
TITLE_KEYS = ("title", "currentRole", "occupation", "headline", "jobTitle")
COMPANY_KEYS = ("companyName", "company", "currentCompany", "organizationName")
LOCATION_KEYS = ("geoRegion", "location", "geographicArea", "displayLocation", "locationName", "addressLine")
URL_KEYS = ("navigationUrl", "navigationURL", "profileUrl", "publicProfileUrl")
URN_KEYS = ("entityUrn", "objectUrn", "salesProfileUrn", "profileUrn")
POSITION_KEYS = ("currentPositions", "positions", "currentPosition", "experience")


def _get(d, keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return None


def _first(value):
    if isinstance(value, list) and value:
        return value[0]
    return value


def _title_company_from_positions(obj):
    for key in POSITION_KEYS:
        pos = _first(obj.get(key))
        if isinstance(pos, dict):
            title = _get(pos, ("title", "name", "role"))
            company = _get(pos, ("companyName", "company", "name", "organizationName"))
            return title, company
    return None, None


def _profile_url(obj):
    url = _get(obj, URL_KEYS)
    if url:
        if str(url).startswith("/"):
            url = "https://www.linkedin.com" + str(url)
        return str(url).split("?")[0]
    urn = _get(obj, URN_KEYS)
    if isinstance(urn, str) and urn:
        match = re.search(r"\(([^)]+)\)", urn)
        inner = match.group(1) if match else urn.split(":")[-1]
        return "https://www.linkedin.com/sales/lead/" + inner
    return ""


def _looks_like_lead(obj):
    if not isinstance(obj, dict):
        return False
    has_name = any(obj.get(k) for k in FULLNAME_KEYS) or any(obj.get(k) for k in FIRST_KEYS)
    if not has_name:
        return False
    has_context = (
        any(k in obj for k in POSITION_KEYS)
        or any(k in obj for k in TITLE_KEYS)
        or any(k in obj for k in COMPANY_KEYS)
        or any(k in obj for k in URL_KEYS + URN_KEYS)
    )
    return has_context


def _walk(node, out):
    if isinstance(node, dict):
        if _looks_like_lead(node):
            out.append(node)
        for value in node.values():
            _walk(value, out)
    elif isinstance(node, list):
        for value in node:
            _walk(value, out)


def extract_salesnav_leads(payload):
    found = []
    _walk(payload, found)
    leads = []
    seen = set()
    for obj in found:
        first = str(_get(obj, FIRST_KEYS) or "").strip()
        last = str(_get(obj, LAST_KEYS) or "").strip()
        full = str(_get(obj, FULLNAME_KEYS) or f"{first} {last}").strip()
        if not full or len(full) < 2:
            continue
        pos_title, pos_company = _title_company_from_positions(obj)
        title = str(pos_title or _get(obj, TITLE_KEYS) or "").strip()
        company = str(pos_company or _get(obj, COMPANY_KEYS) or "").strip()
        location = str(_get(obj, LOCATION_KEYS) or "").strip()
        url = _profile_url(obj)
        key = url or f"{full.lower()}|{company.lower()}"
        if key in seen:
            continue
        seen.add(key)
        leads.append({
            "full_name": full,
            "first_name": first,
            "last_name": last,
            "title": title,
            "company": company,
            "location": location,
            "linkedin_url": url,
        })
    return leads
