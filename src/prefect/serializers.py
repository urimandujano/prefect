"""
Data serializer implementations

These serializers are registered for use with `DataDocument` types
"""
import abc
import base64
import warnings
from typing import TYPE_CHECKING, Any, Generic, Optional, TypeVar

import pydantic
from pydantic import BaseModel
from pydantic.json import pydantic_encoder
from typing_extensions import Literal

from prefect.utilities.importtools import from_qualified_name, to_qualified_name
from prefect.utilities.pydantic import add_type_dispatch

D = TypeVar("D")


if TYPE_CHECKING:
    pass


def prefect_json_object_encoder(obj: Any) -> Any:
    """
    `JSONEncoder.default` for encoding objects into JSON with extended type support.

    Raises a `TypeError` to fallback on other encoders on failure.
    """
    return {
        "__class__": to_qualified_name(obj.__class__),
        "data": pydantic_encoder(obj),
    }


def prefect_json_object_decoder(result: dict):
    """
    `JSONDecoder.object_hook` for decoding objects from JSON when previously encoded
    with `prefect_json_object_encoder`
    """
    if "__class__" in result:
        return pydantic.parse_obj_as(
            from_qualified_name(result["__class__"]), result["data"]
        )
    return result


@add_type_dispatch
class Serializer(BaseModel, Generic[D], abc.ABC):
    """
    A serializer that can encode objects of type 'D' into bytes.
    """

    type: str

    @abc.abstractmethod
    def dumps(self, obj: D) -> bytes:
        """Encode the object into a blob of bytes."""

    @abc.abstractmethod
    def loads(self, blob: bytes) -> D:
        """Decode the blob of bytes into an object."""

    class Config:
        extra = "forbid"


class PickleSerializer(Serializer):
    """
    Serializes objects using the pickle protocol.

    - Uses `cloudpickle` by default. See `picklelib` for using alternative libraries.
    - Stores the version of the pickle library to check for compatibility during
        deserialization.
    - Wraps pickles in base64 for safe transmission.
    """

    type: Literal["pickle"] = "pickle"

    picklelib: str = "cloudpickle"
    picklelib_version: str = None

    @pydantic.validator("picklelib")
    def check_picklelib(cls, value):
        """
        Check that the given pickle library is importable and has dumps/loads methods.
        """
        try:
            pickler = from_qualified_name(value)
        except (ImportError, AttributeError) as exc:
            raise ValueError(
                f"Failed to import requested pickle library: {value!r}."
            ) from exc

        if not callable(getattr(pickler, "dumps", None)):
            raise ValueError(
                f"Pickle library at {value!r} does not have a 'dumps' method."
            )

        if not callable(getattr(pickler, "loads", None)):
            raise ValueError(
                f"Pickle library at {value!r} does not have a 'loads' method."
            )

        return value

    @pydantic.root_validator
    def check_picklelib_version(cls, values):
        """
        Infers a default value for `picklelib_version` if null or ensures it matches
        the version retrieved from the `pickelib`.
        """
        picklelib = values.get("picklelib")
        picklelib_version = values.get("picklelib_version")

        if not picklelib:
            raise ValueError("Unable to check version of unrecognized picklelib module")

        pickler = from_qualified_name(picklelib)
        pickler_version = getattr(pickler, "__version__", None)

        if not picklelib_version:
            values["picklelib_version"] = pickler_version
        elif picklelib_version != pickler_version:
            warnings.warn(
                f"Mismatched {picklelib!r} versions. Found {pickler_version} in the "
                f"environment but {picklelib_version} was requested. This may cause "
                "the serializer to fail.",
                RuntimeWarning,
                stacklevel=3,
            )

        return values

    def dumps(self, obj: Any) -> bytes:
        pickler = from_qualified_name(self.picklelib)
        blob = pickler.dumps(obj)
        return base64.encodebytes(blob)

    def loads(self, blob: bytes) -> Any:
        pickler = from_qualified_name(self.picklelib)
        return pickler.loads(base64.decodebytes(blob))


class JSONSerializer(Serializer):
    """
    Serializes data to JSON.

    Input types must be compatible with the stdlib json library.

    Wraps the `json` library to serialize to UTF-8 bytes instead of string types.
    """

    type: Literal["json"] = "json"
    jsonlib: str = "json"
    object_encoder: Optional[str] = pydantic.Field(
        default="prefect.serializers.prefect_json_object_encoder",
        description=(
            "An optional callable to use when serializing objects that are not "
            "supported by the JSON encoder. By default, this is set to a callable that "
            "adds support for all types supported by Pydantic."
        ),
    )
    object_decoder: Optional[str] = pydantic.Field(
        default="prefect.serializers.prefect_json_object_decoder",
        description=(
            "An optional callable to use when deserializing objects. This callable "
            "is passed each dictionary encountered during JSON deserialization. "
            "By default, this is set to a callable that deserializes content created "
            "by our default `object_encoder`."
        ),
    )
    dumps_kwargs: dict = pydantic.Field(default_factory=dict)
    loads_kwargs: dict = pydantic.Field(default_factory=dict)

    @pydantic.validator("dumps_kwargs")
    def dumps_kwargs_cannot_contain_default(cls, value):
        # `default` is set by `object_encoder`. A user provided callable would make this
        # class unserializable anyway.
        if "default" in value:
            raise ValueError(
                "`default` cannot be provided. Use `object_encoder` instead."
            )
        return value

    @pydantic.validator("loads_kwargs")
    def loads_kwargs_cannot_contain_object_hook(cls, value):
        # `object_hook` is set by `object_decoder`. A user provided callable would make
        # this class unserializable anyway.
        if "object_hook" in value:
            raise ValueError(
                "`object_hook` cannot be provided. Use `object_decoder` instead."
            )
        return value

    def dumps(self, data: Any) -> bytes:
        json = from_qualified_name(self.jsonlib)
        kwargs = self.dumps_kwargs.copy()
        if self.object_encoder:
            kwargs["default"] = from_qualified_name(self.object_encoder)
        result = json.dumps(data, **kwargs)
        if isinstance(result, str):
            # The standard library returns str but others may return bytes directly
            result = result.encode()
        return result

    def loads(self, blob: bytes) -> Any:
        json = from_qualified_name(self.jsonlib)
        kwargs = self.loads_kwargs.copy()
        if self.object_decoder:
            kwargs["object_hook"] = from_qualified_name(self.object_decoder)
        return json.loads(blob.decode(), **kwargs)
