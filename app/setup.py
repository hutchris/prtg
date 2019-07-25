#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
`setuptools` Distribution for prtg
"""

# System  Imports
import codecs
import os
import re

# External Imports
from setuptools import find_packages, setup

PACKAGE_NAME = 'prtg'


def load_readme(fname):
    """
    Read the contents of relative `README` file.
    """
    file_path = os.path.join(os.path.dirname(__file__), fname)
    with codecs.open(file_path, encoding='utf-8') as fobj:
        sub = (
            '(https://github.com/'
            'timgates42/prtg'
            '/blob/master/\\g<1>)'
        )
        markdown_fixed = re.sub(
            '[(]([^)]*[.](?:md|rst))[)]',
            sub,
            fobj.read(),
        )
        rst_fixed = re.sub(
            '^[.][.] [_][`][^`]*[`][:] ([^)]*[.](?:md|rst))',
            sub,
            markdown_fixed
        )
        return rst_fixed


def read_version():
    """
    Read the contents of relative file.
    """
    file_path = os.path.join(
        os.path.dirname(__file__), PACKAGE_NAME, 'version.py'
    )
    regex = re.compile('__version__ = [\'\"]([^\'\"]*)[\'\"]')
    with codecs.open(file_path, encoding='utf-8') as fobj:
        for line in fobj:
            mobj = regex.match(line)
            if mobj:
                return mobj.group(1)
    raise Exception('Failed to read version')


setup(
    name=PACKAGE_NAME,
    version=read_version(),
    author='Chris Hutchings',
    author_email='hutchris@gmail.com',
    maintainer='Tim Gates',
    maintainer_email='tim.gates@iress.com',
    packages=find_packages(exclude=['tests']),
    license='MIT',
    description=(
        'Python module to manage PRTG servers'
    ),
    long_description=load_readme('README.md'),
    long_description_content_type='text/markdown',
    python_requires='>=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*',
    install_requires=[
        elem for elem in
        'bs4\nclick\nfuture\nlxml\nrequests'.split('\n')
        if elem
    ],
    url='https://github.com/timgates42/prtg',
    classifiers=[elem for elem in [
        'Development Status :: 4 - Beta',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy',
        'Operating System :: OS Independent',
        'License :: OSI Approved :: MIT License',
    ] if elem],
)
