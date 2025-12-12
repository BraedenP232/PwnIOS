import json
import logging
import asyncio
import websockets
import threading
import base64
import os
import pwnagotchi
from datetime import datetime
import time
import importlib.util
import sys

import pwnagotchi.plugins as plugins
import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.components import LabeledValue
from pwnagotchi.ui.view import BLACK

# Configuration values
# /etc/pwnagotchi/config.toml

# main.custom_plugin_repos = [
#     "https://github.com/BraedenP232/pwnios/archive/main.zip",
# ]

### REQUIRED ###
# main.plugins.pwnios.enabled = true
# main.plugins.pwnios.port = 8082
# main.plugins.pwnios.display = true
# main.plugins.pwnios.display_gps = true

### OPTIONAL ###
## PiSugar ##
# main.plugins.pwnios.pisugar = true  # Enable PiSugar battery monitoring
## GPS ##
# main.plugins.pwnios.save_gps_log = false  # Enable GPS logging to file
# main.plugins.pwnios.gps_log_path = /path/to/gps.log # /tmp/pwnagotchi_gps.log is set by default


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

PISUGAR_AVAILABLE = False


class PwnIOS(plugins.Plugin):
    __author__ = "PellTech"
    __version__ = "1.0.3.1"
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
        self.client_health = {}
        self.loop = None
        self.message_queue = None
        self.server_thread = None
        
        self.broadcaster_task = None
        self.heartbeat_task = None
        
        self.pisugar = None
        self.pisugar_error = None
        
        self.last_face = None
        self.last_status = None
        self.ui_update_counter = 0

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
                PISUGARX_PATH = "/home/pi/.pwn/lib/python3.11/site-packages/pwnagotchi/plugins/default/pisugarx.py"
                spec = importlib.util.spec_from_file_location("pisugarx", PISUGARX_PATH)
                mod = importlib.util.module_from_spec(spec)
                sys.modules["pisugarx"] = mod
                spec.loader.exec_module(mod)
                pisugarx = mod
                logging.info("[PwnIOS] PiSugarX loaded from fallback path")
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
        
        # Log PiSugar status
        if self.pisugar_error:
            logging.warning(f"[PwnIOS] Battery monitoring unavailable: {self.pisugar_error}")
        elif PISUGAR_AVAILABLE:
            logging.info("[PwnIOS] Battery monitoring available")
        
        self.server_thread = threading.Thread(target=self._start_websocket_server, daemon=True)
        self.server_thread.start()

    def on_ready(self, agent):
        self.agent = agent
        logging.info("[PwnIOS] Agent ready")

    def on_unload(self, ui):
        logging.info("[PwnIOS] Plugin unloading...")
        self.running = False
        self._cleanup_resources()
        logging.info("[PwnIOS] Plugin unloaded")
        
    async def _handle_gps_data(self, websocket, full_message_data):
        try:
            gps_payload = full_message_data.get('data', {})

            if gps_payload.get('latitude') is None or gps_payload.get('longitude') is None:
                logging.warning("[PwnIOS] Received GPS data with missing latitude or longitude.")
                await self._send_error(websocket, "GPS data error: latitude or longitude missing.")
                return

            self.gps_data = {
                'enabled': True,
                'latitude': gps_payload.get('latitude'),
                'longitude': gps_payload.get('longitude'),
                'accuracy': gps_payload.get('accuracy'),
                'last_update': datetime.now().isoformat()
            }
            self.last_gps_update = datetime.now()
            self.gps_enabled = True

            logging.info(f"[PwnIOS] GPS data received: {self.gps_data['latitude']:.6f}, {self.gps_data['longitude']:.6f}")

            if self.options.get('save_gps_log', False):
                await self._save_gps_log(self.gps_data)

            await self._broadcast_to_clients({
                "type": "gps_update",
                "data": self.gps_data
            })

        except Exception as e:
            logging.error(f"[PwnIOS] GPS data error: {e}")
            await self._send_error(websocket, f"GPS data error: {str(e)}")
            
    def _get_gps_data(self):
        if not self.gps_data or not self.gps_enabled:
            return None

        if self.last_gps_update:
            time_diff = (datetime.now() - self.last_gps_update).total_seconds()
            if time_diff > 300:  # 5 minutes
                self.gps_enabled = False
                return None

        return self.gps_data
    
    async def _save_gps_log(self, gps_data):
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
        if self.websocket_server:
            try: self.websocket_server.close()
            except: pass
            
        for task in [self.broadcaster_task, self.heartbeat_task]:
            if task:
                try: task.cancel()
                except: pass
                
        for client in self.connected_clients.copy():
            try:
                # Only use run_coroutine_threadsafe when we have a valid running loop
                if self.loop is not None and getattr(self.loop, "is_running", lambda: False)():
                    asyncio.run_coroutine_threadsafe(client.close(), self.loop)
                else:
                    # No event loop available to schedule on: try to close synchronously
                    try:
                        asyncio.run(client.close())
                    except Exception:
                        # If asyncio.run fails (e.g. already in an event loop), try best-effort close
                        try:
                            close_ret = client.close()
                            # close_ret may be a coroutine; if so, ignore as last resort
                        except Exception:
                            pass
            except Exception:
                pass
            
        self.connected_clients.clear()
        self.client_health.clear()

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
            self.broadcaster_task = asyncio.create_task(self._message_broadcaster())
            self.heartbeat_task = asyncio.create_task(self._heartbeat_checker())
            
            self.websocket_server = await websockets.serve(
                self._handle_client, "0.0.0.0", 8082,
                ping_interval=30, ping_timeout=20, close_timeout=10,
                max_size=2**20, compression=None, max_queue=32
            )
            
            logging.info("[PwnIOS] WebSocket server started on port 8082")
            await self.websocket_server.wait_closed()
            
        except Exception as e:
            logging.error(f"[PwnIOS] Server error: {e}")
        finally:
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
        logging.info(f"[PwnIOS] iOS client connected: {client_addr}")
        
        try:
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
            self.client_health.pop(websocket, None)
            logging.info(f"[PwnIOS] Client disconnected: {client_addr}")

    async def _send_initial_data(self, websocket):
        logging.info("[PwnIOS] Sending initial data")
        await self._send_stats(websocket)
        await self._send_access_points(websocket)
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
            *[send_to_client(client) for client in list(self.connected_clients)], 
            return_exceptions=True
        )
        
        for client in dead_clients:
            self.connected_clients.discard(client)
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
        
        handlers = {
            'get_stats': lambda: self._send_stats(websocket),
            'get_access_points': lambda: self._send_access_points(websocket),
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
                if message_id:
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
            logging.info("[PwnIOS] get_face_image request received")
            
            face_name, status = self._get_current_face_and_status()
            logging.info(f"[PwnIOS] Current face: {face_name}, status: {status}")
            
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
            logging.info("[PwnIOS] Face image sent successfully")
            
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
            'mode': 'AUTO',
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

                if hasattr(self.agent, 'handshakes'):
                    handshakes = self.agent.handshakes
                    stats['handshakes'] = len(handshakes) if handshakes else 0
                    if handshakes and len(handshakes) > 0:
                        last = list(handshakes.values())[-1] if isinstance(handshakes, dict) else handshakes[-1]
                        stats['lastHandshake'] = {
                            'filename': last.get('filename', ''),
                            'access_point': last.get('access_point', ''),
                            'client_station': last.get('client_station', ''),
                            'timestamp': last.get('timestamp', '')
                        }
                elif hasattr(self.agent, '_handshakes'):
                    handshakes = self.agent._handshakes
                    stats['handshakes'] = len(handshakes) if handshakes else 0

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

                if hasattr(self.agent, 'mode'):
                    if self.agent.mode == 'manual':
                        stats['mode'] = "MANUAL"
                    else:
                        stats['mode'] = "AUTO"
                elif hasattr(self.agent, '_mode'):
                    stats['mode'] = str(self.agent._mode).upper()

            except Exception as e:
                logging.error(f"[PwnIOS] Error getting agent stats: {e}")

        return stats

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

                for ap in raw_aps:
                    if isinstance(ap, dict):
                        access_points.append({
                            'bssid': ap.get('bssid', ''),
                            'hostname': ap.get('hostname', ap.get('ssid', '')),
                            'channel': ap.get('channel', 0),
                            'rssi': ap.get('rssi', 0),
                            'encryption': ap.get('encryption', ''),
                            'vendor': ap.get('vendor', '')
                        })
                    else:
                        access_points.append({
                            'bssid': str(ap),
                            'hostname': str(ap),
                            'channel': 0,
                            'rssi': 0,
                            'encryption': '',
                            'vendor': ''
                        })

            except Exception as e:
                logging.error(f"[PwnIOS] Error getting access points from agent: {e}")

        await websocket.send(json.dumps({
            "type": "access_points", 
            "data": access_points
        }))

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
                    if self.pisugar_error:
                        return f"N/A ({self.pisugar_error[:30]}...)"
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
                    if "No PiSugar device was found" in str(self.pisugar_error or ""):
                        return "N/A (Update pisugarx.py)"
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
        logging.info(f"[PwnIOS] Requesting face image for: '{face_name}'")
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
                            logging.info(f"[PwnIOS] Found face image: {full_path}")
                            return encoded
                    except Exception as e:
                        logging.error(f"[PwnIOS] Error reading face file {full_path}: {e}")

        return None
    
    def on_handshake(self, agent, filename, access_point, client_station):
        # Save GPS coordinates if available
        if self.gps_data and self.gps_enabled:
            logging.info("Location Data:")
            logging.info(f"Latitude: {self.gps_data['latitude']}")
            logging.info(f"Longitude: {self.gps_data['longitude']}")
            logging.info(f"Accuracy: {self.gps_data['accuracy']}")
            
            gps_filename = filename.replace(".pcap", ".gps.json")
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
        formatted_aps = []
        for ap in access_points[:10]:
            if isinstance(ap, dict):
                formatted_aps.append({
                    'bssid': ap.get('bssid', ''),
                    'hostname': ap.get('hostname', ap.get('ssid', '')),
                    'channel': ap.get('channel', 0),
                    'rssi': ap.get('rssi', 0),
                    'encryption': ap.get('encryption', ''),
                    'vendor': ap.get('vendor', '')
                })
            else:
                formatted_aps.append({
                    'bssid': str(ap),
                    'hostname': str(ap),
                    'channel': 0,
                    'rssi': 0,
                    'encryption': '',
                    'vendor': ''
                })
        
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
        face, current_status = self._get_current_face_and_status()
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
                logging.info(f"[PwnIOS] UI Update - Face changed from '{self.last_face}' to '{current_face}', Status: '{current_status}'")
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
