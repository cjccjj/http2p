# http2p

**Access HTTP resources from an HTTPS browser page via a direct WebRTC P2P tunnel — no proxy, no CA certs, no mixed-content warnings.**

## When to use this

You need **all three** of these:

1. **Browser-only client** — the consumer is a browser (HTTPS page blocked from fetching HTTP)
2. **Direct P2P required** — data must not route through a proxy (compliance, latency, cost)
3. **Legacy server can only do outbound** — behind NAT, no inbound ports, or you can't install certs

If any of these are missing, see [When not to use](#when-not-to-use).

## When not to use

Most situations have simpler solutions:

| If… | Just use… |
|---|---|
| No browser involved (curl, scripts, servers) | The HTTP URL directly — no mixed-content block exists |
| A reverse proxy is acceptable | nginx/caddy in front of the legacy server — 2 lines of config |
| You can put HTTPS on the legacy server | Let's Encrypt + nginx — CA certs today are free and automated |
| Your HTTP server has a public IP and inbound ports | Let's Encrypt + nginx again |
| You just need a one-off file download | `curl -O http://…` and scp/ftp the file |

**http2p is a niche tool for a specific constraint set.** If you're not hitting browser mixed-content + P2P + outbound-only simultaneously, use something simpler.

## Quick Start

### 1. Install dependencies

```bash
pip install aiortc aiohttp websockets
```

### 2. Open firewall

One UDP port must be reachable from the internet for WebRTC. Default is `40000`.

```bash
# Example: iptables
iptables -A INPUT -p udp --dport 40000 -j ACCEPT

# Or on cloud/VPS: open the port in your security group / firewall rules
```

### 3. Run the gateway

On the machine that can reach your HTTP server:

```bash
python gateway.py --public-ip 203.0.113.5 --legacy-base http://127.0.0.1:8080
```

| Flag | Default | Description |
|---|---|---|
| `--public-ip` | (required) | Your server's public IP |
| `--legacy-base` | `http://127.0.0.1:4000` | Base URL of the HTTP server |
| `--signaling` | `wss://http2p.dx512.com/ws` | Signaling server (or self-host) |
| `--webrtc-port` | `40000` | UDP port for the WebRTC tunnel |

### 4. Access from a browser

```
https://http2p.dx512.com/wr/203.0.113.5/path/to/file
```

Or visit `https://http2p.dx512.com/` for the interactive debug panel.

## Architecture

```
Browser ═══ WebRTC DTLS tunnel ═══ Gateway ─── HTTP ─── Legacy Server
   │         (encrypted, direct)       (local)
   │
   └── wss://signaling (SDP/ICE only, ~KB text)
```

| Component | Hosted by | Description |
|---|---|---|
| **Frontend** | Public service | HTTPS page + JS WebRTC client |
| **Signaling** | Public service | WebSocket relay for connection setup |
| **Gateway** | **You run this** | Bridges WebRTC ↔ your HTTP server |

Signaling sees only connection metadata (SDP/ICE). All data flows direct browser ↔ gateway.

## Limitations

- **Primarily for static file/resource fetches.** The built-in frontend is a download page. POST, auth headers, and REST API patterns are not implemented on the frontend side — the gateway can handle them, but a custom JS client would be needed.
- **One browser tab per gateway instance.** The gateway manages a single WebRTC session. Multiple tabs connecting to the same gateway will cause the first session to be replaced.
- **Browser-only.** Requires JavaScript and WebRTC. Curl, wget, and server-side HTTP clients cannot use this.
- **UDP port required.** The gateway machine must have one inbound UDP port open. Corporate firewalls that block UDP entirely will prevent WebRTC.

## Self-hosting the signaling service

If you don't want to use the free public service at `wss://http2p.dx512.com/ws`:

- **Cloudflare Workers:** Deploy `http2p_front/index.js` to your own Worker using `npx wrangler deploy`
- **Python (dev):** Run `python signaling.py` (listens on `127.0.0.1:9877`)

Then pass `--signaling wss://your-domain.com/ws` to the gateway.

## FAQ

**Q: Is this a proxy?** No. Data goes direct over an encrypted P2P DTLS tunnel. Signaling sees only SDP/ICE metadata.

**Q: Gateway behind NAT?** The gateway discovers its public IP via STUN. If STUN is blocked, specify `--public-ip`. Forward the UDP `--webrtc-port` on your firewall.

**Q: Multiple concurrent users?** Yes — each user connects to a *different* gateway instance. Different gateway IPs are independent. (Same gateway = single session.)

## Requirements

- Python 3.10+
- Outbound internet (gateway → signaling WebSocket)
- One inbound UDP port (internet → gateway WebRTC)
- The legacy HTTP server must be reachable from the gateway

## License

Custom non-commercial license. See [LICENSE](LICENSE).
