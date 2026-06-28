import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response


def JSON(status: int, value: Any) -> Response:
    return JSONResponse(content=value, status_code=status)


async def DecodeJSON(request: Request, target: type) -> Any:
    body = await request.body()
    data = json.loads(body)
    if hasattr(target, "model_validate"):
        return target.model_validate(data)
    if hasattr(target, "__annotations__"):
        return target(**{k: v for k, v in data.items() if k in target.__annotations__})
    return data
