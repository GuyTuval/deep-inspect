from types import ModuleType
from typing import Any, Set, Union

import pydantic
import pytest
from pydantic import BaseModel


@pytest.mark.parametrize("packages, ancestor_class", [
    (pydantic, {BaseModel})
])
def test_load_subclasses(packages: Union[ModuleType, Set[ModuleType]], ancestor_class: Any):
    pass
