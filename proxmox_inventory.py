import argparse
import json
import os
import re
import requests
import socket
import sys
from requests.exceptions import RequestException, Timeout, HTTPError

DEBUG = False
debug_level = 1
GROUP_VARS = {
    'postfix': {
        'postfix_role': 'master'
    }
}

def bootstrap_auth_session(args: argparse.Namespace) -> dict:
    """
    Authenticate against the Proxmox API using provided credentials.

    :param args: Parsed command-line arguments
    :return: Dictionary containing auth cookie
    """
    auth_url = f"https://{args.proxmox_host}:8006/api2/json/access/ticket"
    auth_cred = {'username': args.TOWER_USERNAME, 'password': args.TOWER_PASSWORD}
    try:
        response = requests.post(auth_url, data=auth_cred, timeout=10, verify=True)
        response.raise_for_status()
        ticket = response.json()['data']['ticket']
        debug("Auth ticket acquired", 2)
        return {'PVEAuthCookie': ticket}
    except (RequestException, HTTPError, Timeout) as e:
        sys.stderr.write(f"[ERROR] Authentication failed: {e}\n")
        sys.exit(1)

def debug(msg='', debug_msg_level=1, out=sys.stdout) -> None:
    """
    Prints the debug message if debug mode is enabled and the debug level is less than or equal to the debug level.

    :param msg: A string that represents the message to be printed. Default is an empty string.
    :param debug_msg_level: An integer that represents the debug message level. Default is 1.
    :param out: The output stream where the debug message will be printed. Default is sys.stdout.
    :return: None
    """
    if DEBUG and debug_msg_level <= debug_level:
        if msg != '':
            if debug_level > 1:
                out.write(f"DEBUG[{debug_msg_level}]: {msg}")
            else:
                out.write(f"DEBUG: {msg}")
        out.write('\n')

def filter_valid_nodes(nodes: list, skip_list: list) -> list:
    """
    Filter out non-relevant or undesired nodes from Proxmox API result.

    :param nodes: List of node dictionaries
    :param skip_list: List of node names to exclude
    :return: Filtered list of valid nodes
    """
    valid_nodes = []
    for node in nodes:
        try:
            debug(f"Evaluating node: {json.dumps(node)}", 3)
            if is_valid_node(node, skip_list):
                debug(f"Accepted node: {node['name']}", 2)
                valid_nodes.append(node)
            else:
                debug(f"Rejected node: {node['name']}", 2)
        except KeyError as e:
            debug(f"Skipping malformed node entry due to missing key: {e}", 1)
    return valid_nodes

def generate_hostvars(node: dict, add_ip: bool = True) -> dict:
    """
    Generate hostvars block for a given node.

    :param node: Dictionary representing a single Proxmox VM/container
    :param add_ip: Boolean flag whether to resolve and include IP address
    :return: Hostvars dictionary for that host
    """
    hostvars = {'proxmox_host': node['node']}
    if add_ip:
        try:
            hostvars['ansible_host'] = socket.gethostbyname(node['name'])
        except socket.gaierror:
            debug(f"Could not resolve IP for host {node['name']}", 3)
    return hostvars

def get_env_var(name: str, fallback: str = None) -> str:
    """
    Return environment variable or fallback if not present. Exit if neither.

    :param name: Environment variable name
    :param fallback: Optional fallback string
    :return: Value for use in logic or exit with error if not found
    """
    value = os.environ.get(name, fallback)
    if not value:
        sys.stderr.write(f"[ERROR] Required environment variable '{name}' not set.\n")
        sys.exit(1)
    return value

def is_valid_node(node: dict, skip_list: list) -> bool:
    """
    Determine if a Proxmox node should be included in the inventory.

    :param node: Node dictionary from API
    :param skip_list: Hostnames to exclude from inventory
    :return: Boolean indicating if node is valid
    """
    node_type = node.get('type')
    node_name = node.get('name', '').lower()
    status = node.get('status')

    if node_type not in {'qemu', 'lxc'}:
        debug(f"Rejected {node.get('name')} — unsupported type '{node_type}'", 2)
        return False
    if status != 'running':
        debug(f"Rejected {node.get('name')} — status '{status}' is not 'running'", 2)
        return False
    if node_name in skip_list:
        debug(f"Rejected {node.get('name')} — explicitly skipped", 2)
        return False
    if 'template' in node_name:
        debug(f"Rejected {node.get('name')} — appears to be a template", 2)
        return False

    debug(f"Validated {node.get('name')}", 2)
    return True

