import importlib
import inspect
import logging
import os
import re
from itertools import chain
from pathlib import Path
from types import ModuleType
from typing import (Any, Callable, Final, Iterator, List, Optional, Pattern,
                    Set, Tuple, Type, TypeVar, Union)

from pydantic import BaseModel, validator

__all__ = ["PluginsLoader"]
_logger = logging.getLogger(__name__)

T = TypeVar("T")
FileSystemPath = 'str'
PackagePath = 'str'  # TODO: Fix
# PackagePath = Field(str, regex=r"([a-z]*_?[a-z]*(\.([a-z]*_?[a-z])*)?)+")

_PRIVATE_PREFIX: Final = "__"
_INSTALLED_PACKAGES_DIRECTORY: Final = "site-packages"


class PluginsLoader(BaseModel):
    """
    A class used for loading plugins dynamically.

    :param plugins_packages A single package or a ``Set`` of packages that will be used to search for plugins in

    """

    class Config:
        arbitrary_types_allowed = True

    plugins_packages: Union[ModuleType, Set[ModuleType]]
    raise_exception_on_missing_modules: bool = False
    full_depth_search: bool = True  # TODO: Consider if needed? and CHECK
    included_files_pattern: Pattern[str] = re.compile(r".*")
    included_subdirectories_pattern: Pattern[str] = re.compile(r".*")
    ############## ADD USAGE OF FOLLOWING ATTRIBUTES#####
    included_subpackages: Set[ModuleType] = set()  # TODO: Consider if needed?
    #####################################################
    plugins_predicate: Optional[Callable[..., bool]] = None

    @validator('plugins_predicate')
    def prevent_plugins_predicate_none(cls, plugins_predicate: Callable[..., bool]) -> Callable[..., bool]:
        assert plugins_predicate, f"field can't be None"
        return plugins_predicate

    def load_subclasses(self, ancestor_class: Type[T]) -> List[Type[T]]:
        """Load all plugins in ``self.plugins_packages`` that are subclasses of ``ancestor_class``"""
        return self._load(lambda member: _is_member_subclass_of_ancestor_predicate(member, ancestor_class))

    def load(self) -> List[Type[T]]:
        """Load all plugins in ``self.plugins_packages`` that satisfy ``plugins_predicate``"""
        return self._load(self.plugins_predicate)

    def _load(self, plugins_predicate: Callable[..., bool]) -> List[Type[T]]:
        """Load all plugins in ``self.plugins_packages`` that satisfy ``plugins_predicate``"""
        packages_paths: Set[PackagePath] = set()
        plugins_packages = self.plugins_packages if isinstance(self.plugins_packages, set) else {self.plugins_packages}
        for plugins_package in plugins_packages:
            packages_paths |= self._generate_packages_paths(plugins_package)

        plugins = self._load_plugins(packages_paths, plugins_predicate)
        return plugins

    def _generate_packages_paths(self, package: ModuleType) -> Set[PackagePath]:
        """
        Generates ``PackagePath``-s of all packages in ``package``.
        For example, if ``package`` is 'plugins' the returned list will look something like
        ['plugins.plugin1', 'plugins.plugin2']
        """
        packages_import_paths: Set[PackagePath] = set()
        excluded_prefixes = (_PRIVATE_PREFIX, ".")  # exclude inner directories

        package_relative_path = self._generate_package_relative_path(package)
        directory_tree = os.walk(package_relative_path)
        for package_directory, package_subdirectories, package_files in directory_tree:
            if package_directory.endswith(excluded_prefixes):
                continue
            packages_files = [f for f in package_files if self._is_acceptable_package_file(f)]  # remove private files

            for package_file in packages_files:
                package_file_relative_path = Path(package_directory) / package_file
                package_path = self._generate_package_path(package_file_relative_path)
                packages_import_paths.add(package_path)

            if self.full_depth_search:
                subdirectories_trees = self._generate_subdirectories_trees(package_directory, package_subdirectories)
                directory_tree = chain(directory_tree, subdirectories_trees)

        return packages_import_paths

    def _generate_package_relative_path(self, package: ModuleType) -> FileSystemPath:
        """Generates a ``FileSystemPath`` of ``package``'s  relative to ``current_working_directory``"""
        package_path = package.__path__[0]
        return self._generate_directory_relative_path(package_path)

    def _is_acceptable_package_file(self, package_file: FileSystemPath) -> bool:
        """Checks if ``package_file`` is one which we want to look at"""
        package_file_path = Path(package_file)
        return (
                package_file_path.suffix == ".py"
                and not package_file_path.stem.startswith(_PRIVATE_PREFIX)
                and re.match(self.included_files_pattern, package_file)
        )

    def _generate_subdirectories_trees(self, package_directory: FileSystemPath,
                                       package_subdirectories: List[FileSystemPath]) -> \
            Iterator[Tuple[FileSystemPath, List[FileSystemPath], List[FileSystemPath]]]:

        subdirectories_trees = chain.from_iterable([])
        package_subdirectories = [
            directory for directory in package_subdirectories if self._is_acceptable_package_subdirectory(directory)
        ]
        for package_subdirectory in package_subdirectories:
            package_subdirectory_full_path = Path(package_directory) / package_subdirectory
            package_subdirectory_relative_path = self._generate_directory_relative_path(package_subdirectory_full_path)
            subdirectory_tree = os.walk(package_subdirectory_relative_path)
            subdirectories_trees = chain(subdirectories_trees, subdirectory_tree)
        return subdirectories_trees

    def _is_acceptable_package_subdirectory(self, package_subdirectory: FileSystemPath) -> bool:
        """Checks if ``package_subdirectory`` is one which we want to look at"""
        return (
                not package_subdirectory.startswith(_PRIVATE_PREFIX)
                and re.match(self.included_subdirectories_pattern, package_subdirectory)
        )

    # TODO: Can go out to path_utils
    @staticmethod
    def _generate_directory_relative_path(directory: Union[Path, FileSystemPath]) -> FileSystemPath:
        """Generates a ``FileSystemPath`` of ``directory`` relative to ``current_working_directory``"""
        current_working_directory = Path.cwd()
        package_relative_path = os.path.relpath(directory, current_working_directory)
        return package_relative_path

    @staticmethod
    def _generate_package_path(package_file_relative_path: Path) -> PackagePath:
        """
        Generates a package path, given a package file relative path, that can be imported.
        For example, if package_file_relative_path is '../test/my_abstract.py' the return value will be
        'test.my_abstract'

        :param package_file_relative_path: the relative path to the package file
        """
        package_path: Path = package_file_relative_path.with_suffix("")  # remove suffix
        package_posix_path: FileSystemPath = package_path.as_posix()  # convert to posix

        # replace / (used for directory hierarchy in posix path) with . and remove . prefix (if exists)
        package_import_path: PackagePath = package_posix_path.replace("/", ".").lstrip(".")

        # remove prefix path containing `_INSTALLED_PACKAGES_DIRECTORY` directory
        # (for example, useful for virtual environments)
        package_import_path = package_import_path.split(f"{_INSTALLED_PACKAGES_DIRECTORY}.")[-1]
        return package_import_path

    def _load_plugins(self, packages_paths: Set[PackagePath], plugins_predicate: Callable[..., bool]) -> \
            List[Type[T]]:
        """Load all plugins located in ``packages_paths`` that satisfy the ``plugins_predicate``"""
        plugins: List[Type[T]] = []  # define the set of plugins
        missing_modules: List[str] = []

        for plugin_file_name in packages_paths:  # import each plugin's module
            try:
                plugin_module = importlib.import_module(plugin_file_name)
            except ModuleNotFoundError as e:
                if not e.name:
                    raise e
                if e.name not in missing_modules:
                    missing_modules.append(e.name)
                continue
            members = inspect.getmembers(plugin_module, plugins_predicate)
            plugin: Type[T]
            for _, plugin in members:
                if plugin not in plugins:
                    plugins.append(plugin)

        if missing_modules:
            self._handle_missing_modules(missing_modules)

        return plugins

    def _handle_missing_modules(self, missing_modules: List[str]) -> None:
        """
        Logs missing modules (or raises ModuleNotFoundError, depending
        on self.raise_exception_on_missing_modules value)

        :param missing_modules: Modules failed to be loaded
        :raises ModuleNotFoundError: in case of self.raise_exception_on_missing_modules being True
        """
        missing_modules_separated_by_comma = ", ".join(missing_modules)
        warning_message = (
            f"WARNING: Failed searching plugins in the following imported modules: "
            f"{missing_modules_separated_by_comma}.{os.linesep}"
            f"Consider running the following command: 'pip3 install {missing_modules_separated_by_comma}'."
        )
        if self.raise_exception_on_missing_modules:
            raise ModuleNotFoundError(warning_message)
        _logger.warning(warning_message)


def _is_member_subclass_of_ancestor_predicate(member: Any, ancestor_class: Type[T]) -> bool:
    return (
            inspect.isclass(member) and
            member != ancestor_class and
            issubclass(member, ancestor_class)
    )
