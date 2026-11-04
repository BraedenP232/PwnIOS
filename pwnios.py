import json
import logging
import asyncio
import websockets
from websockets.asyncio.server import serve
import threading
import base64
import os
import hmac
import pwnagotchi
from datetime import datetime
import time
import sys
import math

import pwnagotchi.plugins as plugins
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK

# Configuration values
# /etc/pwnagotchi/config.toml

# main.custom_plugin_repos = [
#     "https://github.com/BraedenP232/pwnios/archive/main.zip",
# ]

#[main.plugins.pwnios]
#enabled = true

# Display
#port = 8082
#display = false
#display_gps = false

# PiSugar
#pisugar = false

# Authentication (optional)
# Generate a token with: python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
#authentication_required = true
#auth_token = "paste-generated-token-here"

# GPS
#save_gps_log = true
#gps_log_path = "/tmp/pwnagotchi_gps.log"
#gps_altitude = 10

# Use MockPiSugarModule initially or else PiSugar import errors will occur at startup
class _MockPiSugarModule:
    class PiSugarServer:
        def __init__(self, *args, **kwargs):
            pass
        @property
        def battery_level(self) -> float:
            return 0.0
        @property
        def battery_charging(self) -> bool:
            return False
        def get_battery_level(self) -> float:
            return 0.0
        def get_battery_charging(self) -> bool:
            return False