def main() -> None:
    """
    Primary orchestration routine for inventory generation logic.
    """
    global DEBUG, debug_level
    args = parse_args()

    if args.list_instances:
        DEBUG = False
    elif args.debug_level:
        DEBUG = True
        debug_level = args.debug_level
        debug(f"Set debug level to {debug_level}")

    debug(f"Arguments: {args}")

    args.TOWER_USERNAME = args.TOWER_USERNAME or get_env_var('TOWER_USERNAME')
    args.TOWER_PASSWORD = args.TOWER_PASSWORD or get_env_var('TOWER_PASSWORD')
    args.proxmox_host = args.proxmox_host or os.environ.get('proxmox_host')

    if not args.proxmox_host:
        sys.stderr.write("[ERROR] Unable to determine ProxMox server\n")
        sys.exit(1)

    token = bootstrap_auth_session(args)
    nodes = retrieve_proxmox_nodes(token, args.proxmox_host)

    skip_hosts = [host.strip() for host in args.skip_hosts.split(',') if host.strip()]
    inventory_blob = create_inventory(nodes, skip_hosts)

    debug("Final Inventory:", 2)
    debug(json.dumps(inventory_blob, indent=2), 3)

    if args.list_instances:
        print(json.dumps(inventory_blob, indent=4))

def parse_args() -> argparse.Namespace:
    """
    Parse CLI arguments for inventory script behavior and debugging.

    :return: argparse.Namespace with parsed flags and values
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('-l', '--debug_level', type=int, choices=[1, 2, 3],
                        help='Set debug level (enabled debugging)')
    parser.add_argument('--list', action='store_true', dest='list_instances',
                        help='Output AAP Inventory (default: false)')
    parser.add_argument('--host', action='store', dest='proxmox_host', default='proxmox0',
                        help='Proxmox host to use for inventory src')
    parser.add_argument('--user', action='store', dest='TOWER_USERNAME', help='ProxMox user')
    parser.add_argument('--pass', action='store', dest='TOWER_PASSWORD', help='ProxMox password')
    parser.add_argument('--skip', action='store', dest='skip_hosts', default='',
                        help='Comma-separated list of hosts to skip')
    return parser.parse_args()

def process_tags(node: dict, inventory: dict) -> None:
    """
    Add tag-based grouping and group_vars to the inventory.

    :param node: Dictionary representing a single node with 'tags' field
    :param inventory: The main inventory dictionary to update
    :return: None
    """
    tags = filter(None, (t.strip() for t in node.get('tags', '').split(';')))
    for tag in tags:
        group = re.sub(r'[^a-zA-Z]+', '_', tag).strip('_').lower()
        inventory.setdefault(group, {'hosts': []})
        inventory[group]['hosts'].append(node['name'])

        if group not in inventory['all']['children']:
            inventory['all']['children'].append(group)

        if group in GROUP_VARS:
            inventory[group].setdefault('vars', {}).update(GROUP_VARS[group])

def retrieve_proxmox_nodes(token: dict, server: str) -> dict:
    """
    Pull full cluster resource data from Proxmox API using provided session token.

    :param token: Auth session dictionary
    :param server: Hostname of Proxmox instance
    :return: Parsed node list JSON
    """
    resource_url = f"https://{server}:8006/api2/json/cluster/resources"
    try:
        response = requests.get(resource_url, cookies=token, timeout=10, verify=True)
        response.raise_for_status()
        debug("Cluster data retrieved", 2)
        debug(json.dumps(response.json(), indent=2), 3)
        return response.json()
    except (RequestException, Timeout, HTTPError) as e:
        sys.stderr.write(f"[ERROR] Failed to retrieve cluster data: {e}\n")
        sys.exit(1)

def create_inventory(node_list: dict, skip_hosts: list = None, add_ip: bool = True) -> dict:
    """
    Generate an Ansible-style dynamic inventory from Proxmox node API output.

    :param node_list: Parsed JSON of nodes from Proxmox API
    :param skip_hosts: List of hosts to omit
    :param add_ip: Whether to resolve and include IP addresses in hostvars
    :return: Dictionary formatted to meet Ansible dynamic inventory spec
    """
    inventory = {
        'all': {'hosts': [], 'children': []},
        '_meta': {'hostvars': {}}
    }

    skip_hosts = skip_hosts or []
    filtered_nodes = filter_valid_nodes(node_list.get('data', []), skip_hosts)

    for node in filtered_nodes:
        node_type = node['type']
        node_name = node['name']

        inventory.setdefault(node_type, {'hosts': []})
        inventory[node_type]['hosts'].append(node_name)
        if node_type not in inventory['all']['children']:
            inventory['all']['children'].append(node_type)

        inventory['_meta']['hostvars'][node_name] = generate_hostvars(node, add_ip)
        process_tags(node, inventory)

    return inventory

if __name__ == '__main__':
    main()
