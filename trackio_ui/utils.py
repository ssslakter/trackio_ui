import orjson


def sse_json(data: dict, event: str = "message") -> str:
    json_str = orjson.dumps(data, option=orjson.OPT_SERIALIZE_NUMPY | orjson.OPT_NON_STR_KEYS).decode()
    return f"event: {event}\ndata: {json_str}\n\n"
