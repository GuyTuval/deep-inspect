import importlib
import inspect
import logging
import os
from itertools import chain
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Set, Type, TypeVar, Union

from pydantic import BaseModel, validator

__all__ = ["PluginsLoader"]
_logger = logging.getLogger(__name__)
T = TypeVar("T")


class PluginsLoader(BaseModel):
    class Config:
        arbitrary_types_allowed = True

    plugins_packages: Union[ModuleType, Set[ModuleType]]
    raise_exception_on_missing_modules: bool = False
    full_depth_search: bool = True
    excluded_files_regex: str = ""
    excluded_directories_regex: str = ""
    excluded_packages: Set[ModuleType] = set()
    plugins_predicate: Callable[..., bool] = None

    @validator('plugins_predicate')
    def prevent_plugins_predicate_none(cls, plugins_predicate) -> None:
        assert plugins_predicate, f"filed can't be None"
        return plugins_predicate

    def load_subclasses(self, ancestor_class: Type[T]) -> Set[Type[T]]:
        """

        :rtype: object
        """
        return self._load(lambda member: _is_subclass_predicate(member, ancestor_class))

    def load(self) -> Set[Type[T]]:
        return self._load(self.plugins_predicate)

    def _load(self, plugins_predicate: Callable[..., bool]) -> Set[Type[T]]:
        if not isinstance(self.plugins_packages, set):
            self.plugins_packages = {self.plugins_packages}

        packages_paths = set()
        for plugins_package in self.plugins_packages:
            if (
                not hasattr(plugins_package, "__package__")
                or plugins_package.__package__ != plugins_package.__name__
            ):
                raise TypeError(f"Parameter {plugins_package} is not a python package")
            packages_paths |= self._generate_packages_paths(plugins_package)

        plugins_classes = self._generate_plugins_classes(
            packages_paths, plugins_predicate
        )
        return plugins_classes

    def _generate_packages_paths(self, package: ModuleType) -> Set[str]:
        """
        Generates paths of all packages in the given package
        For example, if given package 'plugins' the returned list will look something like
         ['plugins.plugin1', 'plugins.plugin2']
        """
        packages_paths: Set[str] = set()
        excluded_prefixes = ("__", ".")  # exclude inner folders

        package_relative_path = self._generate_package_relative_path(package)
        walk = os.walk(package_relative_path)
        for package_directory, package_subdirectories, files in walk:
            if package_directory.endswith(excluded_prefixes):
                continue
            packages_files = [
                f for f in files if Path(f).suffix == ".py" and not Path(f).stem.startswith("__")
            ]  # remove private files

            for package_file in packages_files:
                package_file_relative_path = Path(package_directory) / package_file
                package_path = self._generate_package_import_path(package_file_relative_path)
                packages_paths.add(package_path)

            package_subdirectories = [x for x in package_subdirectories if not x.startswith("__")]
            for package_subdirectory in package_subdirectories:
                package_subdirectory_full_path = Path(package_directory) / package_subdirectory
                package_subdirectory_relative_path = (
                    self._generate_directory_relative_path(package_subdirectory_full_path)
                )
                walk = chain(walk, os.walk(package_subdirectory_relative_path))

        return packages_paths

    def _generate_package_relative_path(self, package: ModuleType) -> str:
        """
        Generates package's relative path (in relate to the current working directory)
        """
        package_path = package.__path__[0]
        return self._generate_directory_relative_path(package_path)

    # TODO: Can go out to path_utils
    @staticmethod
    def _generate_directory_relative_path(directory: Union[Path, str]) -> str:
        current_working_directory = Path.cwd()
        package_relative_path = os.path.relpath(directory, current_working_directory)
        return package_relative_path

    @staticmethod
    def _generate_package_import_path(package_file_relative_path: Path) -> str:
        """
        Generates a package import path that can be imported given a package file relative path.
        For example, if package_file_relative_path is '../test/my_abstract.py' the return value will be 'test.my_abstract'
        :param package_file_relative_path: the relative path to the package file
        """
        result = package_file_relative_path.with_suffix("")  # remove suffix
        result = result.as_posix()  # convert to posix
        result = result.replace("/", ".")  # replace / (used for directory hierarchy in posix path) with .
        result = result.lstrip(".")  # remove . prefix (if exists)

        # remove prefix path containing 'site-packages' directory (for example, useful for virtual environments)
        result = result.split("site-packages.")[-1]
        return result

    @staticmethod
    def _generate_plugins_classes(
        packages_paths: Set[str], plugins_predicate: Callable[..., bool]
    ) -> Set[Type[T]]:
        """
        Generates a list of plugins using all classes that exist in packages_paths which implement the
        plugins_abstract_class.
        """
        plugins_classes: Set[Type[T]] = set()  # define the set of plugins

        missing_modules = set()
        for plugin_file_name in packages_paths:  # import each plugin's module
            try:
                plugin_module = importlib.import_module(plugin_file_name)
            except ModuleNotFoundError as e:
                missing_modules.add(e.name)
                continue
            members = inspect.getmembers(plugin_module, plugins_predicate)
            plugins_class: Type[T]
            for _, plugin_class in members:
                plugins_classes.add(plugin_class)

        if missing_modules:
            missing_modules_separated_by_comma = ", ".join(missing_modules)
            _logger.warning(
                f"WARNING: Failed searching plugins in the following imported modules: "
                f"{missing_modules_separated_by_comma}.{os.linesep}"
                f"Consider running the following command: 'pip3 install {missing_modules_separated_by_comma}'."
            )

        return plugins_classes


def _is_subclass_predicate(member: Any, ancestor_class: Type[T]) -> bool:
    return (
        inspect.isclass(member) and
        member != ancestor_class and
        issubclass(member, ancestor_class)
    )
