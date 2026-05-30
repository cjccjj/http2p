#!/usr/bin/env python3
"""WebRTC Gateway — bridges WebRTC Data Channel to a local legacy HTTP service.

Usage:
  python gateway.py --public-ip 1.2.3.4 --legacy-base http://127.0.0.1:4000
"""

import argparse
import asyncio
import json
import os
from aiortc import (
    RTCPeerConnection,
    RTCSessionDescription,
    RTCIceCandidate,
    RTCConfiguration,
)
import aiohttp
import websockets


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="WebRTC Data Bridge Gateway")
    p.add_argument(
        "--public-ip",
        default=os.getenv("PUBLIC_IP", ""),
        help="Public IP the browser will connect to (required)",
    )
    p.add_argument(
        "--signaling",
        default=os.getenv("SIGNALING_URL", "wss://http2p.dx512.com/ws"),
        help="Signaling server WebSocket URL",
    )
    p.add_argument(
        "--legacy-base",
        default=os.getenv("LEGACY_BASE", "http://127.0.0.1:4000"),
        help="Base URL of the legacy HTTP server",
    )
    p.add_argument(
        "--webrtc-port",
        type=int,
        default=int(os.getenv("WEBRTC_PORT", "40000")),
        help="UDP port for WebRTC ICE",
    )
    p.add_argument(
        "--read-size",
        type=int,
        default=int(os.getenv("READ_SIZE", "16384")),
        help="Chunk size for streaming",
    )
    args = p.parse_args()
    if not args.public_ip:
        p.error("--public-ip is required")
    return args


ARGS = parse_args()


