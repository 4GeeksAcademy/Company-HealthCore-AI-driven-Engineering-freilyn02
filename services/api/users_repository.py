"""Repository layer: all TinyDB query logic for users and profiles
lives here, so main.py and the auth routes stay free of duplicated
query code.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from tinydb import Query

from app.core.security import (
    generate_reset_token,
    hash_password,
    hash_reset_token,
    verify_password,
)
from database import password_resets_table, profiles_table, users_table
from models import ProfileUpdate, UserCreate, UserCredentialsUpdate

UserQuery = Query()
ResetQuery = Query()
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

# ---- Password Reset ----

RESET_TOKEN_TTL_MINUTES = 30


def request_password_reset(email: str) -> Optional[str]:
    """If the email matches a user, create a reset token and return the
    raw token (for the email link). Returns None if no user matches —
    the caller must still respond 200 either way, to avoid leaking
    which emails are registered.
    """
    user = find_user_by_email(email)
    if user is None:
        return None
    raw_token = generate_reset_token()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)
    ).isoformat()
    password_resets_table.insert(
        {
            "user_id": user["id"],
            "token_hash": hash_reset_token(raw_token),
            "expires_at": expires_at,
            "used": False,
        }
    )
    return raw_token


def reset_password(token: str, new_password: str) -> bool:
    """Validate the reset token and update the user's password.
    Returns False if the token is invalid, expired, or already used.
    """
    token_hash = hash_reset_token(token)
    record = password_resets_table.get(ResetQuery.token_hash == token_hash)
    if record is None or record["used"]:
        return False
    if datetime.fromisoformat(record["expires_at"]) < datetime.now(timezone.utc):
        return False

    users_table.update(
        {"hashed_password": hash_password(new_password)}, doc_ids=[record["user_id"]]
    )
    password_resets_table.update({"used": True}, doc_ids=[record.doc_id])
    return True


def change_password(user_id: int, current_password: str, new_password: str) -> bool:
    """Verify the current password and update it. Returns False if the
    current password doesn't match.
    """
    user = users_table.get(doc_id=user_id)
    if user is None or not verify_password(current_password, user["hashed_password"]):
        return False
    users_table.update({"hashed_password": hash_password(new_password)}, doc_ids=[user_id])
    return True