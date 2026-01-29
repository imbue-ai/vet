from typing import Any
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def model_update(model: T, update: dict[str, Any]) -> T:
    """
    Update a Pydantic model with a dictionary of updates.
    Validation is performed to ensure items in the update dictionary are valid fields in the model.
    Use the Evolver class (imbue_core/imbue_core/nested_evolver.py) for type checking

    Args:
        model (BaseModel): The original Pydantic model.
        update (Dict[str, Any]): A dictionary of updates to apply to the model.

    Returns:
        BaseModel: A new instance of the model with the updates applied.

    """
    update_dict_fields = update.keys()
    model_fields = set(model.__class__.model_fields)
    extra_fields = update_dict_fields - model_fields
    if extra_fields:
        raise ValueError(f"Invalid fields: {extra_fields}")
    return fields_only_model_copy(model, update=update)


def fields_only_model_copy(model: T, update: dict[str, Any] = {}) -> T:
    """
    Create a copy of a Pydantic model with only the fields defined in the model.

    (Specifically, do not copy cached properties.)

    """
    fields = {name: update.get(name, getattr(model, name)) for name in model.__class__.model_fields}
    return model.__class__(**fields)
