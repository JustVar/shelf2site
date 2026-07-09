"""Shared effective-visibility helper for the deployment map.

Single source of truth for what appears on the map and in every metric
derived from it. A unit is visible only when ALL of these hold:

  1. no unit-level curation row hides it (map_visibility level='unit',
     key 'item:{id}' or 'edge_box:{id}'); for legacy edge boxes the
     edge_boxes.show_on_map boolean is honored in addition,
  2. its site is not hidden (level='site', normalized site string),
  3. its customer is not hidden (level='customer', normalized string),
  4. it is not tied to a sensitive order the viewer may not see
     (CustomerOrder.is_sensitive vs user.has_sensitive_customers_access,
     same rule the fulfillment board applies).

Curation rows mean HIDDEN by presence; unhide deletes the row. This
module replaces the three copy-pasted show_on_map filters the old
map route carried — add new visibility rules HERE, nowhere else.
"""

from .models import MapVisibility


def norm_key(value):
    """Normalize a free-text customer/site identity for curation keys."""
    return (value or "").strip().lower()


def load_hidden(db):
    """One query: the full hidden-set, grouped by level."""
    hidden = {"customer": set(), "site": set(), "unit": set()}
    for row in db.query(MapVisibility).all():
        if row.level in hidden:
            hidden[row.level].add(row.key)
    return hidden


def unit_visible(hidden, unit_key, customer, site, is_sensitive, can_see_sensitive):
    """Effective visibility for one unit. See module docstring for rules."""
    if unit_key in hidden["unit"]:
        return False
    if customer and norm_key(customer) in hidden["customer"]:
        return False
    if site and norm_key(site) in hidden["site"]:
        return False
    if is_sensitive and not can_see_sensitive:
        return False
    return True
