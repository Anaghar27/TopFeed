from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import os
import secrets
import smtplib

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from psycopg2 import errors
from psycopg2.extras import Json

from app.db import get_psycopg_conn

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

router = APIRouter(prefix="/admin", tags=["admin"])


def _get_admin_allowlist() -> set[str]:
    raw = os.getenv("ADMIN_EMAILS", "")
    emails = {email.strip().lower() for email in raw.split(",") if email.strip()}
    return emails


def _get_jwt_secret() -> str:
    secret = os.getenv("ADMIN_JWT_SECRET")
    if not secret:
        raise HTTPException(status_code=500, detail="admin jwt secret not configured")
    return secret


def _get_jwt_ttl_minutes() -> int:
    return int(os.getenv("ADMIN_JWT_TTL_MIN", "60"))


def _send_login_email(recipient: str, otp: str) -> None:
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "")
    smtp_tls = os.getenv("SMTP_TLS", "true").lower() != "false"

    if not smtp_host or not smtp_user or not smtp_password:
        raise HTTPException(status_code=500, detail="SMTP is not configured")

    message = EmailMessage()
    message["From"] = smtp_from
    message["To"] = recipient
    message["Subject"] = "ToPFeed admin login code"
    message.set_content(
        "Your ToPFeed admin login code is:\n\n"
        f"{otp}\n\n"
        "This code expires in 10 minutes.\n"
        "If you did not request this, you can ignore this email."
    )

    with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as smtp:
        if smtp_tls:
            smtp.starttls()
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(message)


def _issue_admin_token(email: str) -> tuple[str, datetime]:
    ttl_minutes = _get_jwt_ttl_minutes()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    payload = {
        "sub": email,
        "exp": expires_at,
    }
    token = jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")
    return token, expires_at


def require_admin_token(authorization: str = Header(..., alias="Authorization")) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="invalid authorization header")
    token = authorization.replace("Bearer ", "", 1).strip()
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="admin token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="invalid admin token") from exc

    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=401, detail="invalid admin token")

    allowlist = _get_admin_allowlist()
    if not allowlist or email not in allowlist:
        raise HTTPException(status_code=403, detail="admin access required")
    return email


class UserPreferences(BaseModel):
    categories: list[str] = Field(default_factory=list)
    subcategories: list[str] = Field(default_factory=list)


class AdminUserUpdate(BaseModel):
    full_name: str | None = None
    email: str | None = None
    location: str | None = None
    profile_image_url: str | None = None
    theme_preference: str | None = None
    preferences: UserPreferences | None = None
    password: str | None = None


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


class EventOut(BaseModel):
    event_id: int
    ts: str
    user_id: str
    event_type: str
    news_id: str
    impression_id: str | None = None
    request_id: str | None = None
    model_version: str | None = None
    method: str | None = None
    position: int | None = None
    explore_level: float | None = None
    diversify: bool | None = None
    dwell_ms: int | None = None
    metadata: dict


class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminLoginVerify(BaseModel):
    email: str
    password: str
    otp: str


class AdminTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: str


class AdminBootstrap(BaseModel):
    email: str
    password: str


