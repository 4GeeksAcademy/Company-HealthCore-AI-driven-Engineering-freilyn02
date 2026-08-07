"""FastAPI app: HealthCore Supplier Directory - Lightweight Storage API."""
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi import Query as QueryParam
from fastapi.middleware.cors import CORSMiddleware

import repository
from models import SupplierCreate, SupplierOut, SupplierRatePatch, SupplierStatusPatch

app = FastAPI(title="HealthCore Supplier Directory API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/suppliers", response_model=SupplierOut, status_code=201)
def create_supplier(payload: SupplierCreate):
    return repository.create_supplier(payload)


@app.get("/suppliers", response_model=List[SupplierOut])
def list_suppliers(
    country: Optional[str] = QueryParam(default=None),
    category: Optional[str] = QueryParam(default=None),
):
    return repository.list_suppliers(country=country, category=category)


@app.get("/suppliers/{supplier_id}", response_model=SupplierOut)
def get_supplier(supplier_id: int):
    supplier = repository.get_supplier(supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return supplier


@app.patch("/suppliers/{supplier_id}/rate", response_model=SupplierOut)
def patch_rate(supplier_id: int, payload: SupplierRatePatch):
    updated = repository.update_rate(supplier_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return updated


@app.patch("/suppliers/{supplier_id}/status", response_model=SupplierOut)
def patch_status(supplier_id: int, payload: SupplierStatusPatch):
    updated = repository.update_status(supplier_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return updated


@app.delete("/suppliers/{supplier_id}", status_code=204)
def delete_supplier(supplier_id: int):
    deleted = repository.delete_supplier(supplier_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Supplier not found")