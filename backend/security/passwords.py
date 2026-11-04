"""Argon2id via maintained argon2-cffi; bounded CPU/memory use per process."""

from threading import BoundedSemaphore

from argon2 import PasswordHasher, Type
from argon2.exceptions import HashingError, InvalidHashError, VerificationError


HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, type=Type.ID)
CAPACITY = BoundedSemaphore(2)


class PasswordCapacityError(Exception):
    pass


def valid_password(password):
    return isinstance(password, str) and 15 <= len(password) <= 128 and len(password.encode("utf-8")) <= 512


def hash_password(password):
    if not valid_password(password):
        raise ValueError("Пароль должен содержать от 15 до 128 символов.")
    if not CAPACITY.acquire(blocking=False):
        raise PasswordCapacityError
    try:
        try:
            return HASHER.hash(password)
        except HashingError:
            raise PasswordCapacityError from None
    finally:
        CAPACITY.release()


def verify_password(encoded, password):
    if not isinstance(password, str) or len(password) > 128 or len(password.encode("utf-8")) > 512:
        return False
    if not CAPACITY.acquire(blocking=False):
        raise PasswordCapacityError
    try:
        try:
            return HASHER.verify(encoded, password)
        except (VerificationError, InvalidHashError):
            return False
    finally:
        CAPACITY.release()
