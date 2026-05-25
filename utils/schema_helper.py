import inspect
import typing
import re

# Python 3.10+ exposes UnionType for X | Y syntax; older versions don't.
try:
    from types import UnionType  # type: ignore
except ImportError:
    UnionType = None  # type: ignore


def _py_type_to_json(py_type):
    """
    Maps Python types to JSON Schema types.

    Correctly unwraps:
      - Optional[T]            (== Union[T, None])
      - Union[A, B, ...]       (picks the first non-None arg)
      - X | Y                  (PEP 604, Python 3.10+)
      - List[T] / list[T]
      - Literal["a", "b"]
    """
    # ── Unwrap Optional / Union ────────────────────────────────────
    # typing.Optional[X] expands to typing.Union[X, None].
    # Both typing.Union and PEP-604 (X | Y) report __origin__ == typing.Union
    # / types.UnionType respectively.
    origin = typing.get_origin(py_type)

    if origin is typing.Union or (UnionType is not None and origin is UnionType):
        args = [a for a in typing.get_args(py_type) if a is not type(None)]
        if not args:
            return {"type": "null"}
        # If multiple non-None args, just take the first concrete type.
        # Function-calling APIs don't really benefit from oneOf here.
        return _py_type_to_json(args[0])

    # ── Literal["a", "b", ...] → enum ──────────────────────────────
    if origin is typing.Literal:
        values = list(typing.get_args(py_type))
        # Pick a JSON type from the first literal value; assume all are same kind.
        first = values[0] if values else ""
        json_type = (
            "integer" if isinstance(first, bool) is False and isinstance(first, int) else
            "number"  if isinstance(first, float) else
            "boolean" if isinstance(first, bool) else
            "string"
        )
        return {"type": json_type, "enum": values}

    # ── List[T] / list[T] → array ──────────────────────────────────
    if origin in (list, typing.List):
        args = typing.get_args(py_type)
        item_type = args[0] if args else str
        return {
            "type": "array",
            "items": _py_type_to_json(item_type),
        }

    # ── Dict[K, V] / dict[K, V] → object ───────────────────────────
    if origin in (dict, typing.Dict):
        return {"type": "object"}

    # ── Plain types ────────────────────────────────────────────────
    type_map = {
        int: "integer",
        str: "string",
        bool: "boolean",
        float: "number",
        dict: "object",
        list: "array",
        type(None): "null",
    }
    return {"type": type_map.get(py_type, "string")}


def _parse_param_descriptions(docstring):
    """
    Parses :param name: description from docstrings.
    Captures multi-line descriptions until the next :param or end of docstring.
    """
    if not docstring:
        return {}

    params = {}
    # Greedy match up to the next :param: or end of string
    pattern = r":param\s+(\w+):\s*(.+?)(?=\n\s*:param\s+\w+:|\Z)"
    for name, desc in re.findall(pattern, docstring, flags=re.DOTALL):
        params[name] = re.sub(r"\s+", " ", desc).strip()
    return params


def tool(func):
    """
    Decorator that generates a JSON schema and attaches it to the function as .schema.
    """
    doc = inspect.getdoc(func) or ""
    func_desc = doc.split(":param")[0].strip() if doc else "No description."
    param_docs = _parse_param_descriptions(doc)

    try:
        type_hints = typing.get_type_hints(func)
    except Exception:
        type_hints = {}

    sig = inspect.signature(func)
    properties = {}
    required = []

    for name, param in sig.parameters.items():
        if name == "self":
            continue

        annotation = type_hints.get(name, param.annotation)
        if annotation == inspect.Parameter.empty:
            annotation = str

        field_schema = _py_type_to_json(annotation)

        if name in param_docs:
            field_schema["description"] = param_docs[name]

        properties[name] = field_schema

        # Required only if no default value AND not Optional
        is_optional_type = (
            typing.get_origin(annotation) is typing.Union
            and type(None) in typing.get_args(annotation)
        )
        if param.default is inspect.Parameter.empty and not is_optional_type:
            required.append(name)

    func.schema = {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": func_desc,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }

    return func
