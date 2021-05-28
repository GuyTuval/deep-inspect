import re

import setuptools


def get_version(path: str) -> str:
    with open(path) as f:
        content = f.read()
        version_match = re.search(r'".*"', content)
        if version_match:
            version = version_match.group()[1:-1]
            return version
        raise RuntimeError("No version was defined")


def get_long_description(path: str) -> str:
    with open(path) as f:
        long_description = f.read()
        return long_description


setuptools.setup(
    name="loadit",
    version=get_version('loadit/__init__.py'),
    author="Guy Tuval",
    author_email="guytuval@gmail.com",
    description="A library for dynamically loading plugins",
    license="GNU GPLv3",
    long_description=get_long_description("README.md"),
    long_description_content_type="text/markdown",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "License :: OSI Approved :: MIT License",
        "Intended Audience :: Developers",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Operating System :: OS Independent",
    ],
    url="https://github.com/GuyTuval/loadit",
    project_urls={
        "Source": "https://github.com/GuyTuval/loadit",
        "Bug Tracker": "https://github.com/GuyTuval/loadit/issues",
    },
    install_requires=[
        "pydantic >= 1.7.1",
        "pytest >= 6.1.1"
    ],
    python_requires=">=3.6",
)
