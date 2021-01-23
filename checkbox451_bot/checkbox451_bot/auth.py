import functools
import os
from enum import Enum, unique
from logging import getLogger
from typing import Union

from aiogram.types import CallbackQuery, Contact, Message
from sqlalchemy_utils import PhoneNumber

from checkbox451_bot import db, kbd, msg

log = getLogger(__name__)

ADMIN = "ADMIN"
CASHIER = "CASHIER"
SUPERVISOR = "SUPERVISOR"

_admins = []


def init():
    _admins.extend(
        PhoneNumber(phone_number, region="UA")
        for phone_number in os.environ.get(ADMIN, "").split(",")
        if phone_number
    )


@unique
class SignMode(Enum):
    ON = "on"
    ONE = "one"
    OFF = "off"

    @classmethod
    def enabled(cls):
        return getattr(cls, "_mode") in (cls.ON, cls.ONE)

    @classmethod
    def one(cls):
        return getattr(cls, "_mode") is SignMode.ONE

    @classmethod
    def set(cls, mode):
        cls._mode = mode

    @classmethod
    def mode(cls, item):
        mode = next((attr for attr in cls if attr.value == item), None)
        if mode is None:
            raise ValueError("invalid mode")


SignMode.set(SignMode.OFF)


def require(role_name):
    def decorator(handler):
        @functools.wraps(handler)
        async def wrapper(arg: Union[CallbackQuery, Message]):
            if isinstance(arg, CallbackQuery):
                message = arg.message
            else:
                message = arg
            if has_role(message.chat.id, role_name):
                return await handler(arg)

            if SignMode.enabled() or not get_role(ADMIN).users:
                if arg is not message:
                    await arg.answer(msg.AUTH_REQUIRED)
                await message.answer(msg.AUTH_REQUIRED, reply_markup=kbd.auth)

        return wrapper

    return decorator


def add_user(contact: Contact, *, session: db.Session):
    if not (user := session.query(db.User).get(contact.user_id)):
        user = db.User(**contact.values)
        session.add(user)
        session.commit()
        log.info("new user: %s", user)

    return user


def get_role(role_name: str, *, session: db.Session = None):
    session = session or db.Session()

    if not (role := session.query(db.Role).get(role_name)):
        role = db.Role(name=role_name)
        session.add(role)
        session.commit()

    return role


def add_role(user: db.User, role_name: str, *, session: db.Session):
    assert role_name in (
        ADMIN,
        CASHIER,
        SUPERVISOR,
    ), f"invalid role: {role_name}"

    role = get_role(role_name, session=session)

    user.roles.append(role)
    log.info("%s is a %s now", user.user_id, role.name)

    session.commit()


def sign_in(contact: Contact):
    session = db.Session()

    if SignMode.enabled() or not get_role(ADMIN, session=session).users:
        user = add_user(contact, session=session)

        if SignMode.one():
            SignMode.set(SignMode.OFF)

        if user.phone_number in _admins:
            add_role(user, ADMIN, session=session)

        return user


def has_role(user_id, role_name):
    session = db.Session()
    user = (
        session.query(db.User)
        .filter(db.User.user_id == user_id, db.User.roles.any(name=role_name))
        .one_or_none()
    )

    return user
