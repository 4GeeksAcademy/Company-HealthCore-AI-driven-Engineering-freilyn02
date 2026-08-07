"""Repository layer: all TinyDB query logic for suppliers lives here,
so main.py stays free of duplicated query code.
"""
from datetime import datetime, timezone
from typing import List, Optional

from tinydb import Query

from database import suppliers_table
from models import SupplierCreate, SupplierRatePatch, SupplierStatusPatch

SupplierQuery = Query()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_by_name_and_country(name: str, country: str) -> Optional[dict]:
    """Natural unique key used by the seeder to avoid duplicate inserts."""
    return suppliers_table.get(
        (SupplierQuery.name == name) & (SupplierQuery.country == country)
    )


def create_supplier(data: SupplierCreate) -> dict:
    record = data.model_dump(mode="json")
    record["updated_at"] = _now_iso()
    doc_id = suppliers_table.insert(record)
    return {**record, "id": doc_id}


def list_suppliers(country: Optional[str] = None, category: Optional[str] = None) -> List[dict]:
    query = None
    if country:
        query = SupplierQuery.country == country
    if category:
        cat_query = SupplierQuery.categories.any([category])
        query = cat_query if query is None else (query & cat_query)

    docs = suppliers_table.search(query) if query is not None else suppliers_table.all()
    return [{**doc, "id": doc.doc_id} for doc in docs]


def get_supplier(supplier_id: int) -> Optional[dict]:
    doc = suppliers_table.get(doc_id=supplier_id)
    if doc is None:
        return None
    return {**doc, "id": doc.doc_id}


def update_rate(supplier_id: int, patch: SupplierRatePatch) -> Optional[dict]:
    if suppliers_table.get(doc_id=supplier_id) is None:
        return None
    suppliers_table.update({"rate": patch.rate, "updated_at": _now_iso()}, doc_ids=[supplier_id])
    return get_supplier(supplier_id)


def update_status(supplier_id: int, patch: SupplierStatusPatch) -> Optional[dict]:
    if suppliers_table.get(doc_id=supplier_id) is None:
        return None
    suppliers_table.update(
        {"status": patch.status.value, "updated_at": _now_iso()}, doc_ids=[supplier_id]
    )
    return get_supplier(supplier_id)


def delete_supplier(supplier_id: int) -> bool:
    if suppliers_table.get(doc_id=supplier_id) is None:
        return False
    suppliers_table.remove(doc_ids=[supplier_id])
    return True