@router.post("/bootstrap", status_code=201)
def bootstrap_admin(payload: AdminBootstrap, x_admin_bootstrap_key: str = Header(..., alias="X-Admin-Bootstrap-Key")):
    allowlist = _get_admin_allowlist()
    email = payload.email.strip().lower()
    if not allowlist or email not in allowlist:
        raise HTTPException(status_code=403, detail="admin access required")
    if not payload.password.strip():
        raise HTTPException(status_code=400, detail="password cannot be empty")

    expected = os.getenv("ADMIN_BOOTSTRAP_KEY")
    if not expected or x_admin_bootstrap_key != expected:
        raise HTTPException(status_code=403, detail="invalid bootstrap key")

    password_hash = pwd_context.hash(payload.password)
    conn = get_psycopg_conn()
    try:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO admin_users (email, password_hash, created_at, updated_at)
                    VALUES (%s, %s, NOW(), NOW())
                    """,
                    (email, password_hash),
                )
            conn.commit()
        except errors.UniqueViolation:
            conn.rollback()
            raise HTTPException(status_code=409, detail="admin already exists")
        return {"status": "created"}
    finally:
        conn.close()


@router.post("/login/otp/request")
def request_admin_otp(payload: AdminLoginRequest):
    allowlist = _get_admin_allowlist()
    email = payload.email.strip().lower()
    if not allowlist or email not in allowlist:
        raise HTTPException(status_code=403, detail="admin access required")

    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT password_hash FROM admin_users WHERE email = %s", (email,))
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="admin account not found")
        if not pwd_context.verify(payload.password, row[0]):
            raise HTTPException(status_code=401, detail="invalid credentials")

        otp = f"{secrets.randbelow(1000000):06d}"
        otp_hash = pwd_context.hash(otp)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO admin_login_otps (email, otp_hash, expires_at, used_at, created_at)
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

        _send_login_email(email, otp)
        return {"status": "otp_sent"}
    finally:
        conn.close()


@router.post("/login/verify", response_model=AdminTokenOut)
def verify_admin_login(payload: AdminLoginVerify):
    allowlist = _get_admin_allowlist()
    email = payload.email.strip().lower()
    if not allowlist or email not in allowlist:
        raise HTTPException(status_code=403, detail="admin access required")

    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT u.password_hash, t.otp_hash, t.expires_at, t.used_at
                FROM admin_users u
                JOIN admin_login_otps t ON t.email = u.email
                WHERE u.email = %s
                """,
                (email,),
            )
            row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="admin login not found")

        password_hash, otp_hash, expires_at, used_at = row
        if not pwd_context.verify(payload.password, password_hash):
            raise HTTPException(status_code=401, detail="invalid credentials")
        if used_at is not None:
            raise HTTPException(status_code=400, detail="otp already used")
        if expires_at is None or expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="otp expired")
        if not pwd_context.verify(payload.otp, otp_hash):
            raise HTTPException(status_code=401, detail="invalid otp")

        with conn.cursor() as cur:
            cur.execute(
                "UPDATE admin_login_otps SET used_at = NOW() WHERE email = %s",
                (email,),
            )
        conn.commit()

        token, expires_at = _issue_admin_token(email)
        return AdminTokenOut(access_token=token, expires_at=expires_at.isoformat())
    finally:
        conn.close()


@router.get("/users", response_model=list[UserOut], dependencies=[Depends(require_admin_token)])
def list_users(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT user_id, full_name, email, location, theme_preference,
                       profile_image_url, preferences, created_at, updated_at
                FROM users
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cur.fetchall()
        return [
            UserOut(
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
            for row in rows
        ]
    finally:
        conn.close()


@router.patch("/users/{user_id}", response_model=UserOut, dependencies=[Depends(require_admin_token)])
def admin_update_user(user_id: str, payload: AdminUserUpdate):
    if payload.password is not None and not payload.password.strip():
        raise HTTPException(status_code=400, detail="password cannot be empty")

    password_hash = pwd_context.hash(payload.password) if payload.password else None
    email = payload.email.strip().lower() if payload.email else None

    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
            exists = cur.fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="user not found")

        try:
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
                        password_hash = COALESCE(%s, password_hash),
                        updated_at = NOW()
                    WHERE user_id = %s
                    RETURNING user_id, full_name, email, location, theme_preference,
                              profile_image_url, preferences, created_at, updated_at
                    """,
                    (
                        payload.full_name,
                        email,
                        payload.location,
                        payload.profile_image_url,
                        payload.theme_preference,
                        Json(payload.preferences.model_dump()) if payload.preferences else None,
                        password_hash,
                        user_id,
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        except errors.UniqueViolation:
            conn.rollback()
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


@router.get("/events", response_model=list[EventOut], dependencies=[Depends(require_admin_token)])
def list_events(
    user_id: str | None = None,
    event_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    conditions = []
    params: list[object] = []
    if user_id:
        conditions.append("user_id = %s")
        params.append(user_id)
    if event_type:
        conditions.append("event_type = %s")
        params.append(event_type)
    if since:
        conditions.append("ts >= %s")
        params.append(since)
    if until:
        conditions.append("ts <= %s")
        params.append(until)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    conn = get_psycopg_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT event_id, ts, user_id, event_type, news_id, impression_id,
                       request_id, model_version, method, position, explore_level,
                       diversify, dwell_ms, metadata
                FROM events
                {where_clause}
                ORDER BY ts DESC
                LIMIT %s OFFSET %s
                """,
                (*params, limit, offset),
            )
            rows = cur.fetchall()
        return [
            EventOut(
                event_id=row[0],
                ts=row[1].isoformat(),
                user_id=row[2],
                event_type=row[3],
                news_id=row[4],
                impression_id=row[5],
                request_id=row[6],
                model_version=row[7],
                method=row[8],
                position=row[9],
                explore_level=row[10],
                diversify=row[11],
                dwell_ms=row[12],
                metadata=row[13] or {},
            )
            for row in rows
        ]
    finally:
        conn.close()
