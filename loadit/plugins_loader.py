import importlib
import inspect
import logging
import os
import re
from itertools import chain
from pathlib import Path
from types import ModuleType
from typing import (Any, Callable, Final, Iterator, List, Pattern,
                    Set, Tuple, Type, TypeVar, Union)

from pydantic import BaseModel

__all__ = ["get_subclasses", "get_members"]
logger = logging.getLogger(__name__)

T = TypeVar("T")
FileSystemPath = Union[str, Path]
PackagePath = Union[str, Path]  # string/Path that matches the pattern r"([a-z]*_?[a-z]*(\.([a-z]*_?[a-z])*)?)+"

_PRIVATE_PREFIX: Final = "__"
_INSTALLED_PACKAGES_DIRECTORY: Final = "site-packages"


def get_subclasses(
        ancestor_class: Type[T],
        members_packages: Union[ModuleType, Set[ModuleType]],
        *,
        raise_exception_on_missing_modules: bool = False,
        full_depth_search: bool = True,
        included_files_pattern: Pattern[str] = re.compile(r".*"),
        included_subdirectories_pattern: Pattern[str] = re.compile(r".*")) -> List[Type[T]]:
    """
    Load all subclasses (direct and indirect + dynamically created at import time) of `ancestor_class`
    :param ancestor_class: The ancestor of the subclasses
    :param members_packages: A package or a list of packages to look the subclasses at
    :param raise_exception_on_missing_modules: Whether to raise exception in case of missing module in the used package
    or not
    :param full_depth_search: Whether to go deeper in search of the members or just search in the packages depth
    :param included_files_pattern: A regex of the acceptable module files names
    :param included_subdirectories_pattern: A regex of the acceptable package subdirectories names
    :return: A list of all subclasses of the ancestor
    """

    members_inspector = _create_members_inspector(
        members_packages=members_packages,
        raise_exception_on_missing_modules=raise_exception_on_missing_modules,
        full_depth_search=full_depth_search,
        included_files_pattern=included_files_pattern,
        included_subdirectories_pattern=included_subdirectories_pattern
    )
    return members_inspector.get_subclasses(ancestor_class)


def get_members(members_packages: Union[ModuleType, Set[ModuleType]],
                members_predicate: Callable[..., bool],
                *,
                raise_exception_on_missing_modules: bool = False,
                full_depth_search: bool = True,
                included_files_pattern: Pattern[str] = re.compile(r".*"),
                included_subdirectories_pattern: Pattern[str] = re.compile(r".*")) -> List[Type[T]]:
    """
    Load all members that satisfy the `members_predicate`
    :param members_packages: A package or a list of packages the members at
    :param members_predicate: A function that decides whether a member satisfies our requirements or not
    :param raise_exception_on_missing_modules: Whether to raise exception in case of missing module in the used package
    or not
    :param full_depth_search: Whether to go deeper in search of the members or just search in the packages depth
    :param included_files_pattern: A regex of the acceptable module files names
    :param included_subdirectories_pattern: A regex of the acceptable package subdirectories names
    :return: A list of all subclasses of the ancestor
    """

    members_inspector = _create_members_inspector(
        members_packages=members_packages,
        raise_exception_on_missing_modules=raise_exception_on_missing_modules,
        full_depth_search=full_depth_search,
        included_files_pattern=included_files_pattern,
        included_subdirectories_pattern=included_subdirectories_pattern,
        members_predicate=members_predicate
    )
    return members_inspector.get_members()


def _create_members_inspector(*, members_packages: Union[ModuleType, Set[ModuleType]],
                              raise_exception_on_missing_modules: bool = False,
                              full_depth_search: bool = True,
                              included_files_pattern: Pattern[str] = re.compile(r".*"),
                              included_subdirectories_pattern: Pattern[str] = re.compile(r".*"),
                              members_predicate: Callable[..., bool] = lambda member: False):
    """
    Creates a `PluginsLoader`
    :param members_packages: A package or a list of packages to look the members at
    :param full_depth_search: Whether to go deeper in search of the members or just search in the packages depth
    :param raise_exception_on_missing_modules: Whether to raise exception in case of missing module in the used package
    or not
    :param included_files_pattern: A regex of the acceptable module files names
    :param included_subdirectories_pattern: A regex of the acceptable package subdirectories names
    :param members_predicate: A function that decides whether a member satisfies our requirements or not
    :return: The Created `PluginsLoader` instance
    """
    members_inspector = MembersInspector(
        members_packages=members_packages,
        raise_exception_on_missing_modules=raise_exception_on_missing_modules,
        full_depth_search=full_depth_search,
        included_files_pattern=included_files_pattern,
        included_subdirectories_pattern=included_subdirectories_pattern,
        members_predicate=members_predicate
    )
    return members_inspector


