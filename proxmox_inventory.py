#!/usr/bin/env python3
import argparse
import json
import os
import re

import requests
import socket
import sys

from requests.exceptions import RequestException, Timeout, HTTPError

DEBUG = False


def call_api(url: str, auth: dict, direction: str = 'get', timeout: int = 10):
    if not isinstance(url, str) or not url:
        raise ValueError('Invalid URL. The URL must be a non-empty string')

    try:
        if direction == 'get':
            debug('Calling Get', 2)
            response = requests.get(
                url,
                cookies=auth,
                timeout=timeout,
                verify=True  # This ensures SSL certificates are verified
            )
        else:
            debug('Calling Post', 2)
            response = requests.post(
                url,
                data=auth,
                timeout=timeout,
                verify=True  # This ensures SSL certificates are verified
            )

        # Raise an exception for HTTP error responses
        response.raise_for_status()

        debug(f"API Status: {response.status_code} {response.reason}")
        debug(f"API Return: {response.text}")

        # Attempt to parse and return the JSON response data
        return response.json()

    except Timeout:
        print(f"Request timed out after {timeout} seconds.")
        raise

    except HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
        raise

    except RequestException as req_err:
        print(f"Request error occurred: {req_err}")
        raise

    except ValueError as json_err:
        print(f"Error parsing JSON response: {json_err}")
        raise


def create_inventory(node_list: dict, add_ip: bool = True) -> dict:
    # Initialize the inventory dictionary
    inventory = {
        'all': {
            'hosts': [],
            'children': []
        },
        '_meta': {
            'hostvars': {}
        }
    }

    # Define the structure for hostvars
    hostvar_fields = {
        'proxmox_host': lambda node: node['node']
    }
    if add_ip:
        hostvar_fields['ansible_host'] = lambda node: socket.gethostbyname(node['name'])

    # Function to create a final tag name
    def format_tag(raw_tag):
        return re.sub(r'[^a-zA-Z]+', '_', raw_tag).strip('_').lower() + '_servers'

    # Process each node in the node_list
    for node in node_list.get('data', []):
        if node['type'] in {'qemu', 'lxc'}:
            debug(json.dumps(node, indent=2), 3)

            # Add hostvars to inventory
            inventory['_meta']['hostvars'][node['name']] = {key: func(node) for key, func in hostvar_fields.items()}

            # Process and add tags
            for tag in filter(None, (t.strip() for t in node.get('tags', '').split(';'))):
                final_tag = format_tag(tag)
                debug(f"Final tag: {final_tag}", 3)

                # Add to children and create group if necessary
                if final_tag not in inventory['all']['children']:
                    debug(f"Adding group: {final_tag}", 3)
                    inventory['all']['children'].append(final_tag)

                if final_tag not in inventory:
                    debug(f"Creating group: {final_tag}", 3)
                    inventory[final_tag] = {'hosts': []}

                # Add node to the group
                inventory[final_tag]['hosts'].append(node['name'])

    return inventory

def debug(msg='', debug_msg_level=1, out=sys.stdout) -> None:
    if DEBUG and debug_msg_level <= debug_level:
        if msg != '':
            if debug_level > 1:
                out.write(f"DEBUG[{debug_msg_level}]: {msg}")
            else:
                out.write(f"DEBUG: {msg}")
        out.write('\n')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-l', '--debug_level', type=int, choices=[1, 2, 3],
                        help='Set debug level (enabled debugging)')
    parser.add_argument('--list', action='store_true', dest='list_instances',
                        help='Output AAP Inventory (default: false)')
    parser.add_argument('--host', action='store', dest='proxmox_host', default='proxmox0',
                        help='Proxmox host to use for inventory src')
    parser.add_argument('--user', action='store', dest='TOWER_USERNAME', help='ProxMox user')
    parser.add_argument('--pass', action='store', dest='TOWER_PASSWORD', help='ProxMox password')

    return parser.parse_args()


if __name__ == '__main__':

    args = parse_args()

    if args.list_instances:
        DEBUG = False
    elif args.debug_level:
        DEBUG = True
        debug_level = args.debug_level
        debug(f"Set debug level to {debug_level}")

    debug(f"Arguments: {args}")

    for variable in ['TOWER_PASSWORD', 'TOWER_USERNAME']:
        if args.__dict__[variable]:
            debug(f"Setting {variable} from arguments")
            exec(variable + f' = {args.__dict__[variable]}')
        else:
            debug(f"Setting {variable} from environment")
            exec(variable + f' = {os.environ.get(variable)}')

        if variable != 'TOWER_PASSWORD':
            debug(f"Variable: {variable} = {globals()[variable]}")

        if globals()[variable] is None:
            print(f"Unable to source required variable '{variable}'")
            exit(1)

    if 'proxmox_host' in os.environ:
        proxmox_server = os.environ['proxmox_host']
    elif args.proxmox_host:
        proxmox_server = args.proxmox_host
    else:
        print('Unable to determine ProxMox server')
        exit(1)

    debug(f"Proxmox Server: {proxmox_server}")

    auth_url = f"https://{proxmox_server}:8006/api2/json/access/ticket"
    auth_cred = {
        'username': TOWER_USERNAME,
        'password': TOWER_PASSWORD
    }

    debug(f"API Auth Creds: {auth_cred}")

    token = {
        'PVEAuthCookie': call_api(auth_url, auth_cred, 'put')['data']['ticket']
    }
    debug(f"API Token: {token}")

    auth_url = f"https://{proxmox_server}:8006/api2/json/cluster/resources"

    nodes = call_api(auth_url, token)
    debug(f"API Nodes: {nodes}")

    inventory_blob = create_inventory(nodes)
    debug('Inventory:')
    debug(json.dumps(inventory_blob, indent=2))

    if args.list_instances:
        print(json.dumps(inventory_blob, indent=4))
