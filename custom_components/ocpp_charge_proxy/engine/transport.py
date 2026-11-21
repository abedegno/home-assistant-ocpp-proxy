"""Stable WebSocket interface on current websockets releases.

Use the supported legacy API explicitly while migrating the transport independently
from the protocol engine. Other HA integrations can use the newer API concurrently.
"""

from websockets import exceptions
from websockets.exceptions import WebSocketException, ConnectionClosed
from websockets.legacy.client import connect, WebSocketClientProtocol
from websockets.legacy.server import serve
