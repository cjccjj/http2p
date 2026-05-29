# http2p

**Access any HTTP resource from an HTTPS page — without modifying the resource, without CA certificates, and without routing data through a proxy.**

## The Problem

Modern browsers block HTTPS pages from fetching HTTP content (mixed-content policy). You have an HTTP server — a legacy dashboard, an IoT device, an internal API — and you need to access it from a browser.

## Why Not Just Use a Reverse Proxy?

A reverse proxy requires the proxy server to have network access to both the client and the legacy server. In many real-world situations this isn't possible:

- The legacy server is behind NAT with no inbound ports
- You don't control the HTTPS server or can't install CA certs
- The legacy server is on a restricted network (outbound only)
- Data must not route through a third-party server (compliance)

**http2p** solves this differently: a lightweight gateway runs near your legacy HTTP server. It establishes an outbound connection to a public signaling service. Your browser connects to the same signaling service, negotiates a direct P2P encrypted tunnel, and fetches the HTTP resource directly. No data routes through any proxy.

```
Browser ═══ WebRTC DTLS tunnel ═══ Gateway ─── HTTP ─── Legacy Server
   │              (encrypted, direct)         (localhost)
   │
   └── wss://http2p.dx512.com/ws (signaling only, ~KB text)
```

## Quick Start

### 1. Install & run the gateway

On the machine that can reach your HTTP server (same machine or same network):

```bash
pip install aiortc aiohttp websockets
python gateway.py --public-ip 203.0.113.5 --legacy-base http://127.0.0.1:8080
```

- `--public-ip`: The public IP browsers can reach (required)
- `--legacy-base`: Base URL of your HTTP server (default: http://127.0.0.1:4000)
- `--signaling`: Signaling server URL (default: our free public service)

One UDP port must be open to the internet (default: 40000, configurable with `--webrtc-port`).

### 2. Access from a browser

Open:

```
https://http2p.dx512.com/wr/203.0.113.5/path/to/file
```

That's it. The browser connects to your gateway via WebRTC, fetches the file, and downloads it — no mixed-content warnings, no cert errors.

### Manual mode (debug/development)

Visit `https://http2p.dx512.com/` for an interactive debug panel where you can enter any HTTP URL to fetch.

## Architecture

| Component | Hosted by | Description |
|---|---|---|
| **Frontend** | Public service (free) | HTTPS page + JavaScript WebRTC client |
| **Signaling** | Public service (free) | WebSocket relay for connection setup |
| **Gateway** | **You run this** | Bridges WebRTC to your HTTP server |

The public service only handles signaling (a few KB of SDP/ICE text). All actual data transfers go through the direct P2P tunnel between your browser and your gateway. The signaling service never sees your data.

## Use Cases

- **Legacy dashboards**: Old monitoring/management panels on HTTP-only internal servers
- **IoT devices**: Cameras, sensors, relays with plain HTTP APIs
- **Build artifacts**: Internal Jenkins/Nexus artifacts → secure browser download
- **Ad-hoc sharing**: `python gateway.py` on your laptop → share a URL with a colleague
- **Staging access**: Dev servers on HTTP → temporary secure access without certs
- **Configuration**: JSON config from an internal server → fetched securely by browser JS
- **Kubernetes NodePort**: HTTP services → browser access without mixed-content block

## Configuration Reference

```
python gateway.py --help
```

| Flag | Default | Description |
|---|---|---|
| `--public-ip` | (required) | Public IP browsers connect to |
| `--legacy-base` | `http://127.0.0.1:4000` | Base URL of your HTTP server |
| `--signaling` | `wss://http2p.dx512.com/ws` | Signaling server URL |
| `--webrtc-port` | `40000` | UDP port for WebRTC ICE |

## Requirements

- Python 3.10+
- The gateway machine needs **outbound internet** (WebSocket to signaling)
- One **inbound UDP port** accessible from the internet (for the WebRTC tunnel)
- The HTTP server you want to expose must be reachable from the gateway (usually localhost or same network)

## FAQ

**Q: Is this a proxy?** No. The data goes directly from the gateway to your browser via an encrypted P2P tunnel. The signaling server only sees connection metadata (SDP/ICE, ~KB).

**Q: What if my gateway is behind NAT?** The gateway uses STUN to discover its public IP. If STUN is blocked, specify `--public-ip` with your known public IP. The firewall must forward the `--webrtc-port` UDP port.

**Q: Does it work with curl/wget?** No. The browser must run JavaScript to establish the WebRTC connection. This is a browser-based tool.

**Q: Can I use this commercially?** This software is free for non-commercial use. See LICENSE.

## License

This project is licensed under a custom non-commercial license. See [LICENSE](LICENSE) for details.
