from __future__ import annotations

import uuid

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import logging
import os
import secrets
import smtplib

from fastapi import APIRouter, HTTPException
from passlib.context import CryptContext
from pydantic import BaseModel, Field

from psycopg2 import errors
from psycopg2.extras import Json

from app.db import get_psycopg_conn

router = APIRouter()
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
logger = logging.getLogger(__name__)


def _send_reset_email(recipient: str, otp: str) -> None:
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "")
    smtp_tls = os.getenv("SMTP_TLS", "true").lower() != "false"

    if not smtp_host or not smtp_user or not smtp_password:
        raise RuntimeError("SMTP is not configured")

    message = EmailMessage()
    message["From"] = smtp_from
    message["To"] = recipient
    message["Subject"] = "ToPFeed password reset code"
    message.set_content(
        "Your ToPFeed password reset code is:\n\n"
        f"{otp}\n\n"
        "This code expires in 15 minutes.\n"
        "If you did not request this, you can ignore this email."
    )

    with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as smtp:
        if smtp_tls:
            smtp.starttls()
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(message)


class UserPreferences(BaseModel):
    categories: list[str] = Field(default_factory=list)
    subcategories: list[str] = Field(default_factory=list)


class UserCreate(BaseModel):
    user_id: str | None = None
    full_name: str
    email: str
    password: str
    location: str | None = None
    profile_image_url: str | None = None
    theme_preference: str = "light"
    preferences: UserPreferences = Field(default_factory=UserPreferences)


class UserUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    location: str | None = None
    profile_image_url: str | None = None
    theme_preference: str | None = None
    preferences: UserPreferences | None = None


class UserOut(BaseModel):
    user_id: str
    full_name: str | None = None
    email: str | None = None
    location: str | None = None
    profile_image_url: str | None = None
    theme_preference: str
    preferences: UserPreferences
    created_at: str | None = None
    updated_at: str | None = None


@router.post("/users/signup", response_model=UserOut)
def create_user(payload: UserCreate):
    user_id = payload.user_id or f"U{uuid.uuid4().hex[:8]}"
    password_hash = pwd_context.hash(payload.password)

    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
            exists = cur.fetchone()
        if exists:
            raise HTTPException(status_code=409, detail="user_id already exists")

        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (user_id, full_name, email, password_hash, location, profile_image_url, theme_preference, preferences)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING user_id, full_name, email, location, theme_preference,
                              profile_image_url, preferences, created_at, updated_at
                    """,
                    (
                        user_id,
                        payload.full_name,
                        payload.email,
                        password_hash,
                        payload.location,
                        payload.profile_image_url,
                        payload.theme_preference,
                        Json(payload.preferences.model_dump()),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        except errors.UniqueViolation as exc:
            conn.rollback()
            constraint = getattr(exc.diag, "constraint_name", "") if exc.diag else ""
            if constraint in {"users_pkey"}:
                raise HTTPException(status_code=409, detail="user_id already exists")
            raise HTTPException(status_code=409, detail="email already exists")
        return UserOut(
            user_id=row[0],
            full_name=row[1],
            email=row[2],
            location=row[3],
            theme_preference=row[4],
            profile_image_url=row[5],
            preferences=UserPreferences(**(row[6] or {})),
            created_at=row[7].isoformat() if row[7] else None,
            updated_at=row[8].isoformat() if row[8] else None,
        )
    finally:
        conn.close()


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(user_id: str):
    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, full_name, email, location, theme_preference,
                       profile_image_url, preferences, created_at, updated_at
                FROM users
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="user not found")
        if not row[3]:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET location = %s, updated_at = NOW() WHERE user_id = %s",
                    ("unknown", user_id),
                )
            conn.commit()
            row = (row[0], row[1], row[2], "unknown", row[4], row[5], row[6], row[7], row[8])
        return UserOut(
            user_id=row[0],
            full_name=row[1],
            email=row[2],
            location=row[3],
            theme_preference=row[4],
            profile_image_url=row[5],
            preferences=UserPreferences(**(row[6] or {})),
            created_at=row[7].isoformat() if row[7] else None,
            updated_at=row[8].isoformat() if row[8] else None,
        )
    finally:
        conn.close()


class UserLogin(BaseModel):
    email: str
    password: str


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetVerify(BaseModel):
    email: str
    otp: str
    new_password: str


class PasswordResetOtpVerify(BaseModel):
    email: str
    otp: str


@router.post("/users/login", response_model=UserOut)
def login_user(payload: UserLogin):
    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, full_name, email, password_hash, location, theme_preference,
                       profile_image_url, preferences, created_at, updated_at
                FROM users
                WHERE email = %s
                """,
                (payload.email,),
            )
            row = cur.fetchone()
        if not row or not row[3]:
            raise HTTPException(status_code=401, detail="invalid credentials")
        if not pwd_context.verify(payload.password, row[3]):
            raise HTTPException(status_code=401, detail="invalid credentials")
        if not row[4]:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE users SET location = %s, updated_at = NOW() WHERE email = %s",
                    ("unknown", payload.email),
                )
            conn.commit()
            row = (row[0], row[1], row[2], row[3], "unknown", row[5], row[6], row[7], row[8], row[9])
        return UserOut(
            user_id=row[0],
            full_name=row[1],
            email=row[2],
            location=row[4],
            theme_preference=row[5],
            profile_image_url=row[6],
            preferences=UserPreferences(**(row[7] or {})),
            created_at=row[8].isoformat() if row[8] else None,
            updated_at=row[9].isoformat() if row[9] else None,
        )
    finally:
        conn.close()


