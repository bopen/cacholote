import functools
import hashlib
import importlib
import inspect
import json
import operator


def make_unique_arguments(callable_, *args, **kwargs):
    bound_arguments = inspect.signature(callable_).bind(*args, **kwargs)
    bound_arguments.apply_defaults()
    sorted_kwargs = sorted(bound_arguments.kwargs.items(), key=operator.itemgetter(0))
    return bound_arguments.args, dict(sorted_kwargs)


def inspect_fully_qualified_name(obj):
    """Return the fully qualified name of a python object."""
    module = inspect.getmodule(obj)
    return f"{module.__name__}:{obj.__qualname__}"


def import_object(fully_qualified_name):
    if ":" not in fully_qualified_name:
        raise ValueError(f"{fully_qualified_name} not in the form 'module:qualname'")
    module_name, _, object_name = fully_qualified_name.partition(":")
    obj = importlib.import_module(module_name)
    for attr_name in object_name.split("."):
        obj = getattr(obj, attr_name)
    return obj


def make_unique_call_signature(callable_, *args, **kwargs):
    fully_qualified_name = inspect_fully_qualified_name(callable_)
    unique_args, unique_kwargs = make_unique_arguments(callable_, *args, **kwargs)
    unique_call_signature = {
        "callable": fully_qualified_name,
        "args": unique_args,
        "kwargs": unique_kwargs,
    }
    return unique_call_signature


def jsonify(obj):
    return json.dumps(obj, separators=(",", ":"))


def make_unique_call_signature_json(callable_, *args, **kwargs):
    unique_call_signature = make_unique_call_signature(callable_, *args, **kwargs)
    return jsonify(unique_call_signature)


def hexdigestify(text):
    hash_req = hashlib.sha3_224(text.encode())
    return hash_req.hexdigest()


def make_unique_call_signatures(callable_, *args, **kwargs):
    call_signature = make_unique_call_signature(callable_, *args, **kwargs)
    call_signature_json = jsonify(call_signature)
    return call_signature, call_signature_json, hexdigestify(call_signature_json)


CACHE = {}


def invalidate_entry(hexdigest):
    return CACHE.pop(hexdigest, None)


def cacheable(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            signatures = make_unique_call_signatures(func, *args, **kwargs)
        except TypeError:
            print(f"UNCACHEABLE: {args} {kwargs}")
            return func(*args, **kwargs)

        signature_dict, signature_json, hexdigest = signatures
        if hexdigest not in CACHE:
            print(f"MISS: {hexdigest} {signature_json}")
            result = func(*signature_dict["args"], **signature_dict["kwargs"])
            CACHE[hexdigest] = (signature_json, result)
        else:
            print(f"HIT: {hexdigest}")
        return CACHE[hexdigest][1]

    return wrapper