class MembersInspector(BaseModel):
    """
    A class used for loading members dynamically.
    """

    class Config:
        arbitrary_types_allowed = True

    members_packages: Union[ModuleType, Set[ModuleType]]
    raise_exception_on_missing_modules: bool = False
    full_depth_search: bool = True
    included_files_pattern: Pattern[str] = re.compile(r".*")
    included_subdirectories_pattern: Pattern[str] = re.compile(r".*")
    members_predicate: Callable[..., bool] = lambda member: False

    def get_subclasses(self, ancestor_class: Type[T]) -> List[Type[T]]:
        """Get all subclasses in ``self.members_packages`` that are subclasses of ``ancestor_class``"""
        return self._get_members(lambda member: _is_member_subclass_of_ancestor(member, ancestor_class))

    def get_members(self) -> List[Type[T]]:
        """Get all members in ``self.members_packages`` that satisfy ``members_predicate``"""
        return self._get_members(self.members_predicate)

    def _get_members(self, members_predicate: Callable[..., bool]) -> List[Type[T]]:
        """Get all members in ``self.members_packages`` that satisfy ``members_predicate``"""
        packages_paths: Set[PackagePath] = set()
        members_packages = self.members_packages if isinstance(self.members_packages, set) else {self.members_packages}
        for members_package in members_packages:
            packages_paths |= self._generate_packages_paths_from_module(members_package)

        members: List[Type[T]] = self._load_members(packages_paths, members_predicate)
        return members

    def _generate_packages_paths_from_module(self, package: ModuleType) -> Set[PackagePath]:
        """
        Generates ``PackagePath``-s of all packages in ``package``.
        For example, if ``package`` is 'my_package' the returned list will look something like
        ['my_package.first_file', 'my_package.second_file']
        """
        packages_paths: Set[PackagePath] = set()
        excluded_prefixes = (_PRIVATE_PREFIX, ".")  # exclude inner directories

        package_relative_path = self._generate_package_relative_path(package)
        directory_tree = os.walk(package_relative_path)
        for package_directory, package_subdirectories, package_files in directory_tree:
            if Path(package_directory).name.endswith(excluded_prefixes):
                continue
            packages_paths |= self._generate_packages_paths_from_files(package_directory, package_files)

            if self.full_depth_search:
                subdirectories_trees = self._generate_subdirectories_trees(package_directory, package_subdirectories)
                directory_tree = chain(directory_tree, subdirectories_trees)

        return packages_paths

    def _generate_package_relative_path(self, package: ModuleType) -> FileSystemPath:
        """Generates a ``FileSystemPath`` of ``package``'s  relative to ``current_working_directory``"""
        package_path: FileSystemPath = package.__path__[0]
        return self._generate_directory_relative_path(package_path)

    def _generate_packages_paths_from_files(self,
                                            package_directory: FileSystemPath,
                                            package_files: List[str]) -> Set[PackagePath]:
        packages_paths: Set[PackagePath] = set()
        packages_files_relative_paths = [
            Path(package_directory) / f for f in package_files if self._is_acceptable_package_file(f)
        ]  # remove private files

        for package_file_relative_path in packages_files_relative_paths:
            package_path = self._generate_package_path(package_file_relative_path)
            packages_paths.add(package_path)

        return packages_paths

    def _is_acceptable_package_file(self, package_file: FileSystemPath) -> bool:
        """Checks if ``package_file`` is one which we want to look at"""
        package_file_path = Path(package_file)
        return (
                package_file_path.suffix == ".py"
                and not package_file_path.name.startswith(_PRIVATE_PREFIX)
                and re.match(self.included_files_pattern, package_file) is not None
        )

    def _generate_subdirectories_trees(self, package_directory: FileSystemPath,
                                       package_subdirectories: List[FileSystemPath]) -> \
            Iterator[Tuple[FileSystemPath, List[FileSystemPath], List[FileSystemPath]]]:

        subdirectories_trees: Iterator[Tuple[FileSystemPath, List[FileSystemPath], List[FileSystemPath]]]
        subdirectories_trees = chain.from_iterable([])
        package_subdirectories_full_paths = [
            Path(package_directory) / directory for directory in package_subdirectories
            if self._is_acceptable_package_subdirectory(directory)
        ]
        for package_subdirectory_full_path in package_subdirectories_full_paths:
            subdirectory_tree = self._generate_subdirectory_tree(package_subdirectory_full_path)
            subdirectories_trees = chain(subdirectories_trees, subdirectory_tree)
        return subdirectories_trees

    def _generate_subdirectory_tree(self, package_subdirectory_full_path: Path) -> \
            Iterator[Tuple[FileSystemPath, List[FileSystemPath], List[FileSystemPath]]]:

        package_subdirectory_relative_path = self._generate_directory_relative_path(package_subdirectory_full_path)
        subdirectory_tree = os.walk(package_subdirectory_relative_path)
        return subdirectory_tree

    def _is_acceptable_package_subdirectory(self, package_subdirectory: FileSystemPath) -> bool:
        """Checks if ``package_subdirectory`` is one which we want to look at"""
        return (
                not package_subdirectory.startswith(_PRIVATE_PREFIX)
                and re.match(self.included_subdirectories_pattern, package_subdirectory) is not None
        )

    # TODO: Can go out to path_utils
    @staticmethod
    def _generate_directory_relative_path(directory: FileSystemPath) -> FileSystemPath:
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
        package_path: PackagePath = package_posix_path.replace("/", ".").lstrip(".")

        # remove prefix path containing `_INSTALLED_PACKAGES_DIRECTORY` directory
        # (for example, useful for virtual environments)
        package_path: PackagePath = package_path.split(f"{_INSTALLED_PACKAGES_DIRECTORY}.")[-1]
        return package_path

    def _load_members(self, packages_paths: Set[PackagePath], members_predicate: Callable[..., bool]) -> List[Type[T]]:
        """Load all members located in ``packages_paths`` that satisfy the ``members_predicate``"""
        members: List[Type[T]] = []  # define the list of members
        missing_modules: List[str] = []

        for package_path in packages_paths:
            try:
                module = importlib.import_module(package_path)
            except ModuleNotFoundError as e:
                if not e.name:
                    raise e
                if e.name not in missing_modules:
                    missing_modules.append(e.name)
                continue
            module_members = inspect.getmembers(module, members_predicate)
            member: Type[T]
            for _, member in module_members:
                if member not in members:  # use this condition instead of set because T isn't necessarily hashable
                    members.append(member)

        if missing_modules:
            self._handle_missing_modules(missing_modules)

        return members

    def _handle_missing_modules(self, missing_modules: List[str]) -> None:
        """
        Logs missing modules (or raises ModuleNotFoundError, depending
        on self.raise_exception_on_missing_modules value)

        :param missing_modules: Modules failed to be loaded
        :raises ModuleNotFoundError: in case of self.raise_exception_on_missing_modules being True
        """
        missing_modules_separated_by_comma = ", ".join(missing_modules)
        warning_message = (
            f"WARNING: Failed searching members in the following imported modules: "
            f"{missing_modules_separated_by_comma}.{os.linesep}"
            f"Consider running the following command: 'pip3 install {missing_modules_separated_by_comma}'."
        )
        if self.raise_exception_on_missing_modules:
            raise ModuleNotFoundError(warning_message)
        logger.warning(warning_message)


def _is_member_subclass_of_ancestor(member: Any, ancestor_class: Type[T]) -> bool:
    return (
            inspect.isclass(member) and
            member != ancestor_class and
            issubclass(member, ancestor_class)
    )
