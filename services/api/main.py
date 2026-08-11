"""FastAPI app: HealthCore Supplier Directory - Lightweight Storage API."""
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi import Query as QueryParam
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm

import repository
import users_repository
from app.core.deps import get_current_user
from app.core.security import create_access_token, verify_password
from models import (
    ProfileOut,
    ProfileUpdate,
    SupplierCreate,
    SupplierOut,
    SupplierRatePatch,
    SupplierStatusPatch,
    TokenOut,
    UserCreate,
    UserCredentialsUpdate,
    UserOut,
    UserWithProfileOut,
)

app = FastAPI(title="HealthCore Supplier Directory API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Auth ----
@app.post("/auth/login", response_model=TokenOut)
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = users_repository.find_user_by_email(form_data.username)
    if user is None or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    token = create_access_token({"sub": str(user["id"])})
    return {"access_token": token, "token_type": "bearer"}


@app.get("/auth/me", response_model=UserWithProfileOut)
def read_current_user(current_user: dict = Depends(get_current_user)):
    profile = users_repository.get_profile_by_user_id(current_user["id"])
    return {**current_user, "profile": profile}


# ---- Users ----
@app.post("/users", response_model=UserOut, status_code=201)
def register_user(payload: UserCreate):
    if users_repository.find_user_by_email(payload.email) is not None:
        raise HTTPException(status_code=400, detail="Email already registered")
    return users_repository.create_user(payload)


@app.get("/users", response_model=List[UserOut])
def list_users(current_user: dict = Depends(get_current_user)):
    return users_repository.list_users()


@app.get("/users/{user_id}", response_model=UserOut)
def get_user_route(user_id: int, current_user: dict = Depends(get_current_user)):
    user = users_repository.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.put("/users/{user_id}", response_model=UserOut)
def update_user_route(
    user_id: int, payload: UserCredentialsUpdate, current_user: dict = Depends(get_current_user)
):
    is_self = current_user["id"] == user_id
    is_admin = current_user["role"] == "admin"
    if not is_self and not is_admin:
        raise HTTPException(status_code=403, detail="Not authorized to update this user")
    if payload.role is not None and not is_admin:
        raise HTTPException(status_code=403, detail="Only admins can change role")

    updated = users_repository.update_user_credentials(user_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")
    return updated


@app.delete("/users/{user_id}", status_code=204)
def delete_user_route(user_id: int, current_user: dict = Depends(get_current_user)):
    is_self = current_user["id"] == user_id
    is_admin = current_user["role"] == "admin"
    if not is_self and not is_admin:
        raise HTTPException(status_code=403, detail="Not authorized to delete this user")

    deleted = users_repository.delete_user(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")


# ---- Profiles ----
@app.get("/profiles/me", response_model=ProfileOut)
def read_my_profile(current_user: dict = Depends(get_current_user)):
    profile = users_repository.get_profile_by_user_id(current_user["id"])
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@app.put("/profiles/me", response_model=ProfileOut)
def update_my_profile(payload: ProfileUpdate, current_user: dict = Depends(get_current_user)):
    updated = users_repository.update_profile(current_user["id"], payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return updated


# ---- Suppliers (protected) ----
@app.post("/suppliers", response_model=SupplierOut, status_code=201)
def create_supplier(payload: SupplierCreate, current_user: dict = Depends(get_current_user)):
    return repository.create_supplier(payload)


@app.get("/suppliers", response_model=List[SupplierOut])
def list_suppliers(
    country: Optional[str] = QueryParam(default=None),
    category: Optional[str] = QueryParam(default=None),
    current_user: dict = Depends(get_current_user),
):
    return repository.list_suppliers(country=country, category=category)


@app.get("/suppliers/{supplier_id}", response_model=SupplierOut)
def get_supplier(supplier_id: int, current_user: dict = Depends(get_current_user)):
    supplier = repository.get_supplier(supplier_id)
    if supplier is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return supplier


@app.patch("/suppliers/{supplier_id}/rate", response_model=SupplierOut)
def patch_rate(
    supplier_id: int, payload: SupplierRatePatch, current_user: dict = Depends(get_current_user)
):
    updated = repository.update_rate(supplier_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return updated


@app.patch("/suppliers/{supplier_id}/status", response_model=SupplierOut)
def patch_status(
    supplier_id: int, payload: SupplierStatusPatch, current_user: dict = Depends(get_current_user)
):
    updated = repository.update_status(supplier_id, payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return updated


@app.delete("/suppliers/{supplier_id}", status_code=204)
def delete_supplier(supplier_id: int, current_user: dict = Depends(get_current_user)):
    deleted = repository.delete_supplier(supplier_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Supplier not found")