"""Transit (server list) response.

Layout from ServerInfo$$GetServerlistReturn: every child of the root except the last
is a <server> (parsed by Server..ctor(XmlNode)); the last child holds global config.
Element names of the root/children are not checked, only the field names inside them.
"""
from xml.sax.saxutils import escape

from . import config


def _fields(d):
    return "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in d.items())


def server_list_xml():
    server = {
        "worldId": config.WORLD_ID,
        "addr": config.GAME_ADDR,
        "name": config.SERVER_NAME,
        "long_name": config.SERVER_NAME,
        "recommended": "1",
        "condition": "0",
        "passport_addr": config.PUBLIC_BASE + "/",
        "paycenter_addr": config.PUBLIC_BASE + "/",
        "dcenter_addr": config.PUBLIC_BASE + "/",
        "report_addr": config.PUBLIC_BASE + "/",
        "transit_addr": config.PUBLIC_BASE + "/",
        "ab_version": config.AB_VERSION,
        "naive_switch": "1",
    }
    cfg = {
        "notice_url": "",
        "update_start_time": "0",
        "update_end_time": "0",
        "client_version": config.CLIENT_VERSION,
        "top_client_version": config.CLIENT_VERSION,
        "version_desc": "",
        "login_queue_switch": "0",
    }
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f"<servers><server>{_fields(server)}</server><config>{_fields(cfg)}</config></servers>")