class PwnIOS(plugins.Plugin):
    __author__ = "PellTech"
    __version__ = "2.0.0"
    __license__ = "GPL3"
    __description__ = "Plugin for iOS companion app to display Pwnagotchi stats, share GPS, and control features."

    def __init__(self):
        self.running = False
        self.agent = None
        self.start_time = datetime.now()

        self.gps_data = None
        self.gps_enabled = False
        self.last_gps_update = None

        self.websocket_server = None
        self.connected_clients = set()
        self.authenticated_clients = set()
        self.client_health = {}
        self.loop = None
        self.message_queue = None
        self.server_thread = None
        self.server_stopped = None

        self.broadcaster_task = None
        self.heartbeat_task = None

        self.pisugar = None
        self.last_face = None
        self.last_status = None
        self.ui_update_counter = 0
        self.session_handshakes = []

    def _init_pisugar(self):
        # Read user config
        pisugar_enabled = self.options.get("pisugar", False)

        if not pisugar_enabled:
            logging.info("[PwnIOS] PiSugar disabled in config — using mock")
            self.pisugar = _MockPiSugarModule.PiSugarServer()
            return

        # Try to import PiSugar dynamically (config requires it)
        try:
            import importlib
            pisugarx = importlib.import_module(
                "pwnagotchi.plugins.default.pisugarx"
            )
            logging.info("[PwnIOS] PiSugarX imported (config enabled)")
        except Exception as e1:
            try:
                import importlib.util, sys
                _py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
                PISUGARX_PATH = f"/home/pi/.pwn/lib/{_py_ver}/site-packages/pwnagotchi/plugins/default/pisugarx.py"
                spec = importlib.util.spec_from_file_location("pisugarx", PISUGARX_PATH)
                mod = importlib.util.module_from_spec(spec)
                sys.modules["pisugarx"] = mod
                spec.loader.exec_module(mod)
                pisugarx = mod
                logging.info(f"[PwnIOS] PiSugarX loaded from fallback path ({_py_ver})")
            except Exception as e2:
                logging.warning(
                    f"[PwnIOS] PiSugar requested but module unavailable: {e1}; {e2}"
                )
                self.pisugar = _MockPiSugarModule.PiSugarServer()
                return

        # Now that module exists, try initializing
        try:
            self.pisugar = pisugarx.PiSugarServer()
            logging.info("[PwnIOS] PiSugar initialized successfully")
        except Exception as e:
            logging.warning(
                f"[PwnIOS] PiSugar init failed ({e}) — using mock"
            )
            self.pisugar = _MockPiSugarModule.PiSugarServer()


    def on_loaded(self):
        self.running = True
        logging.info("[PwnIOS] Plugin loaded")

        self._init_pisugar()

        self.server_thread = threading.Thread(target=self._start_websocket_server, daemon=True)
        self.server_thread.start()

    def on_ready(self, agent):
        self.agent = agent
        logging.info(f"[PwnIOS] Agent ready (runtime mode: {self._get_runtime_mode()})")

    def on_unload(self, ui):
        logging.info("[PwnIOS] Plugin unloading...")
        self.running = False
        self._cleanup_resources()
        logging.info("[PwnIOS] Plugin unloaded")

    async def _handle_gps_data(self, websocket, full_message_data):
        try:
            gps_payload = full_message_data.get('data', {})

            latitude = gps_payload.get('latitude')
            longitude = gps_payload.get('longitude')
            accuracy = gps_payload.get('accuracy')
            numeric_values = (latitude, longitude)

            if any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(value) for value in numeric_values):
                await self._send_error(websocket, "GPS data error: invalid coordinates.")
                return

            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                await self._send_error(websocket, "GPS data error: coordinates out of range.")
                return

            if accuracy is not None and (
                isinstance(accuracy, bool)
                or not isinstance(accuracy, (int, float))
                or not math.isfinite(accuracy)
                or accuracy < 0
            ):
                await self._send_error(websocket, "GPS data error: invalid accuracy.")
                return

            self.gps_data = {
                'enabled': True,
                'latitude': latitude,
                'longitude': longitude,
                'accuracy': accuracy,
                'last_update': datetime.now().isoformat(),
                'phone_timestamp': gps_payload.get('timestamp'),
                'background_strategy': gps_payload.get('backgroundStrategy', 'live')
            }
            self.last_gps_update = datetime.now()
            self.gps_enabled = True

            logging.info(f"[PwnIOS] GPS data received: {self.gps_data['latitude']:.6f}, {self.gps_data['longitude']:.6f}")

            if self.options.get('save_gps_log', False):
                self._save_gps_log(self.gps_data)

            await self._broadcast_to_clients({
                "type": "gps_update",
                "data": self.gps_data
            })

            await websocket.send(json.dumps({
                "type": "gps_ack",
                "message_id": full_message_data.get('message_id'),
                "accepted_timestamp": self.gps_data['last_update']
            }))

        except Exception as e:
            logging.error(f"[PwnIOS] GPS data error: {e}")
            await self._send_error(websocket, f"GPS data error: {str(e)}")

    def _get_gps_data(self):
        if not self.gps_data or not self.gps_enabled:
            return None

        if self.last_gps_update:
            time_diff = (datetime.now() - self.last_gps_update).total_seconds()
            default_stale_seconds = (
                1800 if self.gps_data.get('background_strategy') == 'batterySaver' else 300
            )
            stale_seconds = self.options.get('gps_stale_seconds', default_stale_seconds)
            if time_diff > stale_seconds:
                self.gps_enabled = False
                return None

        return self.gps_data

    def _save_gps_log(self, gps_data):
        try:
            log_path = self.options.get('gps_log_path', '/tmp/pwnagotchi_gps.log')

            log_entry = {
                'timestamp': datetime.now().isoformat(),
                'latitude': gps_data['latitude'],
                'longitude': gps_data['longitude'],
                'accuracy': gps_data['accuracy']
            }

            with open(log_path, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')

        except Exception as e:
            logging.error(f"[PwnIOS] GPS log save error: {e}")

    async def _send_gps_data(self, websocket):
        gps_data = self._get_gps_data()
        await websocket.send(json.dumps({
            "type": "gps_data",
            "data": gps_data,
            "enabled": self.gps_enabled
        }))

    def _cleanup_resources(self):
        loop = self.loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._request_server_stop)
        elif self.websocket_server is not None:
            self.websocket_server.close()

    def _request_server_stop(self):
        if self.websocket_server is not None:
            self.websocket_server.close()
        if self.server_stopped is not None:
            self.server_stopped.set()

    def queue_message(self, message):
        try:
            if self.loop and self.loop.is_running() and self.message_queue:
                asyncio.run_coroutine_threadsafe(self.message_queue.put(message), self.loop)
        except Exception as e:
            logging.error(f"[PwnIOS] Error queuing message: {e}")

    def _start_websocket_server(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._run_server())
        finally:
            self._cleanup_loop()

    def _cleanup_loop(self):
        for task in asyncio.all_tasks(self.loop):
            task.cancel()
        self.loop.run_until_complete(
            asyncio.gather(*asyncio.all_tasks(self.loop), return_exceptions=True)
        )
        self.loop.close()

    async def _run_server(self):
        try:
            self.message_queue = asyncio.Queue()
            self.server_stopped = asyncio.Event()
            self.broadcaster_task = asyncio.create_task(self._message_broadcaster())
            self.heartbeat_task = asyncio.create_task(self._heartbeat_checker())

            host = str(self.options.get("host", "0.0.0.0"))
            port = int(self.options.get("port", 8082))
            self.websocket_server = await serve(
                self._handle_client, host, port,
                ping_interval=30, ping_timeout=20, close_timeout=10,
                max_size=2**20, compression=None, max_queue=32
            )

            sockets = self.websocket_server.sockets or []
            addresses = ", ".join(str(sock.getsockname()) for sock in sockets)
            logging.info(
                "[PwnIOS] WebSocket server %s started on %s (websockets %s)",
                self.__version__, addresses or f"{host}:{port}", websockets.__version__
            )
            await self.server_stopped.wait()

        except Exception:
            logging.exception("[PwnIOS] WebSocket server failed to start or stopped unexpectedly")
        finally:
            if self.websocket_server is not None:
                self.websocket_server.close()
                await self.websocket_server.wait_closed()
            await self._cleanup_server_tasks()

    async def _cleanup_server_tasks(self):
        for task in [self.broadcaster_task, self.heartbeat_task]:
            if task:
                task.cancel()
                try: await task
                except asyncio.CancelledError: pass

    async def _handle_client(self, websocket):
        client_addr = websocket.remote_address
        self.connected_clients.add(websocket)
        self.client_health[websocket] = time.time()
        authentication_required = bool(self.options.get("authentication_required", False))
        logging.info(f"[PwnIOS] iOS client connected: {client_addr}")

        try:
            await websocket.send(json.dumps({
                "type": "hello",
                "protocol_version": 2,
                "plugin_version": self.__version__,
                "capabilities": [
                    "command_results", "stats", "access_points",
                    "face_status", "face_image", "gps_data", "handshake_history",
                    "authentication"
                ],
                "authentication_required": authentication_required
            }))
            if not authentication_required:
                self.authenticated_clients.add(websocket)
                await self._send_initial_data(websocket)

            async for message in websocket:
                try:
                    self.client_health[websocket] = time.time()
                    data = json.loads(message)
                    await self._handle_client_message(websocket, data)
                except json.JSONDecodeError as e:
                    logging.error(f"[PwnIOS] Invalid JSON: {message} - {e}")
                    await self._send_error(websocket, "Invalid JSON format")
                except Exception as e:
                    logging.error(f"[PwnIOS] Message error: {e}")

        except websockets.exceptions.ConnectionClosed:
            logging.info(f"[PwnIOS] Client disconnected normally: {client_addr}")
        except Exception as e:
            logging.error(f"[PwnIOS] Client error: {e}")
        finally:
            self.connected_clients.discard(websocket)
            self.authenticated_clients.discard(websocket)
            self.client_health.pop(websocket, None)
            logging.info(f"[PwnIOS] Client disconnected: {client_addr}")

    async def _send_initial_data(self, websocket):
        logging.info("[PwnIOS] Sending initial data")
        await self._send_stats(websocket)
        await self._send_access_points(websocket)
        await self._send_handshakes(websocket)
        await self._send_face_status(websocket)

    async def _message_broadcaster(self):
        while self.running:
            try:
                message = await asyncio.wait_for(self.message_queue.get(), timeout=1.0)
                await self._broadcast_to_clients(message)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"[PwnIOS] Broadcaster error: {e}")
                await asyncio.sleep(0.1)

    async def _heartbeat_checker(self):
        while self.running:
            try:
                await asyncio.sleep(45)
                current_time = time.time()

                stale_clients = [
                    client for client, last_seen in self.client_health.items()
                    if current_time - last_seen > 60
                ]

                for client in stale_clients:
                    logging.info(f"[PwnIOS] Removing stale client: {client.remote_address}")
                    self.connected_clients.discard(client)
                    self.authenticated_clients.discard(client)
                    self.client_health.pop(client, None)
                    try: await client.close()
                    except: pass

                if self.connected_clients:
                    await self._broadcast_to_clients({
                        "type": "keepalive",
                        "timestamp": current_time
                    })

            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"[PwnIOS] Heartbeat checker error: {e}")

    async def _broadcast_to_clients(self, message):
        if not self.connected_clients:
            return

        json_message = json.dumps(message)
        dead_clients = set()

        async def send_to_client(client):
            try:
                await asyncio.wait_for(client.send(json_message), timeout=5.0)
            except asyncio.TimeoutError:
                logging.warning(f"[PwnIOS] Send timeout to client: {client.remote_address}")
                dead_clients.add(client)
            except Exception as e:
                logging.warning(f"[PwnIOS] Send error to client: {e}")
                dead_clients.add(client)

        await asyncio.gather(
            *[send_to_client(client) for client in list(self.authenticated_clients)],
            return_exceptions=True
        )

        for client in dead_clients:
            self.connected_clients.discard(client)
            self.authenticated_clients.discard(client)
            self.client_health.pop(client, None)

    async def _send_error(self, websocket, error_message):
        try:
            await websocket.send(json.dumps({
                "type": "error",
                "message": error_message
            }))
        except Exception as e:
            logging.error(f"[PwnIOS] Error sending error response: {e}")

    async def _handle_client_message(self, websocket, data):
        msg_type = data.get('type')
        message_id = data.get('message_id')

        if msg_type == 'auth':
            await self._handle_authentication(websocket, data)
            return

        if websocket not in self.authenticated_clients:
            await self._send_error(websocket, "Authentication required")
            return

        handlers = {
            'get_stats': lambda: self._send_stats(websocket),
            'get_access_points': lambda: self._send_access_points(websocket),
            'get_handshakes': lambda: self._send_handshakes(websocket),
            'get_face_status': lambda: self._send_face_status(websocket),
            'get_face_image': lambda: self._handle_face_image_request(websocket),
            'set_mode': lambda: self._handle_set_mode(websocket, data),
            'reboot': lambda: self._handle_reboot(websocket),
            'shutdown': lambda: self._handle_shutdown(websocket),
            'bored': lambda: self._handle_bored(websocket),
            'ping': lambda: self._handle_ping(websocket),
            'pong': lambda: self._handle_pong(websocket),
            'gps_data': lambda: self._handle_gps_data(websocket, data),
            'get_gps_data': lambda: self._send_gps_data(websocket),
        }

        try:
            handler = handlers.get(msg_type)
            if handler:
                await handler()
                if message_id and msg_type != 'gps_data':
                    await websocket.send(json.dumps({
                        "type": "acknowledgment",
                        "message_id": message_id,
                        "original_type": msg_type
                    }))
            else:
                await self._send_error(websocket, f"Unknown message type: {msg_type}")
        except Exception as e:
            logging.error(f"[PwnIOS] Error handling message type {msg_type}: {e}")
            await self._send_error(websocket, f"Error processing {msg_type}")

    async def _handle_authentication(self, websocket, data):
        configured_token = str(self.options.get("auth_token", ""))
        supplied_token = str(data.get("data", {}).get("token", ""))
        success = bool(configured_token) and hmac.compare_digest(
            supplied_token,
            configured_token
        )

        if success:
            self.authenticated_clients.add(websocket)
            await websocket.send(json.dumps({
                "type": "auth_result",
                "success": True
            }))
            await self._send_initial_data(websocket)
        else:
            logging.warning(
                "[PwnIOS] Authentication failed for client %s",
                websocket.remote_address
            )
            await websocket.send(json.dumps({
                "type": "auth_result",
                "success": False,
                "error": "Invalid authentication token"
            }))

    async def _handle_set_mode(self, websocket, data):
        mode = data.get('data', {}).get('mode', 'auto').lower()

        if self.agent:
            logging.info(f"[PwnIOS] Attempting to set agent mode to: {mode}")
            self.agent.mode = mode
            if mode == 'auto':
                logging.info(f"[PwnIOS] Agent mode set to AUTO. Pwnagotchi's main loop should react.")
            elif mode == 'manual':
                logging.info(f"[PwnIOS] Agent mode set to MANUAL. Pwnagotchi's main loop should react.")
        else:
            logging.warning("[PwnIOS] Agent not ready, cannot change mode.")
            await self._send_error(websocket, "Pwnagotchi agent not ready, cannot change mode.")

    async def _handle_reboot(self, websocket):
        if self.agent and hasattr(self.agent, 'reboot'):
            try:
                self.agent.reboot()
            except Exception as e:
                logging.error(f"[PwnIOS] Reboot error: {e}")
        else:
            try:
                import subprocess
                subprocess.run(['sudo', 'reboot'], check=True)
            except Exception as e:
                logging.error(f"[PwnIOS] System reboot error: {e}")

    async def _handle_shutdown(self, websocket):
        if self.agent and hasattr(self.agent, 'shutdown'):
            try:
                self.agent.shutdown()
            except Exception as e:
                logging.error(f"[PwnIOS] Shutdown error: {e}")
        else:
            try:
                import subprocess
                subprocess.run(['sudo', 'shutdown'], check=True)
            except Exception as e:
                logging.error(f"[PwnIOS] System shutdown error: {e}")

    async def _handle_bored(self, websocket):
        if self.agent and hasattr(self.agent, 'set_bored'):
            try:
                self.agent.set_bored()
            except Exception as e:
                logging.error(f"[PwnIOS] Bored state error: {e}")
        elif self.agent and hasattr(self.agent, '_state'):
            self.agent._state = 'bored'
        else:
            await websocket.send(json.dumps({
                "type": "response",
                "message": "Bored state not supported"
            }))

    async def _handle_ping(self, websocket):
        await websocket.send(json.dumps({
            "type": "pong",
            "timestamp": time.time()
        }))

    async def _handle_pong(self, websocket):
        logging.debug(f"[PwnIOS] Received pong from {websocket.remote_address}")

    async def _handle_face_image_request(self, websocket):
        try:
            logging.debug("[PwnIOS] get_face_image request received")

            face_name, status = self._get_current_face_and_status()
            logging.debug(f"[PwnIOS] Current face: {face_name}, status: {status}")

            image_data = self._get_face_image(face_name)

            response = {
                "type": "face_image",
                "data": image_data,
                "face": face_name,
                "face_name": face_name,
                "status": status,
                "timestamp": time.time()
            }

            await websocket.send(json.dumps(response))
            logging.debug("[PwnIOS] Face image sent successfully")

        except Exception as e:
            logging.error(f"[PwnIOS] get_face_image error: {e}")
            await websocket.send(json.dumps({
                "type": "face_image",
                "data": None,
                "error": str(e)
            }))

    async def _send_stats(self, websocket):
        try:
            stats = self._get_stats_from_agent()
            face, status = self._get_current_face_and_status()

            response = {
                "type": "stats",
                "data": stats,
                "face": face,
                "status": status,
                "timestamp": time.time()
            }

            await websocket.send(json.dumps(response))
            logging.debug(f"[PwnIOS] Stats sent to {websocket.remote_address}")

        except Exception as e:
            logging.error(f"[PwnIOS] Error sending stats: {e}")
            await self._send_error(websocket, f"Error getting stats: {str(e)}")

    def _get_stats_from_agent(self):
        stats = {
            'uptime': 0,
            'battery': self._get_battery_info(),
            'temperature': self._get_temperature(),
            'channel': 1,
            'mode': self._get_runtime_mode(),
            'status': 'ready',
            'handshakes': 0,
            'peers': 0,
            'accessPoints': 0,
            'lastHandshake': None,
            'lastPeer': None
        }

        gps_data = self._get_gps_data()
        if gps_data:
            stats['gps'] = {
                'enabled': True,
                'latitude': gps_data['latitude'],
                'longitude': gps_data['longitude'],
                'accuracy': gps_data['accuracy'],
                'last_update': self.last_gps_update.isoformat() if self.last_gps_update else None
            }
        else:
            stats['gps'] = {'enabled': False}

        if self.agent:
            try:
                # Get the raw uptime in seconds directly from pwnagotchi
                try:
                    stats['uptime'] = pwnagotchi.uptime()
                    logging.debug(f"[PwnIOS] Got uptime directly: {stats['uptime']} seconds")
                except ImportError:
                    # Fallback: try to get it from the agent's view (but this will be formatted)
                    if hasattr(self.agent, '_view') and self.agent._view:
                        view_uptime = self.agent._view.get('uptime')
                        if view_uptime:
                            # This will be in HH:MM:SS format, we need to convert back to seconds
                            stats['uptime'] = self._parse_uptime_string(view_uptime)
                            logging.debug(f"[PwnIOS] Got uptime from view: {view_uptime} -> {stats['uptime']} seconds")
                    elif hasattr(self.agent, 'view') and self.agent.view:
                        view = self.agent.view() if callable(self.agent.view) else self.agent.view
                        if isinstance(view, dict) and 'uptime' in view:
                            uptime_str = view['uptime']
                            stats['uptime'] = self._parse_uptime_string(uptime_str)
                            logging.debug(f"[PwnIOS] Got uptime from callable view: {uptime_str} -> {stats['uptime']} seconds")


                if hasattr(self.agent, 'session') and self.agent.session():
                    stats['channel'] = getattr(self.agent.session(), 'channel', 1)

                if hasattr(self.agent, 'peers'):
                    peers = self.agent.peers
                    stats['peers'] = len(peers) if peers else 0
                    if peers and len(peers) > 0:
                        last_peer = list(peers.values())[-1] if isinstance(peers, dict) else peers[-1]
                        stats['lastPeer'] = {
                            'peer': str(last_peer.get('peer', last_peer)) if isinstance(last_peer, dict) else str(last_peer),
                            'timestamp': last_peer.get('timestamp', '') if isinstance(last_peer, dict) else datetime.now().isoformat()
                        }
                elif hasattr(self.agent, '_peers'):
                    peers = self.agent._peers
                    stats['peers'] = len(peers) if peers else 0

                if hasattr(self.agent, 'access_points'):
                    aps = self.agent.access_points
                    stats['accessPoints'] = len(aps) if aps else 0
                elif hasattr(self.agent, '_access_points'):
                    aps = self.agent._access_points
                    stats['accessPoints'] = len(aps) if aps else 0

            except Exception as e:
                logging.error(f"[PwnIOS] Error getting agent stats: {e}")

        handshakes = self._normalized_handshake_history()
        stats['handshakes'] = len(handshakes)
        stats['lastHandshake'] = handshakes[-1] if handshakes else None

        return stats

    def _get_runtime_mode(self):
        """Return the mode selected by the Pwnagotchi launcher."""
        # MANU mode does not fire the ready plugin event. The upstream launcher
        # selects it with --manual, making the process arguments authoritative.
        arguments = {str(argument).strip().lower() for argument in sys.argv}
        if '--manual' in arguments:
            return 'MANU'

        # Retain compatibility with versions that expose mode on the callback
        # object or through a private mode property.
        if self.agent is not None:
            for attribute in ('mode', '_mode'):
                try:
                    raw_mode = getattr(self.agent, attribute, None)
                    if callable(raw_mode):
                        raw_mode = raw_mode()
                    normalized = str(raw_mode or '').strip().lower()
                    if normalized in ('manual', 'manu'):
                        return 'MANU'
                    if normalized in ('auto', 'automatic'):
                        return 'AUTO'
                except Exception:
                    continue

        return 'AUTO'

    async def _send_handshakes(self, websocket):
        await websocket.send(json.dumps({
            "type": "handshakes",
            "data": list(reversed(self._normalized_handshake_history()))
        }))

    def _normalized_handshake_history(self):
        """Merge agent and plugin-session handshakes into one stable payload."""
        merged = {}

        def add_handshake(value, fallback_filename=None):
            if isinstance(value, dict):
                # Jayofelony's agent._handshakes stores Bettercap events with
                # the capture filename inside event["data"]["file"]. The dict
                # key is "station -> AP", not a filename.
                event_data = value.get('data')
                if not isinstance(event_data, dict):
                    event_data = {}

                filename = (value.get('filename') or value.get('path') or
                            value.get('file') or event_data.get('file') or
                            event_data.get('filename'))
                if not filename and fallback_filename:
                    # Older agents may use filenames as their dict keys.
                    candidate = str(fallback_filename)
                    if os.path.splitext(candidate)[1].lower() in ('.pcap', '.pcapng'):
                        filename = candidate

                access_point = (value.get('access_point') or value.get('ap') or
                                value.get('bssid') or event_data.get('ap') or
                                event_data.get('bssid') or '')
                client_station = (value.get('client_station') or value.get('client') or
                                  value.get('station') or event_data.get('station') or '')
                timestamp = (value.get('timestamp') or value.get('time') or
                             event_data.get('timestamp') or '')
            elif isinstance(value, str):
                filename = value
                access_point = ''
                client_station = ''
                timestamp = ''
            else:
                filename = (getattr(value, 'filename', None) or
                            getattr(value, 'file', None) or fallback_filename)
                access_point = getattr(value, 'access_point', '')
                client_station = getattr(value, 'client_station', '')
                timestamp = getattr(value, 'timestamp', '')

            if not filename:
                return

            normalized = {
                'filename': str(filename),
                'access_point': str(access_point or ''),
                'client_station': str(client_station or ''),
                'timestamp': str(timestamp or '')
            }
            key = normalized['filename']
            merged.pop(key, None)
            merged[key] = normalized

        if self.agent:
            try:
                agent_handshakes = getattr(self.agent, 'handshakes', None)
                if agent_handshakes is None:
                    agent_handshakes = getattr(self.agent, '_handshakes', None)
                if callable(agent_handshakes):
                    agent_handshakes = agent_handshakes()

                if isinstance(agent_handshakes, dict):
                    for filename, handshake in agent_handshakes.items():
                        add_handshake(handshake, fallback_filename=filename)
                elif agent_handshakes:
                    for handshake in agent_handshakes:
                        add_handshake(handshake)
            except Exception as error:
                logging.warning(f"[PwnIOS] Unable to normalize agent handshakes: {error}")

        # Session entries are the newest and most complete representation.
        for handshake in self.session_handshakes:
            add_handshake(handshake)

        return list(merged.values())[-100:]

    async def _send_access_points(self, websocket):
        access_points = []

        if self.agent:
            try:
                if hasattr(self.agent, 'access_points'):
                    raw_aps = self.agent.access_points
                elif hasattr(self.agent, '_access_points'):
                    raw_aps = self.agent._access_points
                else:
                    raw_aps = []

                access_points = [self._serialize_access_point(ap) for ap in raw_aps]

            except Exception as e:
                logging.error(f"[PwnIOS] Error getting access points from agent: {e}")

        await websocket.send(json.dumps({
            "type": "access_points",
            "data": access_points
        }))

    @staticmethod
    def _serialize_access_point(access_point):
        if isinstance(access_point, dict):
            return {
                'bssid': access_point.get('bssid', ''),
                'hostname': access_point.get('hostname', access_point.get('ssid', '')),
                'channel': access_point.get('channel', 0),
                'rssi': access_point.get('rssi', 0),
                'encryption': access_point.get('encryption', ''),
                'vendor': access_point.get('vendor', '')
            }

        value = str(access_point)
        return {
            'bssid': value,
            'hostname': value,
            'channel': 0,
            'rssi': 0,
            'encryption': '',
            'vendor': ''
        }

    async def _send_face_status(self, websocket):
        face, status = self._get_current_face_and_status()
        await websocket.send(json.dumps({
            "type": "face_status",
            "data": {
                "face": face,
                "status": status,
                "timestamp": datetime.now().isoformat()
            }
        }))

    def _get_current_face_and_status(self):
        try:
            if self.agent:
                view = None
                if hasattr(self.agent, 'view') and self.agent.view:
                    view = self.agent.view() if callable(self.agent.view) else self.agent.view
                elif hasattr(self.agent, '_view') and self.agent._view:
                    view = self.agent._view() if callable(self.agent._view) else self.agent._view

                if view:
                    face_elem = view.get('face')
                    status_elem = view.get('status')
                else:
                    face_elem = None
                    status_elem = None

                if face_elem and status_elem:
                    face_val = face_elem if isinstance(face_elem, str) else getattr(face_elem, 'value', 'AWAKE')
                    status_val = status_elem if isinstance(status_elem, str) else getattr(status_elem, 'value', 'ready')

                    if isinstance(face_val, str) and face_val.lower().endswith('.png'):
                        face_name = os.path.basename(face_val).split('.')[0].strip().upper()
                    else:
                        face_name = face_val.strip()

                    status = status_val.strip()
                    return face_name, status

                if hasattr(self.agent, 'state'):
                    state = self.agent.state
                elif hasattr(self.agent, '_state'):
                    state = self.agent._state
                else:
                    state = 'ready'

                face_name = self._state_to_face_mapping().get(state.lower(), '(◕‿‿◕)')
                if state.lower() == 'awake':
                    face_name = '(◕‿‿◕)'

                return face_name, state

        except Exception as e:
            logging.error(f"[PwnIOS] Face/status error: {e}")

        return "(◕‿‿◕)", "ready"

    def _state_to_face_mapping(self):
        return {
            'bored': 'BORED', 'sad': 'SAD', 'angry': 'ANGRY', 'happy': 'HAPPY',
            'excited': 'EXCITED', 'lonely': 'LONELY', 'grateful': 'GRATEFUL',
            'motivated': 'MOTIVATED', 'demotivated': 'DEMOTIVATED', 'cool': 'COOL',
            'friend': 'FRIEND', 'broken': 'BROKEN', 'debug': 'DEBUG',
            'upload': 'UPLOAD', 'awake': 'AWAKE', 'sleep': 'SLEEP',
            'intense': 'INTENSE', 'smart': 'SMART', 'look_r': 'LOOK-R',
            'look_l': 'LOOK-L', 'look_r_happy': 'LOOK-R-HAPPY',
            'look_l_happy': 'LOOK-L-HAPPY'
        }

    def _parse_uptime_string(self, uptime_str):
        try:
            if isinstance(uptime_str, str) and ':' in uptime_str:
                parts = uptime_str.split(':')
                if len(parts) == 3:
                    hours, minutes, seconds = map(int, parts)
                    total_seconds = hours * 3600 + minutes * 60 + seconds
                    return total_seconds
                elif len(parts) == 2:
                    minutes, seconds = map(int, parts)
                    total_seconds = minutes * 60 + seconds
                    return total_seconds
        except (ValueError, AttributeError):
            pass
        return 0

    def _get_battery_info(self):
        """Get battery info with comprehensive error handling"""
        try:
            # Check if we have a functional PiSugar instance
            if self.pisugar is None:
                return "N/A (No PiSugar)"

            # Try to get battery level
            try:
                level = self.pisugar.battery_level

                # Check for None or invalid values
                if level is None:
                    return "N/A (Device not found)"

                # Try to get charging status
                try:
                    charging = self.pisugar.battery_charging
                    if charging is None:
                        charging = False
                except (AttributeError, TypeError):
                    charging = False

                status = "Charging" if charging else "Discharging"
                return f"{round(level, 1)}% ({status})"

            except AttributeError as ae:
                # Handle 'NoneType' object has no attribute errors
                if "'NoneType' object has no attribute" in str(ae):
                    return "N/A (Device offline)"
                else:
                    logging.warning(f"[PwnIOS] Battery attribute error: {ae}")
                    return "N/A (Attr error)"

        except Exception as e:
            logging.warning(f"[PwnIOS] Battery info error: {e}")
            return "N/A"

    def _get_temperature(self):
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                return f"{int(f.read().strip()) / 1000:.1f}°C"
        except Exception:
            pass
        return "N/A"

    def _get_face_image(self, face_name):
        logging.debug(f"[PwnIOS] Requesting face image for: '{face_name}'")
        if not face_name:
            current_face, _ = self._get_current_face_and_status()
            face_name = current_face

        if self.agent and hasattr(self.agent, 'get_face_image'):
            try:
                image_data = self.agent.get_face_image(face_name)
                if image_data:
                    return base64.b64encode(image_data).decode("utf-8")
            except Exception as e:
                logging.error(f"[PwnIOS] Agent face image error: {e}")

        if (not face_name or
            any(ord(char) > 127 for char in face_name) or
            len(face_name) > 20):
            current_face, _ = self._get_current_face_and_status()
            face_name = current_face

        face_variations = [face_name, face_name.upper(), face_name.lower(), face_name.capitalize()]
        base_paths = ["/custom-faces", "/etc/pwnagotchi/faces", "/home/pi/custom-faces"]

        for base_path in base_paths:
            for face_var in face_variations:
                full_path = f"{base_path}/{face_var}.png"
                if os.path.isfile(full_path):
                    try:
                        with open(full_path, "rb") as f:
                            encoded = base64.b64encode(f.read()).decode("utf-8")
                            logging.debug(f"[PwnIOS] Found face image: {full_path}")
                            return encoded
                    except Exception as e:
                        logging.error(f"[PwnIOS] Error reading face file {full_path}: {e}")

        return None

    @staticmethod
    def _gps_sidecar_path(filename):
        """Map a .pcap/.pcapng capture to its matching .gps.json sidecar."""
        capture_path = os.fspath(filename)
        stem, extension = os.path.splitext(capture_path)
        if extension.lower() in ('.pcap', '.pcapng'):
            return stem + '.gps.json'
        # Do not rewrite an unrelated extension or a directory containing
        # '.pcap' in its name.
        return capture_path + '.gps.json'

    def on_handshake(self, agent, filename, access_point, client_station):
        # Save GPS coordinates if available
        if self.gps_data and self.gps_enabled:
            logging.info("Location Data:")
            logging.info(f"Latitude: {self.gps_data['latitude']}")
            logging.info(f"Longitude: {self.gps_data['longitude']}")
            logging.info(f"Accuracy: {self.gps_data['accuracy']}")

            gps_filename = self._gps_sidecar_path(filename)
            # avoid 0.000... measurements
            if all([self.gps_data.get("latitude"), self.gps_data.get("longitude")]):
                logging.info(f"saving GPS to {gps_filename} ({self.gps_data})")
                try:
                    gps_export = {
                        "Latitude": self.gps_data['latitude'],
                        "Longitude": self.gps_data['longitude'],
                        "Accuracy": self.gps_data.get('accuracy', 0),
                        "Timestamp": self.gps_data.get('last_update', datetime.now().isoformat())
                    }
                    with open(gps_filename, "w+t") as fp:
                        json.dump(gps_export, fp)
                except Exception as e:
                    logging.error(f"[PwnIOS] Error saving GPS data: {e}")
            else:
                logging.info("[PwnIOS] not saving GPS. Couldn't find location.")
        else:
            logging.info("[PwnIOS] No GPS data available for handshake.")

        # Create handshake data for broadcasting
        handshake_data = {
            'filename': str(filename),
            'access_point': str(access_point),
            'client_station': str(client_station),
            'timestamp': datetime.now().isoformat()
        }

        self.session_handshakes.append(handshake_data)
        if len(self.session_handshakes) > 100:
            self.session_handshakes = self.session_handshakes[-100:]

        # Add GPS data to handshake if available
        if self.gps_data and self.gps_enabled:
            handshake_data['gps'] = {
                'latitude': self.gps_data['latitude'],
                'longitude': self.gps_data['longitude'],
                'accuracy': self.gps_data.get('accuracy', 0)
            }

        face, status = self._get_current_face_and_status()
        self.queue_message({
            "type": "handshake",
            "data": handshake_data,
            "face": face,
            "status": status
        })

    def on_peer_detected(self, agent, peer):
        peer_data = {
            'peer': str(peer),
            'timestamp': datetime.now().isoformat()
        }
        face, status = self._get_current_face_and_status()
        self.queue_message({
            "type": "peer_detected",
            "data": peer_data,
            "face": face,
            "status": status
        })

    def on_wifi_update(self, agent, access_points):
        formatted_aps = [
            self._serialize_access_point(access_point)
            for access_point in access_points[:10]
        ]

        self.queue_message({
            "type": "wifi_update",
            "data": {
                "count": len(access_points),
                "access_points": formatted_aps
            }
        })

    def on_channel_hop(self, agent, channel):
        self.queue_message({
            "type": "channel_hop",
            "data": {"channel": channel}
        })

    def on_bored(self, agent):
        self._broadcast_status_change('bored')

    def on_excited(self, agent):
        self._broadcast_status_change('excited')

    def on_lonely(self, agent):
        self._broadcast_status_change('lonely')

    def on_sad(self, agent):
        self._broadcast_status_change('sad')

    def _broadcast_status_change(self, status):
        """Helper method to broadcast status changes"""
        face, _ = self._get_current_face_and_status()
        self.queue_message({
            "type": "status_change",
            "data": {
                "status": status,
                "face": face,
                "timestamp": datetime.now().isoformat()
            },
            "face": face,
            "status": status
        })

    def on_ui_setup(self, ui):
        if self.options.get('display'):
            ui.add_element(
                'ios_clients',
                LabeledValue(
                    color=BLACK,
                    label='iOS:',
                    value='0',
                    position=(125, 78),
                    label_font=fonts.Small,
                    text_font=fonts.Small,
                    label_spacing=0,
                ))
        if self.options.get('display_gps', False):
            ui.add_element(
                'gps_long',
                LabeledValue(
                    color=BLACK,
                    label='GPS Long: ',
                    value='--',
                    position=(125, 87),
                    label_font=fonts.Small,
                    text_font=fonts.Small,
                    label_spacing=1,
                ))
            ui.add_element(
                'gps_lat',
                LabeledValue(
                    color=BLACK,
                    label='GPS Lat:  ',
                    value='--',
                    position=(125, 96),
                    label_font=fonts.Small,
                    text_font=fonts.Small,
                    label_spacing=1,
                ))

    def on_ui_update(self, ui):
        if self.options.get('display'):
            if len(self.connected_clients) != 0:
                ui.set('ios_clients', 'C')
            else:
                ui.set('ios_clients', '-')

        if self.options.get('display_gps', False):
            gps_data = self._get_gps_data()
            if gps_data and self.gps_enabled:
                gps_long = f"{gps_data['longitude']:.4f}"
                gps_lat = f"{gps_data['latitude']:.4f}"
            else:
                gps_long = "--"
                gps_lat = "--"
            ui.set('gps_long', gps_long)
            ui.set('gps_lat', gps_lat)

        self.ui_update_counter += 1
        if self.ui_update_counter % 5 == 0:
            self._check_face_status_changes()

    def _check_face_status_changes(self):
        try:
            current_face, current_status = self._get_current_face_and_status()

            if (current_face != self.last_face or current_status != self.last_status):
                logging.debug(f"[PwnIOS] UI Update - Face changed from '{self.last_face}' to '{current_face}', Status: '{current_status}'")
                self.last_face = current_face
                self.last_status = current_status

                self.queue_message({
                    "type": "ui_face_update",
                    "data": {
                        "face": current_face,
                        "status": current_status,
                        "timestamp": datetime.now().isoformat()
                    },
                    "face": current_face,
                    "status": current_status
                })

                if self.connected_clients:
                    image_data = self._get_face_image(current_face)
                    if image_data:
                        self.queue_message({
                            "type": "face_image",
                            "data": image_data,
                            "face": current_face,
                            "status": current_status,
                            "timestamp": time.time()
                        })

        except Exception as e:
            logging.error(f"[PwnIOS] Error in _check_face_status_changes: {e}")
