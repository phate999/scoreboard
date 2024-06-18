import uuid
from typing import Optional

from fastapi import Depends, Request, HTTPException, status
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin, schemas
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    CookieTransport,
    JWTStrategy,
)
from fastapi_users.router.common import ErrorCode
from fastapi_users import exceptions
from fastapi_users.db import SQLAlchemyUserDatabase

from schemas import UserCreate, UserRead

from db import User, get_user_db, get_user_db_manual

import dotenv
dotenv.load_dotenv()
import os

SECRET = os.environ.get("SECRET")

class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = SECRET
    verification_token_secret = SECRET

    async def on_after_register(self, user: User, request: Optional[Request] = None):
        print(f"User {user.id} has registered.")

    async def on_after_forgot_password(
        self, user: User, token: str, request: Optional[Request] = None
    ):
        print(f"User {user.id} has forgot their password. Reset token: {token}")

    async def on_after_request_verify(
        self, user: User, token: str, request: Optional[Request] = None
    ):
        print(f"Verification requested for user {user.id}. Verification token: {token}")


async def get_user_manager(user_db: SQLAlchemyUserDatabase = Depends(get_user_db)):
    yield UserManager(user_db)

async def get_user_manager_manual():
    async for user_db in get_user_db_manual():
        yield UserManager(user_db)

bearer_transport = BearerTransport(tokenUrl="auth/jwt-api/login")
cookie_transport = CookieTransport(cookie_max_age=3600)


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(secret=SECRET, lifetime_seconds=3600)


api_auth_backend = AuthenticationBackend(
    name="jwt-api",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

cookie_auth_backend = AuthenticationBackend(
    name="jwt",
    transport=cookie_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [api_auth_backend, cookie_auth_backend])

current_active_user = fastapi_users.current_user(active=True)
current_active_user_optional = fastapi_users.current_user(active=True, optional=True)

async def get_user_by_email(email: str):
    async for user_manager in get_user_manager_manual():
        try:
            return await user_manager.get_by_email(email)
        except exceptions.UserNotExists:
            return None

async def manual_register(
        request: Request,
        user: UserCreate
    ):
        async for user_manager in get_user_manager_manual():
            try:
                created_user = await user_manager.create(
                    user, safe=True, request=request
                )
            except exceptions.UserAlreadyExists:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ErrorCode.REGISTER_USER_ALREADY_EXISTS,
                )
            except exceptions.InvalidPasswordException as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": ErrorCode.REGISTER_INVALID_PASSWORD,
                        "reason": e.reason,
                    },
                )

        return schemas.model_validate(UserRead, created_user)

async def manual_login(user):
    return await cookie_auth_backend.login(get_jwt_strategy(), user)