@router.post("/users/password/reset/request")
def request_password_reset(payload: PasswordResetRequest):
    email = payload.email.strip().lower()
    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE email = %s", (email,))
            exists = cur.fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="email not found")

        otp = f"{secrets.randbelow(1000000):06d}"
        otp_hash = pwd_context.hash(otp)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO password_reset_tokens (email, otp_hash, expires_at, used_at, created_at)
                VALUES (%s, %s, %s, NULL, NOW())
                ON CONFLICT (email)
                DO UPDATE SET otp_hash = EXCLUDED.otp_hash,
                              expires_at = EXCLUDED.expires_at,
                              used_at = NULL,
                              created_at = NOW()
                """,
                (email, otp_hash, expires_at),
            )
        conn.commit()
        try:
            _send_reset_email(email, otp)
        except RuntimeError as exc:
            logger.exception("SMTP configuration missing")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("SMTP send failed")
            raise HTTPException(status_code=502, detail="failed to send otp email") from exc
        return {"status": "otp_sent"}
    finally:
        conn.close()


@router.post("/users/password/reset/verify", response_model=UserOut)
def verify_password_reset(payload: PasswordResetVerify):
    email = payload.email.strip().lower()
    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT t.otp_hash, t.expires_at, t.used_at, u.password_hash
                FROM password_reset_tokens t
                JOIN users u ON u.email = t.email
                WHERE t.email = %s
                """,
                (email,),
            )
            token_row = cur.fetchone()
        if not token_row:
            raise HTTPException(status_code=404, detail="reset token not found")
        otp_hash, expires_at, used_at, existing_hash = token_row
        if used_at is not None:
            raise HTTPException(status_code=400, detail="otp already used")
        if expires_at is None or expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="otp expired")
        if not pwd_context.verify(payload.otp, otp_hash):
            raise HTTPException(status_code=401, detail="invalid otp")

        if existing_hash and pwd_context.verify(payload.new_password, existing_hash):
            raise HTTPException(status_code=400, detail="password cannot be the same as previous")
        new_hash = pwd_context.hash(payload.new_password)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET password_hash = %s
                WHERE email = %s
                RETURNING user_id, full_name, email, location, theme_preference,
                          profile_image_url, preferences, created_at, updated_at
                """,
                (new_hash, email),
            )
            user_row = cur.fetchone()
            cur.execute(
                "UPDATE password_reset_tokens SET used_at = NOW() WHERE email = %s",
                (email,),
            )
        conn.commit()
        if not user_row:
            raise HTTPException(status_code=404, detail="user not found")
        return UserOut(
            user_id=user_row[0],
            full_name=user_row[1],
            email=user_row[2],
            location=user_row[3],
            theme_preference=user_row[4],
            profile_image_url=user_row[5],
            preferences=UserPreferences(**(user_row[6] or {})),
            created_at=user_row[7].isoformat() if user_row[7] else None,
            updated_at=user_row[8].isoformat() if user_row[8] else None,
        )
    finally:
        conn.close()


@router.post("/users/password/reset/otp/verify")
def verify_password_reset_otp(payload: PasswordResetOtpVerify):
    email = payload.email.strip().lower()
    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT otp_hash, expires_at, used_at
                FROM password_reset_tokens
                WHERE email = %s
                """,
                (email,),
            )
            token_row = cur.fetchone()
        if not token_row:
            raise HTTPException(status_code=404, detail="reset token not found")
        otp_hash, expires_at, used_at = token_row
        if used_at is not None:
            raise HTTPException(status_code=400, detail="otp already used")
        if expires_at is None or expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="otp expired")
        if not pwd_context.verify(payload.otp, otp_hash):
            raise HTTPException(status_code=401, detail="invalid otp")
        return {"status": "otp_valid"}
    finally:
        conn.close()


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: str, payload: UserUpdate):
    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
            exists = cur.fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="user not found")

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE users
                SET full_name = COALESCE(%s, full_name),
                    email = COALESCE(%s, email),
                    location = COALESCE(%s, location),
                    profile_image_url = COALESCE(%s, profile_image_url),
                    theme_preference = COALESCE(%s, theme_preference),
                    preferences = COALESCE(%s, preferences),
                    updated_at = NOW()
                WHERE user_id = %s
                RETURNING user_id, full_name, email, location, theme_preference,
                          profile_image_url, preferences, created_at, updated_at
                """,
                (
                    payload.full_name,
                    payload.email,
                    payload.location,
                    payload.profile_image_url,
                    payload.theme_preference,
                    Json(payload.preferences.model_dump()) if payload.preferences else None,
                    user_id,
                ),
            )
            row = cur.fetchone()
        conn.commit()
        return UserOut(
            user_id=row[0],
            full_name=row[1],
            email=row[2],
            location=row[3],
            theme_preference=row[4],
            profile_image_url=row[5],
            preferences=UserPreferences(**(row[6] or {})),
            created_at=row[7].isoformat() if row[7] else None,
            updated_at=row[8].isoformat() if row[8] else None,
        )
    finally:
        conn.close()
