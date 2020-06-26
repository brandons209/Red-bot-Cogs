import inspect
from pathlib import Path

# defines a saysound dictionary
def saysound(name: str, added_by: str, cost: int = 0, volume: int = 100, url: str = None, filepath: str = None) -> dict:
    saysound = {"name": name, "added_by": added_by, "cost": cost, "volume": volume, "url": url, "filepath": filepath}

    return saysound


# gets path to main directory of cog's code
def code_path(cog_instance):
    return Path(inspect.getfile(cog_instance.__class__)).parent
