import importlib
import inspect
import logging
import os
import re
from itertools import chain
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Final, Iterator, List, Pattern, Set, Tuple, Type, TypeVar, Union

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
    class Config:
        arbitrary_types_allowed = True

    plugins_packages: Union[ModuleType, Set[ModuleType]]
    raise_exception_on_missing_modules: bool = False
    full_depth_search: bool = True  # TODO: Consider if needed? and CHECK
    included_files_pattern: Pattern[str] = re.compile(r".*")
    included_directories_pattern: Pattern[str] = re.compile(r".*")  # TODO: Consider if needed?
    ############## ADD USAGE OF FOLLOWING ATTRIBUTES#####
    included_subpackages: Set[ModuleType] = set()  # TODO: Consider if needed?
    #####################################################
    plugins_predicate: Callable[..., bool] = None

    @validator('plugins_predicate')
    def prevent_plugins_predicate_none(cls, plugins_predicate: Callable[..., bool]) -> Callable[..., bool]:
        assert plugins_predicate, f"field can't be None"
        return plugins_predicate

    def load_subclasses(self, ancestor_class: Type[T]) -> List[Type[T]]:
        return self._load(lambda member: _is_subclass_predicate(member, ancestor_class))

    def load(self) -> List[Type[T]]:
        return self._load(self.plugins_predicate)

    def _load(self, plugins_predicate: Callable[..., bool]) -> List[Type[T]]:
        packages_paths: Set[PackagePath] = set()
        for plugins_package in self.plugins_packages:
            packages_paths |= self._generate_packages_paths(plugins_package)

        plugins = self._generate_plugins(packages_paths, plugins_predicate)
        return plugins

    def _generate_packages_paths(self, package: ModuleType) -> Set[PackagePath]:
        """
        Generates paths of all packages in the given package
        For example, if given package 'plugins' the returned list will look something like
         ['plugins.plugin1', 'plugins.plugin2']
        """
        packages_import_paths: Set[PackagePath] = set()
        excluded_prefixes = (_PRIVATE_PREFIX, ".")  # exclude inner directories

        package_relative_path = self._generate_package_relative_path(package)
        directory_tree = os.walk(package_relative_path)
        for package_directory, package_subdirectories, files in directory_tree:
            if package_directory.endswith(excluded_prefixes):
                continue
            packages_files = [
                f
                for f in files
                if Path(f).suffix == ".py"
                and not Path(f).stem.startswith(_PRIVATE_PREFIX)
                and re.match(self.included_files_pattern, f)
            ]  # remove private files

            for package_file in packages_files:
                package_file_relative_path = Path(package_directory) / package_file
                package_path = self._generate_package_import_path(package_file_relative_path)
                packages_import_paths.add(package_path)

            if self.full_depth_search:
                subdirectories_trees = self._generate_subdirectories_trees(package_directory, package_subdirectories)
                directory_tree = chain(directory_tree, subdirectories_trees)

        return packages_import_paths

    def _generate_package_relative_path(self, package: ModuleType) -> FileSystemPath:
        """
        Generates package's relative path (in relate to the current working directory)
        """
        package_path = package.__path__[0]
        return self._generate_directory_relative_path(package_path)

    def _generate_subdirectories_trees(self, package_directory: FileSystemPath,
                                       package_subdirectories: List[FileSystemPath]) -> \
            Iterator[Tuple[FileSystemPath, List[FileSystemPath], List[FileSystemPath]]]:

        subdirectories_trees = None
        package_subdirectories = [
            x
            for x in package_subdirectories
            if not x.startswith(_PRIVATE_PREFIX)
            and re.match(self.included_directories_pattern, x)
        ]
        for package_subdirectory in package_subdirectories:
            package_subdirectory_full_path = Path(package_directory) / package_subdirectory
            package_subdirectory_relative_path = self._generate_directory_relative_path(package_subdirectory_full_path)
            subdirectory_tree = os.walk(package_subdirectory_relative_path)
            if subdirectories_trees:
                subdirectories_trees = chain(subdirectories_trees, subdirectory_tree)
            else:
                subdirectories_trees = subdirectory_tree
        return subdirectories_trees

    # TODO: Can go out to path_utils
    @staticmethod
    def _generate_directory_relative_path(directory: Union[Path, FileSystemPath]) -> FileSystemPath:
        current_working_directory = Path.cwd()
        package_relative_path = os.path.relpath(directory, current_working_directory)
        return package_relative_path

    @staticmethod
    def _generate_package_import_path(package_file_relative_path: Path) -> PackagePath:
        """
        Generates a package import path that can be imported given a package file relative path.
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

    def _generate_plugins(self, packages_paths: Set[PackagePath], plugins_predicate: Callable[..., bool]) -> \
            List[Type[T]]:
        """
        Get all plugins located in `packages_paths` that satisfy the `plugins_predicate`
        """
        plugins: List[Type[T]] = []  # define the set of plugins
        missing_modules: List[str] = []

        for plugin_file_name in packages_paths:  # import each plugin's module
            try:
                plugin_module = importlib.import_module(plugin_file_name)
            except ModuleNotFoundError as e:
                if e.name not in missing_modules:
                    missing_modules.append(e.name)
                continue
            members = inspect.getmembers(plugin_module, plugins_predicate)
            plugins: Type[T]
            for _, plugin in members:
                if plugin not in plugins:
                    plugins.append(plugin)

        if missing_modules:
            self._handle_missing_modules(missing_modules)

        return plugins

    def _handle_missing_modules(self, missing_modules: List[str]) -> None:
        missing_modules_separated_by_comma = ", ".join(missing_modules)
        warning_message = (
            f"WARNING: Failed searching plugins in the following imported modules: "
            f"{missing_modules_separated_by_comma}.{os.linesep}"
            f"Consider running the following command: 'pip3 install {missing_modules_separated_by_comma}'."
        )
        if self.raise_exception_on_missing_modules:
            raise ModuleNotFoundError(warning_message)
        _logger.warning(warning_message)


def _is_subclass_predicate(member: Any, ancestor_class: Type[T]) -> bool:
    return (
        inspect.isclass(member) and
        member != ancestor_class and
        issubclass(member, ancestor_class)
    )
