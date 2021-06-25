Deep Inspect
============

Deep Inspect is a library that wraps `inspect` built-in module. It's purpose
is to allow you to explore python packages in a 'deeper' manner -
down to the most inner files in the package's hierarchy.

Currently, Deep Inspect offers `get_subclasses()` and `get_members` in a 'deeper' manner.


Installation
----------
To install the newest version use the following command:
```
pip install -U deep-inspect
```


Basic Usage
----------------
In order to find every function in `pydantic` package:
```python
import inspect

import pydantic

import deep_inspect

if __name__ == '__main__':
    pydantic_functions = deep_inspect.get_members(pydantic, inspect.isfunction)
    print(pydantic_functions)
```

In order to find all subclasses of `BaseModel` in `pydantic` package:
```python
import pydantic
from pydantic import BaseModel

import deep_inspect

if __name__ == '__main__':
    base_model_subclasses = deep_inspect.get_subclasses(BaseModel, pydantic)
    print(base_model_subclasses)
```

You can also use the `get_subclasses()` function with a `set()` of packages:

```python
import pydantic
import pytest
from pydantic import BaseModel

import deep_inspect

if __name__ == '__main__':
    base_model_subclasses = deep_inspect.get_subclasses(BaseModel, {pydantic, pytest})
    print(base_model_subclasses)
```

### Factory example
Originally, Deep Inspect goal was to implement `get_subclasses()` function to help register `class`es
to a Factory in a dynamic matter.

Refer to the following code sample:
```python
from typing import TypeVar

import pydantic
from pydantic import BaseModel

import deep_inspect

K = TypeVar("K")
V = TypeVar("V")


class Factory:
    def __init__(self):
        self.builders = {}

    def register_builder(self, key: K, builder: V):
        self.builders[key] = builder

    def create(self, key: K, **kwargs):
        builder = self.builders.get(key)
        if not builder:
            raise ValueError(key)
        return builder(**kwargs)


if __name__ == "__main__":
    base_model_inheritors = deep_inspect.get_subclasses(BaseModel, pydantic)

    factory = Factory()

    # register the dynamically loaded `BaseModel` inheritors to `factory`
    for base_model_inheritor in base_model_inheritors:
        factory.register_builder(base_model_inheritor.__name__, base_model_inheritor)

```


Contribution
------------

As Deep Inspect started as a helper library for my current job (refer to the `Factory` example), 
it hasn't reached its full potential.
You are more than welcome to create PRs and I will review them in my free time.

Links
-----
- PyPI Releases: https://pypi.org/project/deep-inspect
- PRs: https://github.com/GuyTuval/deep-inspect/pulls
- Issue Tracker: https://github.com/GuyTuval/deep-inspect/issues
