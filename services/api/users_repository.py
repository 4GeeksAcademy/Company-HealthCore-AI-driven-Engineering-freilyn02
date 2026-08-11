"""Repository layer: all TinyDB query logic for users and profiles
lives here, so main.py and the auth routes stay free of duplicated
query code.
"""
from datetime import datetime, timezone
from typing import List, Optional

from tinydb import Query

from app.core.security import hash_password
from database import profiles_table, users_table
from models import ProfileUpdate, UserCreate, UserCredentialsUpdate

UserQuery = Query()
ProfileQuery = Query()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- Users ----
def find_user_by_email(email: str) -> Optional[dict]:
    doc = users_table.get(UserQuery.email == email)
    if doc is None:
        return None
    return {**doc, "id": doc.doc_id}


def create_user(data: UserCreate) -> dict:
    """Create a User and its linked Profile in the same operation."""
    user_record = {
        "email": data.email,
        "hashed_password": hash_password(data.password),
        "is_active": True,
        "role": "user",
        "created_at": _now_iso(),
    }
    user_id = users_table.insert(user_record)

    profile_record = {
        "user_id": user_id,
        "name": data.name,
        "phone": data.phone,
        "address": data.address,
    }
    profiles_table.insert(profile_record)

    return {**user_record, "id": user_id}


def list_users() -> List[dict]:
    return [{**doc, "id": doc.doc_id} for doc in users_table.all()]


def get_user(user_id: int) -> Optional[dict]:
    doc = users_table.get(doc_id=user_id)
    if doc is None:
        return None
    return {**doc, "id": doc.doc_id}


def update_user_credentials(user_id: int, patch: UserCredentialsUpdate) -> Optional[dict]:
    if users_table.get(doc_id=user_id) is None:
        return None
    updates = patch.model_dump(exclude_none=True)
    if not updates:
        return get_user(user_id)
    users_table.update(updates, doc_ids=[user_id])
    return get_user(user_id)


def delete_user(user_id: int) -> bool:
    """Delete a user and its linked profile."""
    if users_table.get(doc_id=user_id) is None:
        return False
    users_table.remove(doc_ids=[user_id])
    profile = profiles_table.get(ProfileQuery.user_id == user_id)
    if profile is not None:
        profiles_table.remove(doc_ids=[profile.doc_id])
    return True


# ---- Profiles ----
def get_profile_by_user_id(user_id: int) -> Optional[dict]:
    doc = profiles_table.get(ProfileQuery.user_id == user_id)
    if doc is None:
        return None
    return {**doc, "id": doc.doc_id}


def update_profile(user_id: int, patch: ProfileUpdate) -> Optional[dict]:
    profile = profiles_table.get(ProfileQuery.user_id == user_id)
    if profile is None:
        return None
    updates = patch.model_dump(exclude_none=True)
    if updates:
        profiles_table.update(updates, doc_ids=[profile.doc_id])
    return get_profile_by_user_id(user_id)