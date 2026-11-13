from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .. import auth
from ..db import get_db
from ..schemas import AuthStatus, PasswordChange, PasswordIn

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status", response_model=AuthStatus)
def get_status(request: Request, db: Session = Depends(get_db)):
    return AuthStatus(
        authenticated=auth.is_authenticated(request, db),
        setup_required=auth.setup_required(db),
        password_from_env=auth.password_from_env(),
    )


@router.post("/setup", status_code=204)
def setup(body: PasswordIn, request: Request, db: Session = Depends(get_db)):
    if not auth.setup_required(db):
        raise HTTPException(status.HTTP_409_CONFLICT, "Password is already set.")
    if len(body.password) < 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Use at least 8 characters.")
    auth.set_password(db, body.password)
    auth.login_session(request, db)


@router.post("/login", status_code=204)
def login(body: PasswordIn, request: Request, db: Session = Depends(get_db)):
    auth.throttle_check()
    if auth.setup_required(db):
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup required.")
    if not auth.check_password(db, body.password):
        auth.record_failure()
        time.sleep(0.5)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong password.")
    auth.login_session(request, db)


@router.post("/logout", status_code=204)
def logout(request: Request):
    request.session.clear()


@router.post("/password", status_code=204, dependencies=[Depends(auth.require_auth)])
def change_password(body: PasswordChange, request: Request, db: Session = Depends(get_db)):
    if auth.password_from_env():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "The password is set by COLLANDER_PASSWORD; change it there."
        )
    auth.throttle_check()
    if not auth.check_password(db, body.current_password):
        auth.record_failure()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Current password is wrong.")
    auth.set_password(db, body.new_password)
    auth.login_session(request, db)