class Gateway:
    def __init__(self) -> None:
        self.pc: RTCPeerConnection | None = None
        self.channel = None
        self.ws = None
        self._ice_queue: asyncio.Queue = asyncio.Queue()
        self._http_session: aiohttp.ClientSession | None = None
        self._ice_task: asyncio.Task | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._http_session is not None and not self._http_session.closed:
            return self._http_session
        if self._http_session is not None:
            await self._http_session.close()
        self._http_session = aiohttp.ClientSession()
        return self._http_session

    def setup_peer(self) -> None:
        self.pc = RTCPeerConnection(configuration=RTCConfiguration(iceServers=[]))

        @self.pc.on("icecandidate")
        def on_ice(candidate):
            if candidate:
                self._ice_queue.put_nowait(candidate)

        @self.pc.on("icegatheringstatechange")
        def on_gather():
            print(f"[gateway] ICE gather: {self.pc.iceGatheringState}")

        @self.pc.on("iceconnectionstatechange")
        def on_ice_state():
            print(f"[gateway] ICE connection: {self.pc.iceConnectionState}")

        @self.pc.on("datachannel")
        def on_datachannel(channel):
            self.channel = channel
            print(f"[gateway] data channel received (label={channel.label})")

            @channel.on("open")
            def on_open():
                print("[gateway] data channel open")

            @channel.on("message")
            def on_message(msg):
                if isinstance(msg, str) and msg.startswith("SEND "):
                    path = msg[5:].strip()
                    task = asyncio.create_task(self._handle_request(channel, path))
                    task.add_done_callback(
                        lambda t: t.exception() and print(f"[gateway] task error: {t.exception()}")
                    )

    async def _handle_request(self, channel, path: str) -> None:
        url = f"{ARGS.legacy_base}{path}"
        print(f"[gateway] HTTP GET {url}")

        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                channel.send(f"STATUS {resp.status}")
                if resp.status != 200:
                    channel.send(f"ERROR HTTP {resp.status}")
                    return

                ct = resp.headers.get("Content-Type", "application/octet-stream")
                cl = resp.headers.get("Content-Length", "0")
                channel.send(f"TYPE {ct}")
                channel.send(f"SIZE {cl}")

                sent = 0
                while True:
                    chunk = await resp.content.read(ARGS.read_size)
                    if not chunk:
                        break
                    channel.send(chunk)
                    sent += len(chunk)

                channel.send("DONE")
                print(f"[gateway] done: {sent} bytes ({sent / 1048576:.1f} MB) type={ct}")

        except aiohttp.ClientError as e:
            channel.send(f"ERROR {e}")
            print(f"[gateway] HTTP error: {e}")
        except Exception as e:
            channel.send(f"ERROR {e}")
            print(f"[gateway] error: {e}")

    def _inject_public_candidate(self, sdp: str) -> str:
        candidate_line = (
            f"a=candidate:pub1 1 udp 1686052607 "
            f"{ARGS.public_ip} {ARGS.webrtc_port} typ srflx raddr {ARGS.public_ip} rport {ARGS.webrtc_port}"
        )
        lines = sdp.rstrip().split("\r\n")
        for i, line in enumerate(lines):
            if line.startswith("a=candidate:") or line.startswith("a=end-of-candidates"):
                lines.insert(i, candidate_line)
                break
        else:
            lines.append(candidate_line)
        return "\r\n".join(lines) + "\r\n"

    async def send_ice_loop(self) -> None:
        try:
            while True:
                candidate = await self._ice_queue.get()
                await self.ws.send(
                    json.dumps(
                        {
                            "type": "ice",
                            "to": "browser",
                            "candidate": candidate.candidate,
                            "sdpMid": candidate.sdpMid,
                            "sdpMLineIndex": candidate.sdpMLineIndex,
                        }
                    )
                )
                print(f"[gateway] sent ICE: {candidate.type} {candidate.ip}:{candidate.port}")
        except asyncio.CancelledError:
            raise

    async def run(self) -> None:
        while True:
            try:
                await self._connect()
            except (websockets.ConnectionClosed, OSError) as e:
                print(f"[gateway] signaling lost: {e}, reconnecting in 3s...")
                await asyncio.sleep(3)

    async def _connect(self) -> None:
        async with websockets.connect(ARGS.signaling, ping_interval=20, ping_timeout=10) as ws:
            self.ws = ws
            await ws.send(
                json.dumps({"type": "register", "role": "gateway", "id": ARGS.public_ip})
            )
            print(f"[gateway] registered as gateway:{ARGS.public_ip} at {ARGS.signaling} (heartbeat: 20s/10s)")

            async for raw in ws:
                msg = json.loads(raw)
                t = msg.get("type")

                if t == "offer":
                    print("[gateway] offer received")
                    if self.pc:
                        await self.pc.close()
                    if self._ice_task:
                        self._ice_task.cancel()
                    self.setup_peer()
                    self._ice_task = asyncio.create_task(self.send_ice_loop())

                    await self.pc.setRemoteDescription(
                        RTCSessionDescription(sdp=msg["sdp"], type="offer")
                    )
                    answer = await self.pc.createAnswer()
                    await self.pc.setLocalDescription(answer)
                    sdp = self.pc.localDescription.sdp
                    sdp = self._inject_public_candidate(sdp)
                    print(f"[gateway] answer SDP:\n{sdp[:2000]}")
                    await ws.send(
                        json.dumps(
                            {
                                "type": "answer",
                                "to": "browser",
                                "sdp": sdp,
                            }
                        )
                    )
                    print("[gateway] answer sent")

                elif t == "ice":
                    if self.pc:
                        candidate = RTCIceCandidate.from_sdp(msg["candidate"])
                        candidate.sdpMid = msg.get("sdpMid")
                        candidate.sdpMLineIndex = msg.get("sdpMLineIndex")
                        await self.pc.addIceCandidate(candidate)

                elif t == "pong":
                    pass

                else:
                    print(f"[gateway] unknown: {t}")


if __name__ == "__main__":
    _original_cde = asyncio.BaseEventLoop.create_datagram_endpoint

    async def _patched_cde(self, protocol_factory, local_addr=None, **kwargs):
        if local_addr and isinstance(local_addr, tuple) and len(local_addr) >= 2 and local_addr[1] == 0:
            local_addr = (local_addr[0], ARGS.webrtc_port)
        return await _original_cde(self, protocol_factory, local_addr=local_addr, **kwargs)

    asyncio.BaseEventLoop.create_datagram_endpoint = _patched_cde

    gateway = Gateway()
    try:
        asyncio.run(gateway.run())
    except KeyboardInterrupt:
        print("\n[gateway] shutting down")
    finally:
        asyncio.BaseEventLoop.create_datagram_endpoint = _original_cde
