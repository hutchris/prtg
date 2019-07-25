"""
Module load handler for execution via:

python -m prtg
"""
from __future__ import absolute_import, division, print_function

import getpass

import click
from six.moves.urllib.parse import urlparse

from .client import PRTGApi
from .version import __version__ as app_version

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


def get_api(**kwargs):
    """
    Handle command line arguments to construct API object
    """
    url = kwargs['url']
    urlp = urlparse(url)
    passhash = getpass.getpass('PassHash: ')
    api = PRTGApi(
        host=urlp.hostname,
        user=kwargs['user'],
        passhash=passhash,
        rootid=kwargs['rootid'],
        protocol=urlp.scheme,
        port=urlp.port if urlp.port else {
            'https': 443,
            'http': 80,
        }[urlp.scheme],
    )
    return api


def show_probe_or_group(obj):
    """
    Display and descend a nested element
    """
    print(repr(obj))
    for probe in obj.probes:
        show_probe_or_group(probe)
    for group in obj.groups:
        show_probe_or_group(group)
    for device in obj.devices:
        print(repr(device))
        for sensor in device.sensors:
            print(repr(sensor))


def run_show(**kwargs):
    """
    Display Groups and Devices under the specified rootid
    """
    api = get_api(**kwargs)
    show_probe_or_group(api)


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(version=app_version)
def main():
    """
    Click Main Entry Point
    """


@main.command()
@click.argument('url')
@click.option('--user', default='admin', help='Authentication Username')
@click.option('--rootid', default=0, help='PRTG ID of Root Node to Display')
def show(**kwargs):
    """
    Runs the display command
    """
    run_show(**kwargs)


if __name__ == '__main__':
    main()
