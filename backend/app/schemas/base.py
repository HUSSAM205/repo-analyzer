from pydantic import BaseModel, ConfigDict


class StrictRequestModel(BaseModel):
    """Base for request (input) schemas only -- rejects any field the caller
    sends that isn't declared on the model, instead of pydantic v2's default
    of silently ignoring it. A silently-dropped extra field is exactly the
    kind of thing that can hide a client-side bug (a typo'd field name that
    never actually reaches the server) or mask a caller probing for fields
    the API doesn't document. Response schemas don't inherit this -- there's
    no caller input to reject there.
    """

    model_config = ConfigDict(extra="forbid")
