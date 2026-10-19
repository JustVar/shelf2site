"""Sensitive customers: one rule for every route.

An order marked sensitive is visible only to users with sensitive-customer
access (user.has_sensitive_customers_access). For everyone else the order,
and everything hanging off it (its units' provisioning rows, documents,
certifications, site visits, purchase orders), does not exist: reads answer
404 or leave it out of lists, and writes answer 404 as well.

Site records are not orders and are not hidden: a site named after a
customer stays in the sites list. What is hidden is the order and its work.
"""
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .models import CustomerOrder, DeviceProvisioning


def can_see_order(user, order) -> bool:
    return order is not None and (not order.is_sensitive or user.has_sensitive_customers_access)


def visible_order(db: Session, user, order_id):
    """The order, or None when it does not exist or is hidden from this user."""
    if order_id is None:
        return None
    try:
        oid = int(order_id)
    except (TypeError, ValueError):
        return None
    order = db.query(CustomerOrder).filter(CustomerOrder.id == oid).first()
    return order if can_see_order(user, order) else None


def hidden_order_ids(db: Session, user) -> set:
    """Ids of the orders this user may not see (empty for users with access)."""
    if user.has_sensitive_customers_access:
        return set()
    return {oid for (oid,) in db.query(CustomerOrder.id).filter(CustomerOrder.is_sensitive.is_(True)).all()}


def provisioning_hidden(db: Session, user, prov) -> bool:
    """True when the provisioning row belongs to an order hidden from this user."""
    if prov is None or prov.customer_order_id is None or user.has_sensitive_customers_access:
        return False
    order = db.query(CustomerOrder).filter(CustomerOrder.id == prov.customer_order_id).first()
    return order is not None and bool(order.is_sensitive)


def visible_provisioning(db: Session, user, prov_id):
    """The provisioning row, or None when missing or on a hidden order."""
    try:
        pid = int(prov_id)
    except (TypeError, ValueError):
        return None
    prov = db.query(DeviceProvisioning).filter(DeviceProvisioning.id == pid).first()
    if prov is None or provisioning_hidden(db, user, prov):
        return None
    return prov


def without_hidden_provisioning(query, db: Session, user):
    """Filter a DeviceProvisioning query down to rows this user may see."""
    hidden = hidden_order_ids(db, user)
    if not hidden:
        return query
    return query.filter(or_(
        DeviceProvisioning.customer_order_id.is_(None),
        ~DeviceProvisioning.customer_order_id.in_(hidden),
    ))
