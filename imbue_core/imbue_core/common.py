import uuid


def generate_id() -> str:
    return uuid.uuid4().hex
