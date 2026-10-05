# ==================== STANDARD IMPORTS ====================
import sys
import asyncio
import httpx
import random
import json
import socket
import struct
import time
import os
import uuid
import itertools
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
from urllib.parse import urlparse

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ==================== ORIGINAL IMPORTS ====================
from google_play_scraper import app as play_scraper
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from protobuf_decoder.protobuf_decoder import Parser
from message_ids import MESSAGE_ID_TO_NAME
import thunderFF_pb2

# ==================== WEB DASHBOARD ====================
from dashboard_server import bot_state, start_web_dashboard

# ==================== CONFIGURATION ====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_HOST = "0.0.0.0"
WEB_PORT = 20335
ACCOUNTS_FILE = os.path.join(BASE_DIR, "accounts.json")
TOKEN_CACHE_FILE = os.path.join(BASE_DIR, "token_cache.json")
DEVICES_FILE = os.path.join(BASE_DIR, "devices.json")  # 🔥 Persistent device storage
TOKEN_CACHE_TTL = 1200

# Runtime login/version fallbacks. Environment variables let you update these
# without editing code when the game bumps version or endpoint hosts.
DEFAULT_RELEASE_VERSION = os.getenv("FF_RELEASE_VERSION", "OB55")
DEFAULT_CLIENT_VERSION = os.getenv("FF_CLIENT_VERSION", "1.132.3")
DEFAULT_APP_VERSION = os.getenv("FF_APP_VERSION", DEFAULT_CLIENT_VERSION)
DEFAULT_MAJOR_LOGIN_URL = os.getenv("FF_MAJOR_LOGIN_URL", "https://loginbp.ggblueshark.com/")
DEFAULT_MAJOR_LOGIN_URLS = os.getenv(
    "FF_MAJOR_LOGIN_URLS",
    "https://loginbp.ggblueshark.com/,https://loginbp.ppmainecoonghj.com/"
)
DEFAULT_TOKEN_GRANT_URLS = os.getenv(
    "FF_TOKEN_GRANT_URLS",
    "https://ffmconnect.live.gop.garenanow.com/oauth/guest/token/grant,"
    "https://100067.connect.garena.com/oauth/guest/token/grant"
)
DEFAULT_TOKEN_INSPECT_URLS = os.getenv(
    "FF_TOKEN_INSPECT_URLS",
    "https://ffmconnect.live.gop.garenanow.com/oauth/token/inspect,"
    "https://100067.connect.garena.com/oauth/token/inspect"
)
DEFAULT_CLIENT_URLS = os.getenv(
    "FF_CLIENT_URLS",
    "https://clientbp.ppmainecoonghj.com/,https://clientbp.ggpolarbear.com/,"
    "https://client.ind.freefiremobile.com/,https://clientbp.common.ggbluefox.com/"
)
FF_PROXY = os.getenv("FF_PROXY", "").strip() or None
# StartMatch uses a fixed TCP command prefix in the captured Lone Wolf packet.
# Override only if you have a fresh capture proving a different prefix.
STARTMATCH_PACKET_PREFIX = os.getenv("FF_STARTMATCH_PREFIX", "031400").strip() or "031400"
MATCHMAKING_REGION = os.getenv("FF_MATCHMAKING_REGION", "EUROPE").strip() or "EUROPE"

# 🔥 Match control
START_MATCH_INTERVAL = 3.0
NEW_MATCH_DELAY = 3.0   
MAX_MATCH_DURATION = 700
MATCH_IDLE_TIMEOUT = 8.0
PRIORITY_REGIONS = ["BD","IND", "SG", "TH", "PH", "VN", "MY", "ID", "HK", "TW"]

# 🔥 Cache invalidation thresholds
MAX_CONSECUTIVE_PARSE_FAILURES = 5.0     
NON_MATCH_RECONNECT_DELAY = 1.0       

FALLBACK_UID = ""
FALLBACK_PASSWORD = ""


# ==================== ULTRA SAFE PERSISTENT DEVICE RANDOMIZER ====================
def get_device_for_account(account_identifier: str) -> dict:
    """
    Ensures 1 ID = 1 Specific Device.
    It loads saved devices from devices.json. If the account isn't found, 
    it generates a new profile and saves it permanently for this ID.
    """
    devices = {}
    if os.path.exists(DEVICES_FILE):
        try:
            with open(DEVICES_FILE, "r", encoding="utf-8") as f:
                devices = json.load(f)
        except Exception:
            pass
            
    acc_key = str(account_identifier)
    
    if acc_key in devices:
        return devices[acc_key]
        
    # Generate new device profile for this account
    device_list = [
        ("Samsung", "SM-G998B", "Adreno (TM) 660", "Android OS 12 / API-31"),
        ("Xiaomi", "2201122G", "Adreno (TM) 730", "Android OS 13 / API-33"),
        ("Realme", "RMX3700", "Mali-G710", "Android OS 14 / API-34"),
        ("OnePlus", "CPH2451", "Adreno (TM) 740", "Android OS 13 / API-33"),
        ("OPPO", "CPH2611", "Adreno (TM) 720", "Android OS 14 / API-34"),
        ("Vivo", "V2203", "Mali-G710", "Android OS 12 / API-31"),
        ("Poco", "M2102J20SG", "Adreno (TM) 660", "Android OS 13 / API-33"),
    ]
    brand, model, gpu, os_ver = random.choice(device_list)
    
    new_device = {
        "unique_device_id": f"Google|{str(uuid.uuid4())}",
        "brand": brand,
        "model": model,
        "gpu_renderer": gpu,
        "system_software": os_ver,
        "screen_width": random.choice([1080, 1440, 720, 1280]),
        "screen_height": random.choice([2400, 3200, 1600, 2400]),
        "screen_dpi": str(random.randint(300, 420)),
        "memory": random.randint(2800, 6500),
        "processor_details": f"ARM64 FP ASIMD AES VMH | {random.randint(2200, 3200)} | {random.randint(6, 12)}",
        "client_ip": f"{random.randint(103, 223)}.{random.randint(10, 250)}.{random.randint(10, 250)}.{random.randint(10, 250)}"
    }
    
    devices[acc_key] = new_device
    
    try:
        with open(DEVICES_FILE, "w", encoding="utf-8") as f:
            json.dump(devices, f, indent=4)
    except Exception as e:
        print_error(f"Failed to save device mapping: {e}")
        
    return new_device


# ==================== CLOUDFLARE DNS RESOLVER & SOCKET OPTIMIZERS ====================
CLOUDFLARE_PRIMARY_DNS = "1.1.1.1"
CLOUDFLARE_SECONDARY_DNS = "1.0.0.1"
_DNS_CACHE: Dict[str, Tuple[str, float]] = {}
_DNS_CACHE_TTL = 300.0  # 5 minutes DNS cache

async def resolve_host_cloudflare(hostname: str) -> str:
    if not hostname:
        return hostname

    parts = hostname.split('.')
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return hostname

    now = time.time()
    if hostname in _DNS_CACHE:
        ip, exp = _DNS_CACHE[hostname]
        if now < exp:
            return ip

    def _query_cloudflare(server_ip: str) -> Optional[str]:
        s = None
        try:
            tx_id = random.randint(1000, 65535)
            header = struct.pack(">HHHHHH", tx_id, 0x0100, 1, 0, 0, 0)
            qname = b"".join(bytes([len(part)]) + part.encode('ascii') for part in hostname.split('.')) + b"\x00"
            query_pkt = header + qname + struct.pack(">HH", 1, 1)

            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1.2)
            s.sendto(query_pkt, (server_ip, 53))
            resp, _ = s.recvfrom(1024)

            if len(resp) >= 12:
                ancount = struct.unpack(">H", resp[6:8])[0]
                if ancount > 0:
                    offset = 12 + len(qname) + 4
                    for _ in range(ancount):
                        if offset >= len(resp):
                            break
                        if (resp[offset] & 0xC0) == 0xC0:
                            offset += 2
                        else:
                            while offset < len(resp) and resp[offset] != 0:
                                offset += 1 + resp[offset]
                            offset += 1
                        if offset + 10 > len(resp):
                            break
                        rtype, rclass, ttl, rdlen = struct.unpack(">HHIH", resp[offset:offset+10])
                        offset += 10
                        if rtype == 1 and rdlen == 4 and offset + 4 <= len(resp):
                            return socket.inet_ntoa(resp[offset:offset+4])
                        offset += rdlen
        except Exception:
            pass
        finally:
            if s:
                try:
                    s.close()
                except Exception:
                    pass
        return None

    loop = asyncio.get_running_loop()
    ip = await loop.run_in_executor(None, _query_cloudflare, CLOUDFLARE_PRIMARY_DNS)
    if not ip:
        ip = await loop.run_in_executor(None, _query_cloudflare, CLOUDFLARE_SECONDARY_DNS)
    if not ip:
        try:
            ip_info = await loop.getaddrinfo(hostname, None, family=socket.AF_INET)
            if ip_info:
                ip = ip_info[0][4][0]
        except Exception:
            ip = hostname

    if ip:
        _DNS_CACHE[hostname] = (ip, now + _DNS_CACHE_TTL)
    return ip or hostname


def optimize_tcp_socket(sock: socket.socket):
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
    except Exception:
        pass


def optimize_udp_socket(sock: socket.socket):
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 131072)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 131072)
        if hasattr(socket, 'SIO_UDP_CONNRESET') and os.name == 'nt':
            try:
                sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            except Exception:
                pass
    except Exception:
        pass


# ==================== NETWORK & CRYPTO ====================
client = httpx.AsyncClient(
    verify=False,
    timeout=15.0,
    proxy=FF_PROXY,
    trust_env=True,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=50)
)

headers = {
    'User-Agent': 'UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)',
    'Connection': 'Keep-Alive',
    'Accept-Encoding': 'gzip',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Expect': '100-continue',
    'X-Unity-Version': '2018.4.12f1',
    'X-GA-SV': '1789535859',
    'X-GA': 'v1 1',
    'ReleaseVersion': DEFAULT_RELEASE_VERSION
}

AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV = b'6oyZDr22E3ychjM%'

CRC7_TABLE = bytes([
    0, 9, 18, 27, 36, 45, 54, 63, 72, 65, 90, 83, 108, 101, 126, 119,
    25, 16, 11, 2, 61, 52, 47, 38, 81, 88, 67, 74, 117, 124, 103, 110,
    50, 59, 32, 41, 22, 31, 4, 13, 122, 115, 104, 97, 94, 87, 76, 69,
    43, 34, 57, 48, 15, 6, 29, 20, 99, 106, 113, 120, 71, 78, 85, 92,
    100, 109, 118, 127, 64, 73, 82, 91, 44, 37, 62, 55, 8, 1, 26, 19,
    125, 116, 111, 102, 89, 80, 75, 66, 53, 60, 39, 46, 17, 24, 3, 10,
    86, 95, 68, 77, 114, 123, 96, 105, 30, 23, 12, 5, 58, 51, 40, 33,
    79, 70, 93, 84, 107, 98, 121, 112, 7, 14, 21, 28, 35, 42, 49, 56,
    65, 72, 83, 90, 101, 108, 119, 126, 9, 0, 27, 18, 45, 36, 63, 54,
    88, 81, 74, 67, 124, 117, 110, 103, 16, 25, 2, 11, 52, 61, 38, 47,
    115, 122, 97, 104, 87, 94, 69, 76, 59, 50, 41, 32, 31, 22, 13, 4,
    106, 99, 120, 113, 78, 71, 92, 85, 34, 43, 48, 57, 6, 15, 20, 29,
    37, 44, 55, 62, 1, 8, 19, 26, 109, 100, 127, 118, 73, 64, 91, 82,
    60, 53, 46, 39, 24, 17, 10, 3, 116, 125, 102, 111, 80, 89, 66, 75,
    23, 30, 5, 12, 51, 58, 33, 40, 95, 86, 77, 68, 123, 114, 105, 96,
    14, 7, 28, 21, 42, 35, 56, 49, 70, 79, 84, 93, 98, 107, 112, 121,
])

_DELTA = 0x9E3779B9
_ROUNDS = 16
_FIELD_SIZES = {0: 1, 1: 2, 2: 2, 3: 1, 4: 2}
_FIELD_NAMES = {0: "sendOption", 1: "cmd", 2: "orderId", 3: "flags", 4: "length"}

sai_tail_dul = bytes.fromhex(
    "0101030101045452000103000100000410312e3133302e3232"
    "1432303139313231303430ca0163736f7665727365612e737472"
    "6f6e67686f6c642e66726565666972656d6f62696c652e636f6d"
    "3b302e302e302e303b33342e3132362e37362e34353b33342e38"
    "372e3137372e31343b33342e38372e3137302e3233303b33352e"
    "3138352e3138332e353700000000000001000000000000000000"
    "0000000100000000000100000000000100b8eeec91c5d7ffde110200"
)

headers = {
    'User-Agent': 'UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)',
    'Connection': 'Keep-Alive',
    'Accept-Encoding': 'gzip',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Expect': '100-continue',
    'X-Unity-Version': '2018.4.12f1',
    'X-GA-SV': '1789535859',
    'X-GA': 'v1 1',
    'ReleaseVersion': DEFAULT_RELEASE_VERSION
}

class Colors:
    HEADER = '\033[95m'
    GREEN = '\033[92m'
    FAIL = '\033[91m'
    WARNING = '\033[93m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    WHITE = '\033[97m'
    ENDC = '\033[0m'

def print_colored(text, color=Colors.WHITE):
    try:
        print(f"{color}{text}{Colors.ENDC}")
    except Exception:
        try:
            print(f"{color}{text.encode('ascii', errors='replace').decode('ascii')}{Colors.ENDC}")
        except Exception:
            pass

def print_success(text):
    print_colored(f"[+] {text}", Colors.GREEN)
    try:
        bot_state.log(text, "success")
    except Exception:
        pass

def print_error(text):
    print_colored(f"[-] {text}", Colors.FAIL)
    try:
        bot_state.log(text, "error")
    except Exception:
        pass

def print_warning(text):
    print_colored(f"[!] {text}", Colors.WARNING)
    try:
        bot_state.log(text, "warning")
    except Exception:
        pass

def print_info(text):
    print_colored(f"[i] {text}", Colors.CYAN)
    try:
        bot_state.log(text, "info")
    except Exception:
        pass

def get_proto_field(d, key, default=None):
    if not d or not isinstance(d, dict):
        return default
    if key in d:
        val = d[key].get('data')
        return val if val is not None else default
    if str(key) in d:
        val = d[str(key)].get('data')
        return val if val is not None else default
    return default


# ==================== PER-ACCOUNT MATCH COUNTER ====================
_match_counters: Dict[str, int] = {}
_match_counter_lock = asyncio.Lock()

async def _inc_match(uid: str) -> int:
    async with _match_counter_lock:
        _match_counters[uid] = _match_counters.get(uid, 0) + 1
        return _match_counters[uid]

async def _dec_match(uid: str) -> int:
    async with _match_counter_lock:
        if uid in _match_counters and _match_counters[uid] > 0:
            _match_counters[uid] -= 1
        return _match_counters.get(uid, 0)

async def _get_match_count(uid: str) -> int:
    async with _match_counter_lock:
        return _match_counters.get(uid, 0)

async def _get_total_match_count() -> int:
    async with _match_counter_lock:
        return sum(_match_counters.values())


# ==================== TOKEN CACHE ====================
_token_cache_memo: Dict[str, Any] = {}
_token_cache_memo_time: float = 0.0
_TOKEN_CACHE_MEMO_TTL = 5.0

def _json_serializer(obj):
    if isinstance(obj, (bytes, bytearray)):
        return {"__bytes_hex__": bytes(obj).hex()}
    raise TypeError(f"Type {type(obj)} not serializable")

def _json_deserializer(obj):
    if isinstance(obj, dict):
        if "__bytes_hex__" in obj and len(obj) == 1:
            try:
                return bytes.fromhex(obj["__bytes_hex__"])
            except Exception:
                return b""
        return {k: _json_deserializer(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_deserializer(x) for x in obj]
    return obj

def _load_token_cache() -> Dict[str, Any]:
    global _token_cache_memo, _token_cache_memo_time
    now = time.time()
    if _token_cache_memo and (now - _token_cache_memo_time) < _TOKEN_CACHE_MEMO_TTL:
        return _token_cache_memo

    if not os.path.exists(TOKEN_CACHE_FILE):
        return {}
    try:
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content:
            return {}
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("Cache root must be dict")
        parsed = _json_deserializer(data)
        _token_cache_memo = parsed
        _token_cache_memo_time = now
        return parsed
    except Exception as e:
        print_error(f"Token cache corrupt → deleting: {e}")
        try:
            os.remove(TOKEN_CACHE_FILE)
        except Exception:
            pass
        return {}

def _save_token_cache(cache: Dict[str, Any]):
    global _token_cache_memo, _token_cache_memo_time
    try:
        tmp_file = TOKEN_CACHE_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, default=_json_serializer)
        os.replace(tmp_file, TOKEN_CACHE_FILE)
        _token_cache_memo = cache
        _token_cache_memo_time = time.time()
    except Exception as e:
        print_error(f"Token cache save error: {e}")

def cache_get(uid: str) -> Optional[Dict]:
    cache = _load_token_cache()
    entry = cache.get(str(uid))
    if not entry:
        return None
    if time.time() - entry.get("cached_at", 0) > TOKEN_CACHE_TTL:
        print_info(f"[CACHE] UID {uid} expired. Re-login needed.")
        cache_invalidate(uid)
        return None
    if str(entry.get("account_id", "")).isdigit():
        entry["account_id"] = int(entry["account_id"])
    if not isinstance(entry.get("login_payload_data"), (bytes, bytearray)):
        print_warning(f"[CACHE] UID {uid} missing payload → invalidating")
        cache_invalidate(uid)
        return None
    return entry

def cache_set(uid: str, account_data: Dict):
    cache = _load_token_cache()
    entry = dict(account_data)
    entry["cached_at"] = time.time()
    cache[str(uid)] = entry
    _save_token_cache(cache)
    print_success(f"[CACHE] Saved credentials for UID {uid}")

def cache_invalidate(uid: str):
    cache = _load_token_cache()
    if str(uid) in cache:
        del cache[str(uid)]
        _save_token_cache(cache)
        print_warning(f"[CACHE] Invalidated: {uid}")


# ==================== ENCRYPTION & PROTOBUF ====================

async def aes_encrypt(payload, key, iv):
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return cipher.encrypt(pad(payload, AES.block_size))

def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _unique_keep_order(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _tls_block_hint(error_text: str) -> str:
    lowered = str(error_text or "").lower()
    tls_closed = (
        "tls/ssl connection has been closed" in lowered
        or "ssl_error_syscall" in lowered
        or "connection closed abruptly" in lowered
        or "empty reply from server" in lowered
    )
    if not tls_closed:
        return ""
    return (
        " Garena closed TLS before any HTTP response. This is usually a blocked/cloud IP "
        "or network route issue, not a wrong UID/password. Try from Termux/local network "
        "or set FF_PROXY=http://user:pass@host:port (SOCKS also works after installing requirements)."
    )


def _normalize_base_url(url: str, fallback: str = DEFAULT_MAJOR_LOGIN_URL) -> str:
    """Return a safe base URL with scheme and trailing slash."""
    value = str(url or fallback or "").strip()
    if not value:
        value = DEFAULT_MAJOR_LOGIN_URL
    if not value.startswith(("http://", "https://")):
        value = "https://" + value.lstrip("/")
    return value.rstrip("/") + "/"


def _normalize_endpoint_url(url: str, fallback: str = "") -> str:
    value = str(url or fallback or "").strip()
    if not value:
        return ""
    if not value.startswith(("http://", "https://")):
        value = "https://" + value.lstrip("/")
    return value


def _host_from_url(url: str, fallback: str = "clientbp.ppmainecoonghj.com") -> str:
    try:
        parsed = urlparse(_normalize_endpoint_url(url) or _normalize_base_url(url))
        return parsed.netloc or fallback
    except Exception:
        return fallback


def _major_login_endpoint(base_url: str) -> str:
    url = _normalize_endpoint_url(base_url, DEFAULT_MAJOR_LOGIN_URL)
    if url.rstrip("/").endswith("/MajorLogin"):
        return url.rstrip("/")
    return _normalize_base_url(url) + "MajorLogin"


def _candidate_major_login_urls(primary: str = "") -> List[str]:
    candidates = []
    if primary:
        candidates.append(primary)
    candidates.extend(_split_csv(DEFAULT_MAJOR_LOGIN_URLS))
    candidates.append(DEFAULT_MAJOR_LOGIN_URL)
    return _unique_keep_order([_major_login_endpoint(url) for url in candidates if url])


def _candidate_client_base_urls(primary: str = "") -> List[str]:
    candidates = []
    if primary:
        candidates.append(primary)
    candidates.extend(_split_csv(DEFAULT_CLIENT_URLS))
    return _unique_keep_order([_normalize_base_url(url) for url in candidates if url])


def _binary_headers(release_version: Optional[str], url: str) -> Dict[str, str]:
    req_headers = headers.copy()
    req_headers.update({
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; CPH2095 Build/RKQ1.211119.001)",
        "Content-Type": "application/octet-stream",
        "X-Unity-Version": "2018.4.11f1",
        "ReleaseVersion": release_version or DEFAULT_RELEASE_VERSION,
        "X-GA-SV": str(int(time.time())),
        "Host": _host_from_url(url),
    })
    req_headers.pop("Expect", None)
    return req_headers


def _pb_varint(value: int) -> bytes:
    value = int(value)
    out = bytearray()
    while True:
        to_write = value & 0x7F
        value >>= 7
        if value:
            out.append(to_write | 0x80)
        else:
            out.append(to_write)
            break
    return bytes(out)


def _pb_string(field_number: int, value: Any) -> bytes:
    raw = str(value).encode("utf-8")
    return _pb_varint((int(field_number) << 3) | 2) + _pb_varint(len(raw)) + raw


async def build_minimal_majorlogin_payload(open_id, access_token, platform):
    """OB55 fallback MajorLogin payload using only verified auth fields."""
    try:
        platform_str = str(platform or 4)
        payload = (
            _pb_string(22, open_id)
            + _pb_string(23, platform_str)
            + _pb_string(29, access_token)
            + _pb_string(99, platform_str)
        )
        return await aes_encrypt(payload, AES_KEY, AES_IV)
    except Exception as e:
        print_error(f"[LOGIN] Could not build fallback MajorLogin payload: {e}")
        return None


async def get_playstore_version():
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None,
            lambda: play_scraper('com.dts.freefireth', lang='hi', country='id')
        )
        version = result.get("version") if isinstance(result, dict) else None
        if version:
            return version
        print_warning(f"[VERSION] Play Store response missing version. Using fallback {DEFAULT_APP_VERSION}")
    except Exception as e:
        print_warning(f"[VERSION] Play Store lookup failed: {e}. Using fallback {DEFAULT_APP_VERSION}")
    return DEFAULT_APP_VERSION


async def version_config():
    app_version = await get_playstore_version()
    api_url = (
        "https://version.ggwhitehawk.com/live/ver.php"
        f"?version={app_version}"
        "&lang=hi&device=android&channel=android"
        "&appstore=googleplay&region=BD"
        "&whitelist_version=1.3.0&whitelist_sp_version=1.0.0"
    )
    try:
        response = await client.get(api_url)
        response.raise_for_status()
        data = response.json()
        server_url = data.get("server_url")
        remote_version = data.get("remote_version")
        latest_release_version = data.get("latest_release_version")
        if server_url and remote_version and latest_release_version:
            server_url = _normalize_base_url(server_url)
            print_info(f"[VERSION] Release {latest_release_version}, client {remote_version}, login {server_url}")
            return latest_release_version, remote_version, server_url
        print_warning(f"[VERSION] Config response incomplete: {data}")
    except Exception as e:
        print_warning(f"[VERSION] Remote config failed: {e}")

    fallback_url = _normalize_base_url(DEFAULT_MAJOR_LOGIN_URL)
    print_warning(
        f"[VERSION] Using fallback config: {DEFAULT_RELEASE_VERSION}, "
        f"client {DEFAULT_CLIENT_VERSION}, login {fallback_url}"
    )
    return DEFAULT_RELEASE_VERSION, DEFAULT_CLIENT_VERSION, fallback_url

async def get_access_token(uid, password):
    hdrs = {
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 13; CPH2095 Build/RKQ1.211119.001)",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept-Encoding": "gzip",
        "Connection": "Keep-Alive"
    }
    data = {
        "uid": uid,
        "password": password,
        "response_type": "token",
        "client_type": "2",
        "client_secret": "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
        "client_id": "100067"
    }
    last_error = "unknown"
    urls = _unique_keep_order([_normalize_endpoint_url(url) for url in _split_csv(DEFAULT_TOKEN_GRANT_URLS)])
    for url in urls:
        endpoint_headers = hdrs.copy()
        endpoint_headers["Host"] = _host_from_url(url, "ffmconnect.live.gop.garenanow.com")
        for attempt in range(1, 4):
            try:
                response = await client.post(url, headers=endpoint_headers, data=data)
                if response.status_code == 200:
                    response_data = response.json()
                    open_id = response_data.get("open_id")
                    access_token = response_data.get("access_token")
                    platform = response_data.get("platform", 4)
                    if open_id and access_token:
                        print_success(f"[TOKEN] Guest token granted for UID {uid}")
                        return open_id, access_token, platform
                    last_error = f"token response missing open_id/access_token: {response_data}"
                    print_warning(f"[TOKEN] {last_error}")
                    break

                body_preview = response.text[:180].replace("\n", " ")
                last_error = f"{_host_from_url(url)} HTTP {response.status_code}: {body_preview}"
                if response.status_code in (400, 401, 403):
                    print_warning(f"[TOKEN] Endpoint rejected UID {uid}: {last_error}")
                    break
                if response.status_code == 429:
                    print_warning(f"[TOKEN] Rate limited on {_host_from_url(url)}; retry {attempt}/3")
                    await asyncio.sleep(min(6, attempt * 1.5))
                    continue
                print_warning(f"[TOKEN] Attempt {attempt}/3 failed: {last_error}")
            except Exception as e:
                last_error = f"{_host_from_url(url)}: {e}"
                print_warning(f"[TOKEN] Attempt {attempt}/3 network error on {_host_from_url(url)}: {e}")
            await asyncio.sleep(min(3, 0.5 * attempt))

    print_error(f"[TOKEN] Could not get guest token for UID {uid}. Last error: {last_error}{_tls_block_hint(last_error)}")
    return None


async def inspect_access_token(access_token: str) -> Optional[Tuple[str, Any]]:
    last_error = "unknown"
    for base_url in _split_csv(DEFAULT_TOKEN_INSPECT_URLS):
        url = _normalize_endpoint_url(base_url)
        separator = "&" if "?" in url else "?"
        inspect_url = f"{url}{separator}token={access_token}"
        hdrs = {
            "Accept-Encoding": "gzip",
            "Connection": "Keep-Alive",
            "Content-Type": "application/x-www-form-urlencoded",
            "Host": _host_from_url(url, "ffmconnect.live.gop.garenanow.com"),
            "User-Agent": "GarenaMSDK/4.0.19P4(G011A ;Android 13;en;US;)"
        }
        try:
            resp = await client.get(inspect_url, headers=hdrs)
            if resp.status_code != 200:
                last_error = f"{_host_from_url(url)} HTTP {resp.status_code}: {resp.text[:160]}"
                print_warning(f"[TOKEN] Token inspect endpoint failed: {last_error}")
                continue
            data = resp.json()
            if 'error' in data:
                last_error = str(data.get('error'))
                print_warning(f"[TOKEN] Access token rejected by {_host_from_url(url)}: {last_error}")
                continue
            open_id = data.get('open_id')
            platform = data.get('platform', 4)
            if open_id:
                return open_id, platform
            last_error = f"inspect response missing open_id: {data}"
            print_warning(f"[TOKEN] {last_error}")
        except Exception as e:
            last_error = f"{_host_from_url(url)}: {e}"
            print_warning(f"[TOKEN] Token inspect network error on {_host_from_url(url)}: {e}")
    print_error(f"[TOKEN] Could not inspect access token. Last error: {last_error}{_tls_block_hint(last_error)}")
    return None

async def parse_results(parsed_results):
    result_dict = {}
    for result in parsed_results:
        field_data = {"wire_type": result.wire_type}
        if result.wire_type == "varint":
            field_data["data"] = result.data
        elif result.wire_type == "string":
            field_data["data"] = result.data
        elif result.wire_type == "bytes":
            field_data["data"] = result.data
        elif result.wire_type == "length_delimited":
            field_data["data"] = await parse_results(result.data.results)
        result_dict[result.field] = field_data
    return result_dict

async def decode_protobuf(data):
    parsed_results = Parser().parse(data)
    parsed_results_dict = await parse_results(parsed_results)
    return json.dumps(parsed_results_dict)

async def build_majorlogin_payload(open_id, access_token, platform, client_version, device_info):
    try:
        proto = thunderFF_pb2.MajorLoginReq()
        proto.event_time = str(datetime.now())[:-7]
        proto.game_name = "free fire"
        proto.platform_id = 1 if str(platform) in ["1", "4"] else int(platform)
        proto.client_version = client_version
        proto.client_version_code = "2019121229"
        
        # --- INJECTING PERSISTENT DYNAMIC DEVICE DATA ---
        proto.system_software = device_info.get("system_software", "Android OS 12 / API-31 (SP1A.210812.016.C2/user.dxu.20260701.180839)")
        proto.system_hardware = device_info.get("brand", "Handheld")
        proto.device_type = device_info.get("model", "Handheld")
        proto.screen_width = int(device_info.get("screen_width", 1600))
        proto.screen_height = int(device_info.get("screen_height", 900))
        proto.screen_dpi = str(device_info.get("screen_dpi", "300"))
        proto.processor_details = device_info.get("processor_details", "x86-64 SSE3 SSE4.1 SSE4.2 AVX | 2400 | 4")
        proto.memory = int(device_info.get("memory", 5951))
        proto.gpu_renderer = device_info.get("gpu_renderer", "Adreno (TM) 640")
        proto.unique_device_id = device_info.get("unique_device_id", "Google|725030d8-6585-4f55-bcca-a6df7e59935b")
        proto.client_ip = device_info.get("client_ip", "103.145.112.210")
        # ------------------------------------------------
        
        proto.telecom_operator = "Citycell"
        proto.network_operator_a = "Citycell"
        proto.network_type = "WIFI"
        proto.network_type_a = "WIFI"
        proto.cpu_type = 2
        proto.cpu_architecture = "64"
        proto.gpu_version = "OpenGL ES 3.2"
        proto.graphics_api = "OpenGLES2"
        proto.language = "en"
        proto.open_id = open_id
        proto.open_id_type = str(platform)
        proto.login_open_id_type = int(platform)
        proto.access_token = access_token
        proto.login_by = 3
        proto.platform_sdk_id = 2
        proto.origin_platform_type = str(platform)
        proto.primary_platform_type = str(platform)
        proto.reg_avatar = 1
        proto.channel_type = 3
        
        memory_available = proto.memory_available
        memory_available.version = 55
        memory_available.hidden_value = 81
        
        proto.external_storage_total = 34308
        proto.external_storage_available = 30777
        proto.internal_storage_total = 2519
        proto.internal_storage_available = 243
        proto.game_disk_storage_total = 34308
        proto.game_disk_storage_available = 32224
        proto.external_sdcard_total_storage = 34308
        proto.external_sdcard_avail_storage = 32224
        
        proto.library_path = "/data/app/~~UKDdGuy32C5yOa0KZe_ROA==/com.dts.freefireth-UAKF1gjDbXSGfpA07JDTKQ==/lib/arm64"
        proto.library_token = "b8e0cd5e295eee42f5860d3c86e483dd|/data/app/~~UKDdGuy32C5yOa0KZe_ROA==/com.dts.freefireth-UAKF1gjDbXSGfpA07JDTKQ==/base.apk"
        proto.client_using_version = "7428b253defc164018c604a1ebbfebdf"
        proto.supported_astc_bitset = 4095
        proto.analytics_detail = b"FwQVTgUPX1UaUllDDwcWCRBpWAUOUgsvA1snWlBaO1kFYg=="
        proto.loading_time = 14582
        proto.release_channel = "android"
        proto.extra_info = "KqsHT4tDHGqm9PQ3syB24XA4N6SWy/Q/HfMFTQM+SgxmVqsgPK138ajtCFyVNW/Q7p6hxoenpRjeZ2NphiIosCZ3YDkONB5NAa+zTwNo7iabx/mj"
        proto.android_engine_init_flag = 111207
        proto.if_push = 1
        proto.is_vpn = 0
        
        payload = proto.SerializeToString()
        return await aes_encrypt(payload, AES_KEY, AES_IV)
    except Exception as e:
        print_error(f"[LOGIN] Could not build MajorLogin payload: {e}")
        return None

def _parse_majorlogin_response(response_content: bytes) -> Optional[Any]:
    # OB55 responses observed in the wild use a 64-byte prefix. Keep dynamic
    # fallback offsets because routing variants sometimes differ.
    offsets = []
    if len(response_content) > 64:
        offsets.append(64)
    offsets.append(0)
    offsets.extend(range(1, min(128, len(response_content))))

    for offset in _unique_keep_order(offsets):
        if offset >= len(response_content):
            continue
        try:
            candidate = thunderFF_pb2.MajorLoginRes()
            candidate.ParseFromString(response_content[offset:])
            if candidate.region and candidate.token and candidate.url:
                return candidate
        except Exception:
            pass
    return None


async def send_majorlogin(data, release_version, server_url):
    if not data:
        print_error("[MAJORLOGIN] Empty encrypted payload; cannot login")
        return None

    last_error = "unknown"
    for url in _candidate_major_login_urls(server_url):
        try:
            req_headers = _binary_headers(release_version, url)
            response = await client.post(url, headers=req_headers, data=data)
            if response.status_code != 200:
                preview = response.text[:180].replace("\n", " ")
                last_error = f"{_host_from_url(url)} HTTP {response.status_code}: {preview}"
                print_warning(f"[MAJORLOGIN] {last_error}")
                continue
            response_content = response.content
            if len(response_content) < 40:
                last_error = f"{_host_from_url(url)} short response ({len(response_content)} bytes)"
                print_warning(f"[MAJORLOGIN] {last_error}")
                continue

            parsed = _parse_majorlogin_response(response_content)
            if parsed:
                print_success(f"[MAJORLOGIN] Login OK for account {parsed.account_id} ({parsed.region}) via {_host_from_url(url)}")
                return parsed

            last_error = f"{_host_from_url(url)} response did not contain token/region/server URL"
            print_warning(f"[MAJORLOGIN] {last_error}")
        except Exception as e:
            last_error = f"{_host_from_url(url)}: {e}"
            print_warning(f"[MAJORLOGIN] Request failed on {_host_from_url(url)}: {e}")

    print_error(f"[MAJORLOGIN] All endpoints failed. Last error: {last_error}{_tls_block_hint(last_error)}")
    return None

async def send_getlogin(data, base_url, token, release_version):
    if not data or not token:
        print_error("[GETLOGIN] Missing payload or bearer token")
        return None

    last_error = "unknown"
    for safe_base in _candidate_client_base_urls(base_url):
        try:
            url = f"{safe_base.rstrip('/')}/GetLoginData"
            req_headers = _binary_headers(release_version, url)
            req_headers['Authorization'] = f"Bearer {token}"
            response = await client.post(url, headers=req_headers, data=data)
            if response.status_code != 200:
                preview = response.text[:180].replace("\n", " ")
                last_error = f"{_host_from_url(url)} HTTP {response.status_code}: {preview}"
                print_warning(f"[GETLOGIN] {last_error}")
                continue
            response_content = response.content

            res_proto = thunderFF_pb2.GetLoginDataRes()
            parsed_successfully = False
            try:
                res_proto.ParseFromString(response_content)
                if res_proto.functional_addrs or res_proto.informational_addrs:
                    parsed_successfully = True
            except Exception:
                pass

            if not parsed_successfully:
                for offset in range(min(128, len(response_content))):
                    try:
                        candidate = thunderFF_pb2.GetLoginDataRes()
                        candidate.ParseFromString(response_content[offset:])
                        if candidate.functional_addrs or candidate.informational_addrs:
                            res_proto = candidate
                            parsed_successfully = True
                            break
                    except Exception:
                        pass

            dict_res = {}
            try:
                parsed = Parser().parse(response_content.hex())
                dict_res = await parse_results(parsed)
            except Exception:
                pass

            if parsed_successfully:
                print_success(f"[GETLOGIN] Gateway info loaded via {_host_from_url(url)}")
            else:
                print_warning(f"[GETLOGIN] Parsed fallback fields only via {_host_from_url(url)}; gateway addresses may be missing")
            return res_proto, dict_res
        except Exception as e:
            last_error = f"{_host_from_url(safe_base)}: {e}"
            print_warning(f"[GETLOGIN] Request failed on {_host_from_url(safe_base)}: {e}")

    print_error(f"[GETLOGIN] All endpoints failed. Last error: {last_error}{_tls_block_hint(last_error)}")
    return None

def _region_gateway_suffix(region: Any) -> str:
    """Gateway packet suffix used by TCP/Lone Wolf packets for each lock region."""
    reg = str(region or "BD").upper()
    if reg == "BD":
        return "19"
    if reg in {"IND", "IN"}:
        return "14"
    return "15"


async def build_tcp_startup_packet(account_id, token, server_time, key, iv, region="BD", typ='OnLine'):
    uid_hex = f"{int(account_id):016x}"
    timestamp_hex = f"{int(server_time):08x}"
    encode_token = token.encode()
    encrypted_packet = (await aes_encrypt(encode_token, key, iv)).hex()
    encrypted_packet_length = f"{len(encrypted_packet) // 2:08x}"
    suffix = _region_gateway_suffix(region)
    if typ == 'OnLine':
        return f"71{suffix}{uid_hex}{timestamp_hex}00000000{encrypted_packet_length}{encrypted_packet}"
    else:  # ChaT / Informational
        return f"92{suffix}{uid_hex}{timestamp_hex}{encrypted_packet_length}{encrypted_packet}"

async def send_keep_alive(region="BD"):
    """Send 2-byte keep-alive pulse to maintain connection in OB55"""
    try:
        return bytes.fromhex(f"02{_region_gateway_suffix(region)}")
    except Exception:
        return bytes.fromhex("0219")


def _startmatch_prefix() -> str:
    prefix = STARTMATCH_PACKET_PREFIX.lower().replace(" ", "")
    if len(prefix) != 6:
        print_warning(f"[LONE WOLF] Invalid FF_STARTMATCH_PREFIX={STARTMATCH_PACKET_PREFIX!r}; using 031400")
        return "031400"
    try:
        bytes.fromhex(prefix)
        return prefix
    except ValueError:
        print_warning(f"[LONE WOLF] Invalid FF_STARTMATCH_PREFIX={STARTMATCH_PACKET_PREFIX!r}; using 031400")
        return "031400"


async def start_game_lone_wolf(matchmaking_region, client_version, writer, key, iv):
    packet = bytes.fromhex("080112800a0a010b102b3a110a044944433110aa011a064555524f50453a100a044944433210311a064555524f504540014a0801090a0b1219202758016291090a8001303838463832424630324139363736373032303130313030303030303030303030303136303030313030313530303032323246393745454530463030303030303436373632353134303030303030303030303030303030303030303030303030303030303030303030303030303066663030303030303030636163666131366410241afb02735d5e571400024a775d45414d1a041b1c001f11010449715f4243481a001e1d071c1703004b1a4066785c524570735c51486775421b5c5a4c07504042685a63610816054e19025e75196001477c015165406370195f5547404e4550640103020f1304064863754268676c755f65576e40467e5f0a417a4701026d675d6e73670b1108495a4c6a0b78470b740065645e525a057258425f584a447d4e6759440c11044e7c596d7f4b625f7d04055a47505c4e1d6b5b4107447d7201057d7f0f14084e430457674f7e517d72015172415d027473577c4d615f79535256780911030f4d5e027a797f614165067806505d53777750475e75064257076500460817014e741e7e5078487e7a7c465e7669767153497064605a7376677773550d160148037e18675966787f4c42607a645f577e7b441b460776026b18685d0b110205490060020f70676175654674706671797f41067346677c4e06585e780f15074c57047b40517075415f6364027259674b5b0166407f7340600407770a22047a5d5c52300b3a0a167305067162727516134208312e3133302e3232480350015ae90403626253513635686e556f4e36416456324b796f566c636f477776484f624e56526c4d727073504b4f43654177616848494176795556497273743752737149734a7a786b3247525268377a2f637664626d504f6a73552f79626d38547a4c69586d2f474351696d494b53486833447955726f39515152756c34545350626d6d624b7949565937545671577059455372323646572f59624578507338514f706d317372785455736c30796a434144444d4f34616a654b615753366361496c554b4963797a494e396d52516f715277687939797257476d337a644345337a6a61436f492f5a585233656f65365a42647a64677654636b6b665733356e4d4c6a6a565072564b6433523172756174394e50514150724a5546627859696c4c5a3859707336654d5447666b6649793574666a526c314d4648706b51774c6373374439656378566c41636f374e664f6d2b30654756466c4434744478706771385533595973587645384842502f70666c767a737138316a32524f4d7857437556445442492f684735625462773166456e4249725162762b636144775147696f74554e316d4c4b77734379456f4766706746614251457645672b736a764c4c78704743334c304a5344532f74526169504354553344374e6249306547516651622f5a466f4c36455630775a324d6f583932414c572f5049752f56634663584e70596b356f7966326151416a536971486a2f363276354843644f525551303578754e6171795251625653704654303137655237675255636b4966366c6f447476342b514e4a4670766d74757077707774396a5a5974437a4b56743657726d6e36785837706658456251555434684f3758a201050803108703a201050804108103a20105080510c001a20105081d10cc01a2010408161078a20105080e10af01a201020815")
    proto = thunderFF_pb2.StartMatch()
    proto.ParseFromString(packet)
    # This captured Lone Wolf packet uses matchmaking shard "EUROPE". Replacing
    # it with the account lock region (BD/IND/etc.) makes the functional gateway
    # close immediately after StartMatch. Keep EUROPE by default, but allow an
    # override for future captures.
    if matchmaking_region and hasattr(proto.main, 'region_list') and len(proto.main.region_list) > 0:
        proto.main.region_list[0].region = matchmaking_region
        if len(proto.main.region_list) > 1:
            proto.main.region_list[1].region = matchmaking_region
    if hasattr(proto.main, 'client_version'):
        proto.main.client_version.remote_version = client_version
    packet = proto.SerializeToString()
    encrypted_packet = (await aes_encrypt(packet, key, iv)).hex()
    packet_length = len(encrypted_packet) // 2
    hex_length = hex(packet_length)[2:]
    hex_length = hex_length if len(hex_length) > 1 else "0" + hex_length
    gateway_prefix = _startmatch_prefix()
    final_packet = gateway_prefix + "0" * (6 - len(hex_length)) + hex_length + encrypted_packet
    writer.write(bytes.fromhex(final_packet))
    await writer.drain()
    return packet_length, gateway_prefix, matchmaking_region

async def has_ssan_zig(n):
    z = (n << 1) & 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while z >= 0x80:
        out.append((z & 0x7F) | 0x80)
        z >>= 7
    out.append(z)
    return bytes(out)

async def uleb_encode(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            break
    return bytes(out)

async def tea_enc(v0, v1, k0, k1, k2, k3):
    s = 0
    for _ in range(_ROUNDS):
        s = (s + _DELTA) & 0xFFFFFFFF
        v0 = (v0 + (((((v1 << 4) & 0xFFFFFFFF) + k0) & 0xFFFFFFFF ^
                      ((v1 + s) & 0xFFFFFFFF) ^
                      (((v1 >> 5) + k1) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        v1 = (v1 + (((((v0 << 4) & 0xFFFFFFFF) + k2) & 0xFFFFFFFF ^
                      ((v0 + s) & 0xFFFFFFFF) ^
                      (((v0 >> 5) + k3) & 0xFFFFFFFF)))) & 0xFFFFFFFF
    return v0, v1

async def tea_dec(v0, v1, k0, k1, k2, k3):
    s = (_DELTA * _ROUNDS) & 0xFFFFFFFF
    for _ in range(_ROUNDS):
        v1 = (v1 - (((((v0 << 4) & 0xFFFFFFFF) + k2) & 0xFFFFFFFF ^
                      ((v0 + s) & 0xFFFFFFFF) ^
                      (((v0 >> 5) + k3) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        v0 = (v0 - (((((v1 << 4) & 0xFFFFFFFF) + k0) & 0xFFFFFFFF ^
                      ((v1 + s) & 0xFFFFFFFF) ^
                      (((v1 >> 5) + k1) & 0xFFFFFFFF)))) & 0xFFFFFFFF
        s = (s - _DELTA) & 0xFFFFFFFF
    return v0, v1

async def tea_cbc_encrypt(padded, key_bytes):
    k0, k1, k2, k3 = (struct.unpack_from("<I", key_bytes, o)[0] for o in (0, 4, 8, 12))
    out = bytearray(len(padded))
    prev_cipher = bytearray(8)
    prev_intermediate = bytearray(8)
    for i in range(0, len(padded), 8):
        xored = bytearray(8)
        for j in range(8):
            xored[j] = padded[i + j] ^ prev_cipher[j]
        e0, e1 = await tea_enc(
            struct.unpack_from("<I", xored, 0)[0],
            struct.unpack_from("<I", xored, 4)[0],
            k0, k1, k2, k3,
        )
        enc = bytearray(8)
        struct.pack_into("<I", enc, 0, e0)
        struct.pack_into("<I", enc, 4, e1)
        for j in range(8):
            out[i + j] = enc[j] ^ prev_intermediate[j]
        prev_cipher[:] = out[i:i + 8]
        prev_intermediate[:] = xored
    return bytes(out)

async def build_padded(content):
    pad_len = (8 - (len(content) + 10) % 8) % 8
    return bytes([pad_len, 0, 0]) + b"\x00" * pad_len + content + b"\x00" * 7

async def encode_header(layout, send_option, cmd, order_id, flags, length, k, v80):
    out = bytearray()
    for code in layout:
        value = {0: send_option, 1: cmd, 2: order_id, 3: flags, 4: length}[code]
        if _FIELD_SIZES[code] == 1:
            out.append((value & 0xFF) ^ k)
        else:
            v = ((value & 0xFFFF) ^ v80) & 0xFFFF
            out.append(v & 0xFF)
            out.append((v >> 8) & 0xFF)
    return bytes(out)

async def crc7_buff(crc, buf):
    c = crc & 0x7F
    for b in buf:
        c = CRC7_TABLE[((2 * (c & 0xFF)) ^ (b & 0xFF)) & 0xFF] & 0x7F
    return c & 0x7F

async def sv_frame(msg_key, layout, send_option, cmd, order_id, flags, content, key, encrypted=True):
    k = key[0]
    v80 = ((k << 8) | k) & 0xFFFF
    body = await tea_cbc_encrypt(await build_padded(content), key) if encrypted else content
    hdr = bytearray([msg_key, 0]) + await encode_header(layout, send_option, cmd, order_id, flags, len(body), k, v80)
    packet = bytearray(hdr + body)
    packet[1] = await crc7_buff(0, bytes(packet[2:])) & 0x7F
    return bytes(packet)

async def build_match_startup_packets(token, udp_key, match_code, account_id, block_val,
                                      server_ip="", region="BD", client_version="1.132.6",
                                      client_version_code="2019121229", access_token=""):
    token = token.strip()
    udp_key = bytes.fromhex(udp_key)
    match_code = [int(ch) for ch in str(match_code).strip()]
    
    # OB55 splits JWT match token at 660 bytes
    thunder_jwt = token[:660] if len(token) > 660 else token
    sharma_jwt = token[660:] if len(token) > 660 else ""
    encoded_thunder_jwt = thunder_jwt.encode() if isinstance(thunder_jwt, str) else thunder_jwt
    encoded_sharma_jwt = sharma_jwt.encode() if isinstance(sharma_jwt, str) else sharma_jwt
    
    garena420 = await has_ssan_zig(len(encoded_thunder_jwt)) + encoded_thunder_jwt
    
    # OB55 Sharma payload structure matching Wireshark capture
    reg = str(region).upper() if region else "BD"
    csoversea_block = bytes.fromhex(
        "ca0163736f7665727365612e7374726f6e67686f6c642e66726565666972656d6f62696c652e636f6d"
        "3b302e302e302e303b33342e3132362e37362e34353b33342e38372e3137372e31343b33342e38372e"
        "3137302e3233303b33352e3138352e3138332e35370000000000000100000000000000000000000001"
        "00000800000100000000000100a8a2d7bebd8d8bdf110200"
    )
    
    mid = bytes.fromhex('0000000001000102030101') + await has_ssan_zig(len(reg)) + reg.encode()
    mid += bytes.fromhex('0001030003000004')
    mid += await has_ssan_zig(len(client_version)) + client_version.encode()
    mid += await has_ssan_zig(len(client_version_code)) + client_version_code.encode()
    mid += csoversea_block
    
    clean_ip = server_ip.split(':')[0] if server_ip else "0.0.0.0"
    mid += await has_ssan_zig(len(clean_ip)) + clean_ip.encode()
    
    clean_acc_tok = access_token.strip() if access_token else ""
    if clean_acc_tok:
        mid += await has_ssan_zig(len(clean_acc_tok)) + clean_acc_tok.encode()
        
    mid += await has_ssan_zig(len(encoded_sharma_jwt)) + encoded_sharma_jwt
    
    tg_garena420 = (
        await uleb_encode(int(account_id)) +
        await uleb_encode(int(block_val)) +
        await uleb_encode(1) +
        await uleb_encode(43) +
        await uleb_encode(int(block_val)) +
        await uleb_encode(11) +
        mid
    )
    
    process = await sv_frame(0x5E, match_code, 2, 447, 0, 1, garena420, udp_key)
    loading = await sv_frame(0x5A, match_code, 2, 448, 1, 1, tg_garena420, udp_key)
    return process.hex(), loading.hex()

async def produce_xor_key(secret_key):
    k = secret_key[0] if secret_key and len(secret_key) > 0 else 10
    return k, ((k << 8) | k) & 0xFFFF

async def parse_layout(layout):
    if isinstance(layout, str):
        return [int(ch) for ch in layout.strip()]
    return list(layout)

async def tea_cbc_decrypt(body, key_bytes):
    k0, k1, k2, k3 = (struct.unpack_from("<I", key_bytes, o)[0] for o in (0, 4, 8, 12))
    out = bytearray(len(body))
    prev_intermediate = bytearray(8)
    prev_cipher = bytearray(8)
    xored = bytearray(8)
    dec = bytearray(8)
    for i in range(0, len(body), 8):
        for j in range(8):
            xored[j] = body[i + j] ^ prev_intermediate[j]
        d0, d1 = await tea_dec(
            struct.unpack_from("<I", xored, 0)[0],
            struct.unpack_from("<I", xored, 4)[0],
            k0, k1, k2, k3
        )
        struct.pack_into("<I", dec, 0, d0)
        struct.pack_into("<I", dec, 4, d1)
        for j in range(8):
            out[i + j] = dec[j] ^ prev_cipher[j]
        prev_cipher[:] = body[i:i + 8]
        prev_intermediate[:] = dec
    return bytes(out)

async def build_hello_packet(text, key, layout):
    data = text.encode("utf-8")
    if len(data) > 25:
        raise ValueError(f"Text is too long ({len(data)} bytes)")
    content = b"\x10\x00\x00\x00" + data + b"\x00" * (29 - 4 - len(data))
    k, v80 = await produce_xor_key(key)
    layout = await parse_layout(layout)
    padded = await build_padded(content)
    enc_body = await tea_cbc_encrypt(padded, key)
    header_bytes = await encode_header(layout, 1, 1, 0, 1, len(enc_body), k, v80)
    packet = bytearray([0x63, 0x00]) + header_bytes + enc_body
    packet[1] = await crc7_buff(0, packet[2:]) & 0x7F
    return bytes(packet).hex()

async def classify(frame):
    cmd = frame["cmd"]
    msg_name = MESSAGE_ID_TO_NAME.get(cmd, f"UNKNOWN_{cmd}")
    if msg_name == "UDP_HELLO":
        return "HELLO"
    if msg_name == "UDP_ACK":
        return "ACK"
    if msg_name == "UDP_PING":
        return "PING"
    if msg_name == "RUDP_JOIN_MATCH":
        return "JOIN_MATCH"
    if msg_name.startswith("RUDP_"):
        return msg_name
    if msg_name.startswith("UDP_"):
        return msg_name
    return "DATA"

async def build_packet(msg_key, layout, send_option, cmd, order_id, flags, content, key, encrypted=True):
    k = key[0]
    v80 = ((k << 8) | k) & 0xFFFF
    body = await tea_cbc_encrypt(await build_padded(content), key) if encrypted else content
    hdr = bytearray([msg_key, 0])
    for code in layout:
        value = {0: send_option, 1: cmd, 2: order_id, 3: flags, 4: len(body)}[code]
        if _FIELD_SIZES[code] == 1:
            hdr.append((value & 0xFF) ^ k)
        else:
            v = ((value & 0xFFFF) ^ v80) & 0xFFFF
            hdr.append(v & 0xFF)
            hdr.append((v >> 8) & 0xFF)
    packet = bytearray(hdr + body)
    packet[1] = await crc7_buff(0, bytes(packet[2:])) & 0x7F
    return bytes(packet)

async def layouts_from_mask(mask):
    ru = [int(c) for c in str(mask).strip()]
    nr = [c for c in ru if c != 2]
    return ru, nr

async def reply_for(frame, key, mask, ack_key=0x68, ping_key=0x6D, hello_key=0x5B, ack_style="short"):
    ru, nr = await layouts_from_mask(mask)
    typ = await classify(frame)
    if typ == "HELLO":
        if ack_style == "echo":
            content = frame["content"] if frame["content"] else b"\x10\x00\x00\x00"
            return typ, await build_packet(hello_key, nr, 1, 1, None, 1, content, key)
        return typ, await build_packet(ack_key, nr, 0, 2, None, 1, b"\x01\x00", key)
    if typ == "ACK":
        content = frame["content"] if frame["content"] else b"\x01\x00"
        return typ, await build_packet(ack_key, nr, 0, 2, None, 1, content, key)
    if typ == "PING":
        c = frame["content"]
        counter = c[:4] if len(c) >= 4 else c
        return typ, await build_packet(ping_key, nr, 0, 3, None, 0, counter + b"\x00\x00\x00", key, encrypted=False)
    if typ == "JOIN_MATCH":
        return typ, await build_packet(ack_key, nr, 0, 2, None, 1, b"\x02\x00", key)
    return typ, None

async def keepalive_ping(sock, ip, port, key_bytes, mask, stop_event):
    nr = (await layouts_from_mask(mask))[1]
    ping_keys = [0x66, 0x6D, 0x69, 0x6C, 0x6B, 0x6E, 0x6F, 0x70]
    loop = asyncio.get_event_loop()
    i = 0
    while not stop_event.is_set():
        pk = ping_keys[i % len(ping_keys)]
        counter = int(time.time() * 1000) & 0xFFFFFFFF
        pkt = await build_packet(pk, nr, 0, 3, None, 0, struct.pack("<I", counter) + b"\x00\x00\x00", key_bytes, encrypted=False)
        try:
            await loop.sock_sendto(sock, pkt, (ip, port))
        except Exception:
            pass
        i += 1
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            pass

async def try_header(buf, layout, k, v80):
    off = 2
    out = {}
    for code in layout:
        size = _FIELD_SIZES[code]
        if off + size > len(buf):
            return None
        out[_FIELD_NAMES[code]] = (buf[off] ^ k) if size == 1 else ((buf[off] | (buf[off + 1] << 8)) ^ v80) & 0xFFFF
        off += size
    out["headerLen"] = off
    return out

async def oicq_unpad(padded):
    if not padded or len(padded) < 8:
        return None
    if not all(padded[-1 - i] == 0 for i in range(7)):
        return None
    pad_len = padded[0] & 0x07
    s = 3 + pad_len
    e = len(padded) - 7
    return padded[s:e] if s < e else b""

async def decode_packet(packet, key, mask=None):
    data = bytes(packet) if isinstance(packet, bytes) else bytes.fromhex(packet)
    if len(data) < 8:
        return None
    k = key[0]
    v80 = ((k << 8) | k) & 0xFFFF
    crc_ok = (data[1] & 0x7F) == await crc7_buff(0, data[2:])
    candidates = []
    if mask:
        ru, nr = await layouts_from_mask(mask)
        layouts = [("RUDP", ru), ("nonRUDP", nr)]
    else:
        layouts = [("RUDP", list(p)) for p in itertools.permutations([0, 1, 2, 3, 4])]
        layouts += [("nonRUDP", list(p)) for p in itertools.permutations([0, 1, 3, 4])]
    for kind, layout in layouts:
        f = await try_header(data, layout, k, v80)
        if not f:
            continue
        if f["flags"] > 7 or f["sendOption"] > 7:
            continue
        if f["length"] != len(data) - f["headerLen"]:
            continue
        body = data[f["headerLen"]:f["headerLen"] + f["length"]]
        content = None
        padded = None
        if f["flags"] & 1:
            if len(body) < 8 or len(body) % 8 != 0:
                continue
            padded = await tea_cbc_decrypt(body, key)
            content = await oicq_unpad(padded)
            if content is None:
                continue
        else:
            content = body
        score = (1 if crc_ok else 0) + (1 if content is not None else 0)
        candidates.append({
            "kind": kind, "layout": layout, "headerLen": f["headerLen"],
            "msgKey": data[0], "cmd": f["cmd"], "flags": f["flags"],
            "sendOption": f["sendOption"], "orderId": f.get("orderId"),
            "length": f["length"], "content": content, "crcOk": crc_ok,
            "padded": padded, "score": score, "total": len(data),
        })
    if not candidates:
        return None
    candidates.sort(key=lambda c: (c["kind"] == "RUDP" or c["kind"] == "nonRUDP", c["score"]), reverse=True)
    return candidates[0]


# ============================================================
# play_game — UDP MATCH (FIXED & DNS OPTIMIZED)
# ============================================================
async def play_game(server_ip_port, thunder, sharma, udp_key, match_code,
                    account_id, player_region, client_version, key, iv,
                    match_index: int):
    match_start_time = time.time()
    ping_task = None
    sock = None
    ping_stop = asyncio.Event()
    uid_str = str(account_id)
    completed_cleanly = False

    try:
        ip, port = server_ip_port.split(":")
        port = int(port)
        resolved_ip = await resolve_host_cloudflare(ip)

        loop = asyncio.get_event_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        optimize_udp_socket(sock)
        sock.setblocking(False)
        
        udp_key_bytes = bytes.fromhex(udp_key)
        hello_packet = await build_hello_packet(f"{account_id}_2585", udp_key_bytes, match_code)
        await loop.sock_sendto(sock, bytes.fromhex(hello_packet), (resolved_ip, port))

        ack_state = "waiting_for_hello_reply"
        thunder_sent = False
        sharma_sent = False
        join_match_received = False
        local_closed = False
        send_lock = asyncio.Lock()

        ping_task = asyncio.create_task(
            keepalive_ping(sock, resolved_ip, port, udp_key_bytes, match_code, ping_stop)
        )
        last_activity = time.time()
        MAX_IDLE_BEFORE_HELLO_RESEND = 7.0

        print_colored(
            f"🎮 [MATCH #{match_index}] UDP started → {server_ip_port} (DNS: {resolved_ip})",
            Colors.MAGENTA
        )

        async def send_thunder_sharma_inline():
            nonlocal ack_state, thunder_sent, sharma_sent
            if thunder_sent:
                return
            async with send_lock:
                if thunder_sent:
                    return
                try:
                    await loop.sock_sendto(sock, bytes.fromhex(thunder), (resolved_ip, port))
                    thunder_sent = True
                    await asyncio.sleep(0.1)
                    prepare_ack = await build_packet(
                        0x68, (await layouts_from_mask(match_code))[1],
                        0, 2, None, 1, b"\x01\x00", udp_key_bytes
                    )
                    await loop.sock_sendto(sock, prepare_ack, (resolved_ip, port))
                    await asyncio.sleep(0.2)
                    await loop.sock_sendto(sock, bytes.fromhex(sharma), (resolved_ip, port))
                    sharma_sent = True
                    ack_state = "thunder_sharma_sent"
                    print_success(f"[MATCH #{match_index}] Thunder+Sharma sent!")
                except Exception as e:
                    print_error(f"[MATCH #{match_index}] send error: {e}")

        while not local_closed:
            if time.time() - match_start_time > MAX_MATCH_DURATION:
                break
            try:
                response, server_addr = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 65535), timeout=1.5
                )
                if response:
                    last_activity = time.time()
                    frame = await decode_packet(response, udp_key_bytes, match_code)
                    if frame:
                        ptype = await classify(frame)

                        if frame['cmd'] in [103, 107]:
                            print_success(
                                f"[MATCH #{match_index}] Completed (cmd {frame['cmd']})"
                            )
                            completed_cleanly = True
                            local_closed = True
                            continue

                        if frame['cmd'] == 101:
                            try:
                                ack_pkt = await build_packet(
                                    0x68, (await layouts_from_mask(match_code))[1],
                                    0, 2, None, 1, b"\x01\x00", udp_key_bytes
                                )
                                await loop.sock_sendto(sock, ack_pkt, server_addr)
                            except Exception:
                                pass
                            continue

                        if ptype in ["ACK", "PING", "HELLO", "JOIN_MATCH"]:
                            if ptype == "HELLO" and ack_state == "waiting_for_hello_reply":
                                typ, reply = await reply_for(
                                    frame, udp_key_bytes, match_code, ack_style="short"
                                )
                                if reply:
                                    await loop.sock_sendto(sock, reply, server_addr)
                                ack_state = "ack_sent_waiting"
                            elif ptype == "ACK":
                                if ack_state == "waiting_for_hello_reply":
                                    typ, reply = await reply_for(frame, udp_key_bytes, match_code)
                                    if reply:
                                        await loop.sock_sendto(sock, reply, server_addr)
                                    ack_state = "ready_to_send_thunder"
                                elif ack_state == "ack_sent_waiting":
                                    ack_state = "ready_to_send_thunder"
                                else:
                                    typ, reply = await reply_for(frame, udp_key_bytes, match_code)
                                    if reply:
                                        await loop.sock_sendto(sock, reply, server_addr)
                            elif ptype == "PING":
                                typ, reply = await reply_for(frame, udp_key_bytes, match_code)
                                if reply:
                                    await loop.sock_sendto(sock, reply, server_addr)
                            elif ptype == "JOIN_MATCH" and not join_match_received:
                                typ, reply = await reply_for(frame, udp_key_bytes, match_code)
                                if reply:
                                    await loop.sock_sendto(sock, reply, server_addr)
                                    join_match_received = True
            except asyncio.TimeoutError:
                if ack_state == "ready_to_send_thunder" and not thunder_sent:
                    await send_thunder_sharma_inline()
                elif ack_state == "waiting_for_hello_reply":
                    if (time.time() - last_activity) > MAX_IDLE_BEFORE_HELLO_RESEND:
                        try:
                            pkt = await build_hello_packet(
                                f"{account_id}_2585", udp_key_bytes, match_code
                            )
                            await loop.sock_sendto(sock, bytes.fromhex(pkt), (resolved_ip, port))
                        except Exception:
                            pass
                        last_activity = time.time()
                    if (time.time() - match_start_time) > 25.0:
                        print_warning(f"[MATCH #{match_index}] Handshake timeout")
                        break
                elif ack_state == "thunder_sharma_sent":
                    if (time.time() - last_activity) > MATCH_IDLE_TIMEOUT:
                        print_success(f"[MATCH #{match_index}] Finished naturally")
                        completed_cleanly = True
                        break
                continue
            except BlockingIOError:
                await asyncio.sleep(0.05)
            except OSError:
                await asyncio.sleep(0.5)
                continue
            except Exception:
                await asyncio.sleep(0.5)
                continue

            if ack_state == "ready_to_send_thunder" and not thunder_sent:
                await send_thunder_sharma_inline()

        return f"match #{match_index} finished"
    except Exception as e:
        print_error(f"[MATCH #{match_index}] error: {e}")
        return f"match #{match_index} error"
    finally:
        if completed_cleanly:
            try:
                bot_state.increment_match(uid_str)
            except Exception:
                pass
        ping_stop.set()
        if ping_task:
            ping_task.cancel()
            try:
                await ping_task
            except asyncio.CancelledError:
                pass
        if sock:
            try:
                sock.close()
            except Exception:
                pass
        remaining = await _dec_match(uid_str)
        total = await _get_total_match_count()
        print_info(
            f"[MATCH #{match_index}] Closed. "
            f"UID active: {remaining} | Total active: {total}"
        )
        try:
            bot_state.update_status(uid_str, "IN_MATCH" if remaining > 0 else "ONLINE", remaining)
        except Exception:
            pass


# ============================================================
# 🔥 functional_lone_wolf — TRUE Parallel + Smart Cache + DNS
# ============================================================
async def functional_lone_wolf(addrs, starter_packet, account_region, client_version,
                                key, iv, account_id="", account_data=None,
                                max_reconnects=10):
    reconnects = 0
    ip, port = addrs.split(":")
    play_matches: List[asyncio.Task] = []
    no_response_count = 0
    search_attempts = 0
    last_start_time = 0.0
    uid_str = str(account_id)

    consecutive_parse_failures = 0

    current_token = starter_packet
    current_key = key
    current_iv = iv
    current_account_data = account_data

    try:
        while True:
            writer = None
            try:
                if current_account_data:
                    fresh = None
                    if current_account_data.get('auth_type') == 'guest' and current_account_data.get('auth_uid'):
                        fresh = cache_get(str(current_account_data['auth_uid']))
                    elif current_account_data.get('auth_type') == 'token' and current_account_data.get('auth_token'):
                        fresh = cache_get(f"tok_{current_account_data['auth_token'][:20]}")

                    if fresh:
                        current_account_data = fresh
                        current_key = fresh['aes_ak']
                        current_iv = fresh['iv_i']
                        current_token = await build_tcp_startup_packet(
                            fresh['account_id'],
                            fresh['token'],
                            fresh['server_time'],
                            current_key,
                            current_iv,
                            region=fresh.get('region', account_region),
                            typ='OnLine'
                        )
                    else:
                        print_warning(f"[FUNCTIONAL] Cache miss for {uid_str} → re-login needed")
                        try:
                            if current_account_data.get('auth_uid'):
                                cache_invalidate(str(current_account_data['auth_uid']))
                            if current_account_data.get('auth_token'):
                                cache_invalidate(f"tok_{current_account_data['auth_token'][:20]}")
                        except Exception:
                            pass
                        raise ConnectionError("Cache expired, triggering fresh login")

                resolved_ip = await resolve_host_cloudflare(ip)
                reader, writer = await asyncio.open_connection(resolved_ip, int(port))
                
                raw_sock = writer.get_extra_info('socket')
                if raw_sock:
                    optimize_tcp_socket(raw_sock)
                
                writer.write(bytes.fromhex(current_token))
                await writer.drain()

                # Send initial keepalive pulse right after connecting in OB55.
                # Use the same lock region that StartMatch will use.
                try:
                    ka_region = str((current_account_data or {}).get('region') or account_region or "BD").upper()
                    init_ka = await send_keep_alive(ka_region)
                    if init_ka and writer and not writer.is_closing():
                        writer.write(init_ka)
                        await asyncio.wait_for(writer.drain(), timeout=3)
                except Exception:
                    pass

                print_success(f"[FUNCTIONAL] TCP Gateway Connected for UID: {uid_str} (DNS: {resolved_ip})")
                reconnects = 0
                no_response_count = 0
                last_start_time = 0.0

                def effective_region() -> str:
                    region = account_region
                    if current_account_data:
                        region = current_account_data.get('region') or region
                    return str(region or "BD").upper()

                async def send_start_match():
                    nonlocal search_attempts, last_start_time
                    search_attempts += 1
                    current_region = effective_region()
                    print_info(
                        f"[LONE WOLF] Sending StartMatch #{search_attempts} "
                        f"account_region={current_region}, matchmaking_region={MATCHMAKING_REGION}"
                    )
                    try:
                        await asyncio.sleep(random.uniform(0.3, 0.6))
                        sent_len, gateway_prefix, matchmaking_region = await start_game_lone_wolf(
                            MATCHMAKING_REGION, client_version, writer,
                            current_key, current_iv
                        )
                        print_success(
                            f"[LONE WOLF] StartMatch packet sent "
                            f"(account_region={current_region}, matchmaking_region={matchmaking_region}, "
                            f"prefix={gateway_prefix}, encrypted={sent_len} bytes)"
                        )
                        active = await _get_match_count(uid_str)
                        try:
                            bot_state.update_status(uid_str, "SEARCHING", active)
                        except Exception:
                            pass
                    except Exception as e:
                        print_error(f"start_game_lone_wolf error: {e}")
                    last_start_time = asyncio.get_running_loop().time()

                await send_start_match()

                while True:
                    play_matches[:] = [m for m in play_matches if not m.done()]

                    active_count = await _get_match_count(uid_str)
                    try:
                        bot_state.update_status(
                            uid_str,
                            "ONLINE" if active_count == 0 else "IN_MATCH",
                            active_count
                        )
                    except Exception:
                        pass

                    now = asyncio.get_running_loop().time()
                    if now - last_start_time >= START_MATCH_INTERVAL:
                        await send_start_match()

                    try:
                        data = await asyncio.wait_for(reader.read(8192), timeout=0.5)
                    except asyncio.TimeoutError:
                        no_response_count += 1
                        if no_response_count > 80:
                            print_warning(f"[FUNCTIONAL] Gateway silent ({uid_str}). Reconnecting...")
                            raise ConnectionError("Gateway idle timeout")
                        continue

                    if not data:
                        raise ConnectionError("Connection closed by server")

                    hex_data = data.hex()
                    packet_length = len(data)
                    no_response_count = 0

                    if hex_data.startswith("0300") and 10 < packet_length < 30:
                        print_info("Match starting, please wait...")
                        continue

                    if hex_data.startswith("0300") and packet_length >= 300:
                        print_colored("=" * 60, Colors.GREEN)
                        print_colored(f"MATCH FOUND! Loading...", Colors.GREEN)
                        print_colored("=" * 60, Colors.GREEN)

                        try:
                            res = json.loads(await decode_protobuf(hex_data[10:]))
                            token = None
                            udp_key = None
                            match_code = None
                            server_ip_port = None
                            match_account_id = None
                            block_val = None

                            if '42' in res and 'data' in res['42']:
                                match_code = res['42']['data']
                            if '5' in res and 'data' in res['5']:
                                res_field5 = res['5']['data']
                                server_ip_port = res_field5.get('2', {}).get('data')
                                udp_key = res_field5.get('3', {}).get('data')
                                token = res_field5.get('4', {}).get('data')
                                if '42' in res_field5:
                                    match_code = res_field5['42']['data']
                            if '1' in res and 'data' in res['1']:
                                match_account_id = res['1']['data']
                            if '5' in res and 'data' in res['5']:
                                block_val = res['5']['data'].get('1', {}).get('data')

                            effective_acc_id = match_account_id or account_id or "BD_BOT"

                            if token and udp_key and match_code and server_ip_port:
                                acc_tok = ""
                                if current_account_data:
                                    acc_tok = current_account_data.get('access_token', '') or ""
                                match_region = effective_region()
                                thunder, sharma = await build_match_startup_packets(
                                    token, udp_key, match_code, effective_acc_id, block_val or 0,
                                    server_ip=server_ip_port,
                                    region=match_region,
                                    client_version=client_version,
                                    access_token=acc_tok
                                )

                                match_index = await _inc_match(uid_str)
                                total = await _get_total_match_count()
                                print_colored(
                                    f"🚀 [MATCH #{match_index}] UDP starting → {server_ip_port} (background)",
                                    Colors.CYAN
                                )
                                print_success(
                                    f"[FUNCTIONAL] UDP task started. "
                                    f"UID active: {match_index} | Total: {total}"
                                )

                                new_match = asyncio.create_task(
                                    play_game(
                                        server_ip_port,
                                        thunder,
                                        sharma,
                                        udp_key,
                                        match_code,
                                        effective_acc_id,
                                        match_region,
                                        client_version,
                                        current_key,
                                        current_iv,
                                        match_index=match_index
                                    )
                                )
                                play_matches.append(new_match)

                                consecutive_parse_failures = 0

                                try:
                                    writer.close()
                                    await writer.wait_closed()
                                except Exception:
                                    pass

                                print_info(
                                    f"[OFFLINE] {NEW_MATCH_DELAY}s offline → "
                                    f"reload token → new StartMatch"
                                )
                                await asyncio.sleep(NEW_MATCH_DELAY)
                                reconnects = 0
                                break 

                            else:
                                consecutive_parse_failures += 1
                                print_warning(
                                    f"[FUNCTIONAL] Non-match big packet "
                                    f"(#{consecutive_parse_failures}/{MAX_CONSECUTIVE_PARSE_FAILURES}) "
                                    f"→ reconnecting"
                                )

                                if consecutive_parse_failures >= MAX_CONSECUTIVE_PARSE_FAILURES:
                                    print_error(
                                        f"[FUNCTIONAL] {MAX_CONSECUTIVE_PARSE_FAILURES}x parse failures "
                                        f"→ invalidating cache for fresh login"
                                    )
                                    if current_account_data:
                                        try:
                                            if current_account_data.get('auth_uid'):
                                                cache_invalidate(str(current_account_data['auth_uid']))
                                            if current_account_data.get('auth_token'):
                                                cache_invalidate(f"tok_{current_account_data['auth_token'][:20]}")
                                        except Exception:
                                            pass
                                    consecutive_parse_failures = 0

                                try:
                                    writer.close()
                                    await writer.wait_closed()
                                except Exception:
                                    pass
                                await asyncio.sleep(NON_MATCH_RECONNECT_DELAY)
                                break

                        except Exception as e:
                            print_error(f"[FUNCTIONAL] Match packet error: {e}")
                            consecutive_parse_failures += 1
                            if consecutive_parse_failures >= MAX_CONSECUTIVE_PARSE_FAILURES:
                                if current_account_data:
                                    try:
                                        if current_account_data.get('auth_uid'):
                                            cache_invalidate(str(current_account_data['auth_uid']))
                                        if current_account_data.get('auth_token'):
                                            cache_invalidate(f"tok_{current_account_data['auth_token'][:20]}")
                                    except Exception:
                                        pass
                                consecutive_parse_failures = 0
                            try:
                                writer.close()
                                await writer.wait_closed()
                            except Exception:
                                pass
                            await asyncio.sleep(NON_MATCH_RECONNECT_DELAY)
                            break

                    if 30 <= packet_length <= 40:
                        continue

            except asyncio.CancelledError:
                print_warning(f"[FUNCTIONAL] Cancelled — cancelling {len(play_matches)} UDP matches")
                for m in play_matches:
                    if not m.done():
                        m.cancel()
                if play_matches:
                    await asyncio.gather(*play_matches, return_exceptions=True)
                play_matches.clear()
                raise
            except Exception as e:
                print_error(f"[FUNCTIONAL] TCP state ({uid_str}): {e}")

                play_matches[:] = [m for m in play_matches if not m.done()]

                if writer:
                    try:
                        writer.close()
                        await writer.wait_closed()
                    except Exception:
                        pass

                if "Cache expired" in str(e):
                    print_warning(f"[FUNCTIONAL] Triggering re-login for {uid_str}")
                    break

                reconnects += 1
                if reconnects > max_reconnects:
                    print_error("[FUNCTIONAL] Max reconnects reached, retrying...")
                    reconnects = 0
                    await asyncio.sleep(3)
                    continue

                await asyncio.sleep(min(reconnects, 2))

    except asyncio.CancelledError:
        print_warning(f"[FUNCTIONAL] Outer cancelled. {len(play_matches)} UDP matches still running.")
        for m in play_matches:
            if not m.done():
                m.cancel()
        if play_matches:
            await asyncio.gather(*play_matches, return_exceptions=True)
        play_matches.clear()
        raise


async def informational(addrs, starter_packet, key, iv, region="BD", max_reconnects=3):
    reconnects = 0
    ip, port = addrs.split(":")
    while True:
        writer = None
        ping_task = None
        try:
            resolved_ip = await resolve_host_cloudflare(ip)
            reader, writer = await asyncio.open_connection(resolved_ip, int(port))
            
            raw_sock = writer.get_extra_info('socket')
            if raw_sock:
                optimize_tcp_socket(raw_sock)
                
            writer.write(bytes.fromhex(starter_packet))
            await writer.drain()
            reconnects = 0

            # Initial keepalive right after connecting
            try:
                init_ka = await send_keep_alive(region)
                if init_ka and writer and not writer.is_closing():
                    writer.write(init_ka)
                    await asyncio.wait_for(writer.drain(), timeout=3)
            except Exception:
                pass

            async def info_keepalive():
                ka_bytes = await send_keep_alive(region)
                while True:
                    await asyncio.sleep(5)
                    try:
                        if writer and not writer.is_closing():
                            writer.write(ka_bytes)
                            await writer.drain()
                    except Exception:
                        break

            ping_task = asyncio.create_task(info_keepalive())

            while True:
                data = await reader.read(8192)
                if not data:
                    raise ConnectionError("Connection closed")
        except asyncio.CancelledError:
            if ping_task:
                ping_task.cancel()
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
            raise
        except Exception:
            if ping_task:
                ping_task.cancel()
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
            reconnects += 1
            if reconnects > max_reconnects:
                await asyncio.sleep(3)
                reconnects = 0
            else:
                await asyncio.sleep(1)


# ==================== ACCOUNT PROCESSORS ====================

def _track_worker_aliases(task: Optional[asyncio.Task], *aliases: Any):
    """Map every useful user/account id to the same running worker task."""
    if task is None:
        return
    for alias in aliases:
        if alias is None:
            continue
        key = str(alias).strip()
        if key:
            bot_state.account_workers[key] = task


def _forget_worker_aliases(task: Optional[asyncio.Task]):
    """Remove stale aliases when a worker exits or is cancelled."""
    if task is None:
        return
    for key, worker in list(bot_state.account_workers.items()):
        if worker is task:
            bot_state.account_workers.pop(key, None)


def _register_credentials(account_data: Dict):
    try:
        acc_id = str(account_data['account_id'])
        bot_state.account_credentials[acc_id] = account_data
        if account_data.get('auth_uid'):
            bot_state.account_credentials[str(account_data['auth_uid'])] = account_data
        if account_data.get('auth_token'):
            auth_token = str(account_data['auth_token'])
            bot_state.account_credentials[auth_token] = account_data
            bot_state.account_credentials[auth_token[:10]] = account_data
            bot_state.account_credentials[f"tok_{auth_token[:20]}"] = account_data
    except Exception:
        pass


async def refresh_account_profile(account_data_or_uid: Any):
    try:
        if isinstance(account_data_or_uid, str):
            uid = str(account_data_or_uid)
            account_data = bot_state.account_credentials.get(uid)
        else:
            account_data = account_data_or_uid
            uid = str(account_data.get('account_id'))

        if not account_data:
            return

        url = account_data.get('server_url')
        token = account_data.get('token')
        release_version = account_data.get('release_version')
        payload = account_data.get('login_payload_data')

        if not (url and token and release_version and payload):
            return

        res = await send_getlogin(payload, url, token, release_version)
        if res:
            res_proto, dict_res = res
            level = int(get_proto_field(dict_res, 6, 1))
            exp = int(get_proto_field(dict_res, 7, 0))
            likes = int(get_proto_field(dict_res, 8, 0))
            nickname = res_proto.nickname or get_proto_field(dict_res, 4, "")

            acc_id = str(account_data['account_id'])
            if exp > 0:
                bot_state.update_exp(acc_id, exp, level)
            if likes > 0 and acc_id in bot_state.accounts:
                bot_state.accounts[acc_id]["likes"] = likes
            if nickname and acc_id in bot_state.accounts:
                bot_state.accounts[acc_id]["nickname"] = nickname
            print_info(f"[EXP-REFRESH] UID {acc_id} -> Level: {level}, EXP: {exp}")
    except Exception as e:
        print_error(f"refresh_account_profile error: {e}")


async def _majorlogin_with_fallbacks(open_id: str, access_token: str, platform: Any,
                                     client_version: str, release_version: str,
                                     server_url: str, device_info: Dict[str, Any],
                                     label: str) -> Tuple[Optional[Any], Optional[bytes]]:
    full_payload = await build_majorlogin_payload(open_id, access_token, platform, client_version, device_info)
    fallback_payload = await build_minimal_majorlogin_payload(open_id, access_token, platform)

    payloads = []
    if full_payload:
        payloads.append(("full", full_payload))
    if fallback_payload:
        payloads.append(("minimal", fallback_payload))

    for payload_name, payload in payloads:
        if payload_name != "full":
            print_warning(f"[LOGIN] Retrying MajorLogin for {label} with {payload_name} OB55 payload")
        majorlogin_response = await send_majorlogin(payload, release_version, server_url)
        if majorlogin_response:
            if payload_name != "full":
                print_success(f"[LOGIN] {payload_name} OB55 payload worked for {label}")
            return majorlogin_response, payload

    return None, None


async def process_account_uid_pass(uid: str, password: str) -> Optional[Dict]:
    cached = cache_get(uid)
    if cached:
        print_success(f"[CACHE HIT] UID {uid} loaded from token_cache.json (no login)")
        acc_id = str(cached['account_id'])
        bot_state.register_account(
            uid=acc_id,
            nickname=cached.get('nickname', f"Player_{acc_id}"),
            region=cached.get('region', 'BD'),
            level=cached.get('level', 1),
            exp=cached.get('exp', 0),
            likes=cached.get('likes', 0)
        )
        _register_credentials(cached)
        return cached

    print_info(f"[LOGIN] Full login for UID {uid}...")
    try:
        verconfig_res = await version_config()
        if verconfig_res is None:
            print_error(f"[LOGIN] Version configuration unavailable for UID {uid}")
            return None
        release_version, client_version, server_url = verconfig_res
        
        tokengrant_response = await get_access_token(uid, password)
        if tokengrant_response is None:
            print_error(f"[LOGIN] Guest token step failed for UID {uid}")
            return None
        open_id, access_token, platform = tokengrant_response
        
        # 🔥 1ta id 1ta Device Injection
        device_info = get_device_for_account(uid)
        
        majorlogin_response, login_payload_data = await _majorlogin_with_fallbacks(
            open_id, access_token, platform, client_version, release_version, server_url, device_info, uid
        )
        if majorlogin_response is None or not login_payload_data:
            print_error(f"[LOGIN] MajorLogin step failed for UID {uid}")
            return None
        getlogin_result = await send_getlogin(login_payload_data, majorlogin_response.url, majorlogin_response.token, release_version)
        if getlogin_result is None:
            print_error(f"[LOGIN] GetLoginData step failed for UID {uid}")
            return None
        res_proto, dict_res = getlogin_result

        acc_id = str(majorlogin_response.account_id)
        level = int(get_proto_field(dict_res, 6, 1))
        exp = int(get_proto_field(dict_res, 7, 0))
        likes = int(get_proto_field(dict_res, 8, 0))
        nickname = res_proto.nickname or get_proto_field(dict_res, 4, f"Player_{acc_id}")
        region = majorlogin_response.region or get_proto_field(dict_res, 3, "BD")

        bot_state.register_account(uid=acc_id, nickname=nickname, region=region, level=level, exp=exp, likes=likes)

        account_data = {
            'account_id': majorlogin_response.account_id,
            'nickname': nickname,
            'region': region,
            'level': level,
            'exp': exp,
            'likes': likes,
            'open_id': open_id,
            'access_token': access_token,
            'platform': str(platform),
            'token': majorlogin_response.token,
            'server_time': majorlogin_response.server_time,
            'aes_ak': majorlogin_response.aes_ak,
            'iv_i': majorlogin_response.iv_i,
            'functional_addrs': res_proto.functional_addrs or get_proto_field(dict_res, 14),
            'informational_addrs': res_proto.informational_addrs or get_proto_field(dict_res, 32),
            'release_version': release_version,
            'client_version': client_version,
            'server_url': majorlogin_response.url,
            'login_payload_data': login_payload_data,
            'auth_type': 'guest',
            'auth_uid': uid,
            'auth_password': password
        }
        _register_credentials(account_data)
        cache_set(uid, account_data)
        return account_data
    except Exception as e:
        print_error(f"process_account_uid_pass error: {e}")
        return None


async def process_account_token(access_token: str) -> Optional[Dict]:
    cache_key = f"tok_{access_token[:20]}"
    cached = cache_get(cache_key)
    if cached:
        print_success(f"[CACHE HIT] Token {access_token[:10]}... loaded from cache")
        acc_id = str(cached['account_id'])
        bot_state.register_account(
            uid=acc_id,
            nickname=cached.get('nickname', f"Player_{acc_id}"),
            region=cached.get('region', 'BD'),
            level=cached.get('level', 1),
            exp=cached.get('exp', 0),
            likes=cached.get('likes', 0)
        )
        _register_credentials(cached)
        return cached

    print_info("[LOGIN] Full login with Access Token...")
    try:
        verconfig_res = await version_config()
        if verconfig_res is None:
            print_error("[LOGIN] Version configuration unavailable for access-token login")
            return None
        release_version, client_version, server_url = verconfig_res

        inspect_result = await inspect_access_token(access_token)
        if inspect_result is None:
            return None
        open_id, platform = inspect_result

        # 🔥 1ta id 1ta Device Injection (using unique open_id as the key)
        device_info = get_device_for_account(open_id)

        majorlogin_response, login_payload_data = await _majorlogin_with_fallbacks(
            open_id, access_token, platform, client_version, release_version, server_url, device_info, "access-token login"
        )
        if majorlogin_response is None or not login_payload_data:
            print_error("[LOGIN] MajorLogin step failed for access-token login")
            return None

        getlogin_result = await send_getlogin(
            login_payload_data,
            majorlogin_response.url,
            majorlogin_response.token,
            release_version
        )
        if getlogin_result is None:
            print_error("[LOGIN] GetLoginData step failed for access-token login")
            return None

        res_proto, dict_res = getlogin_result
        acc_id = str(majorlogin_response.account_id)
        level = int(get_proto_field(dict_res, 6, 1))
        exp = int(get_proto_field(dict_res, 7, 0))
        likes = int(get_proto_field(dict_res, 8, 0))
        nickname = res_proto.nickname or get_proto_field(dict_res, 4, f"Player_{acc_id}")
        region = majorlogin_response.region or get_proto_field(dict_res, 3, "BD")

        bot_state.register_account(uid=acc_id, nickname=nickname, region=region, level=level, exp=exp, likes=likes)

        account_data = {
            'account_id': majorlogin_response.account_id,
            'nickname': nickname,
            'region': region,
            'level': level,
            'exp': exp,
            'likes': likes,
            'open_id': open_id,
            'access_token': access_token,
            'platform': str(platform),
            'token': majorlogin_response.token,
            'server_time': majorlogin_response.server_time,
            'aes_ak': majorlogin_response.aes_ak,
            'iv_i': majorlogin_response.iv_i,
            'functional_addrs': res_proto.functional_addrs or get_proto_field(dict_res, 14),
            'informational_addrs': res_proto.informational_addrs or get_proto_field(dict_res, 32),
            'release_version': release_version,
            'client_version': client_version,
            'server_url': majorlogin_response.url,
            'login_payload_data': login_payload_data,
            'platform': platform,
            'auth_type': 'token',
            'auth_token': access_token
        }
        _register_credentials(account_data)
        cache_set(cache_key, account_data)
        return account_data
    except Exception as e:
        print_error(f"process_account_token error: {e}")
        return None


async def run_account_worker(account_data: Dict, label: str):
    acc_id = str(account_data['account_id'])
    informational_task = None
    exp_task = None
    functional_task = None
    try:
        reg = account_data.get('region', 'BD')
        functional_addrs = str(account_data.get('functional_addrs') or '').strip()
        informational_addrs = str(account_data.get('informational_addrs') or '').strip()
        if ':' not in functional_addrs:
            raise ConnectionError(f"Missing functional gateway address for {label}")

        bot_state.update_status(acc_id, "ONLINE", 0)

        tcp_packet_online = await build_tcp_startup_packet(
            account_data['account_id'],
            account_data['token'],
            account_data['server_time'],
            account_data['aes_ak'],
            account_data['iv_i'],
            region=reg,
            typ='OnLine'
        )

        tcp_packet_chat = None
        if ':' in informational_addrs:
            tcp_packet_chat = await build_tcp_startup_packet(
                account_data['account_id'],
                account_data['token'],
                account_data['server_time'],
                account_data['aes_ak'],
                account_data['iv_i'],
                region=reg,
                typ='ChaT'
            )
            informational_task = asyncio.create_task(
                informational(
                    informational_addrs,
                    tcp_packet_chat,
                    account_data['aes_ak'],
                    account_data['iv_i'],
                    region=reg
                )
            )
        else:
            print_warning(f"[INFO] Missing informational gateway for {label}; continuing without chat socket")

        async def exp_refresher():
            while True:
                await asyncio.sleep(90)
                fresh = bot_state.account_credentials.get(acc_id)
                if fresh:
                    await refresh_account_profile(fresh)

        exp_task = asyncio.create_task(exp_refresher())

        functional_task = asyncio.create_task(
            functional_lone_wolf(
                functional_addrs,
                tcp_packet_online,
                account_data['region'],
                account_data['client_version'],
                account_data['aes_ak'],
                account_data['iv_i'],
                account_id=acc_id,
                account_data=account_data
            )
        )

        await functional_task

    except asyncio.CancelledError:
        try:
            bot_state.update_status(acc_id, "OFFLINE", 0)
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            bot_state.update_status(acc_id, "ERROR", 0)
        except Exception:
            pass
        print_error(f"run_account_worker error for {label}: {e}")
    finally:
        for t in (informational_task, exp_task, functional_task):
            if t and not t.done():
                t.cancel()
        for t in (informational_task, exp_task, functional_task):
            if t:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass


async def account_loop_guest(uid: str, password: str):
    current_task = asyncio.current_task()
    _track_worker_aliases(current_task, uid)
    try:
        while True:
            try:
                print_info(f"[LOGIN] Starting login for Guest UID: {uid}...")
                try:
                    bot_state.update_status(str(uid), "CONNECTING")
                except Exception:
                    pass
                account_data = await process_account_uid_pass(uid, password)
                if not account_data:
                    print_error(f"Login failed for UID: {uid}. Retrying in 15 seconds...")
                    try:
                        bot_state.update_status(str(uid), "ERROR")
                    except Exception:
                        pass
                    await asyncio.sleep(15)
                    continue

                acc_id = str(account_data.get('account_id', uid))
                if acc_id != str(uid):
                    bot_state.remove_account_state(str(uid))
                _track_worker_aliases(current_task, uid, acc_id, account_data.get('auth_uid'))
                await run_account_worker(account_data, uid)
                print_warning(f"Session finished for {uid}. Reconnecting in 3s...")
                await asyncio.sleep(3)
            except asyncio.CancelledError:
                print_warning(f"Worker for {uid} stopped.")
                try:
                    bot_state.update_status(str(uid), "OFFLINE")
                    if uid in bot_state.account_credentials:
                        acc_id = str(bot_state.account_credentials[uid].get('account_id', ''))
                        if acc_id:
                            bot_state.update_status(acc_id, "OFFLINE")
                except Exception:
                    pass
                break
            except Exception as e:
                print_error(f"Error for UID {uid}: {e}. Retrying in 10s...")
                await asyncio.sleep(10)
    finally:
        _forget_worker_aliases(current_task)


async def account_loop_token(token: str):
    token_label = token[:10]
    cache_key = f"tok_{token[:20]}"
    current_task = asyncio.current_task()
    _track_worker_aliases(current_task, token_label, cache_key)
    try:
        while True:
            try:
                print_info("[LOGIN] Starting login with Access Token...")
                account_data = await process_account_token(token)
                if not account_data:
                    print_error("Login failed for Token. Retrying in 15 seconds...")
                    await asyncio.sleep(15)
                    continue

                acc_id = str(account_data['account_id'])
                _track_worker_aliases(current_task, token_label, cache_key, acc_id)
                await run_account_worker(account_data, acc_id)
                print_warning("Token session finished. Reconnecting in 3s...")
                await asyncio.sleep(3)
            except asyncio.CancelledError:
                print_warning(f"Worker for token {token_label} stopped.")
                try:
                    account_data = bot_state.account_credentials.get(cache_key) or bot_state.account_credentials.get(token_label)
                    if account_data and account_data.get('account_id'):
                        bot_state.update_status(str(account_data['account_id']), "OFFLINE")
                except Exception:
                    pass
                break
            except Exception as e:
                print_error(f"Token error: {e}. Retrying in 10s...")
                await asyncio.sleep(10)
    finally:
        _forget_worker_aliases(current_task)


# ==================== ACCOUNTS LOADER ====================

def load_accounts():
    accounts = []
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    accounts = data
        except Exception as e:
            print_error(f"Could not load {ACCOUNTS_FILE}: {e}")

    if not accounts and FALLBACK_UID and FALLBACK_PASSWORD:
        accounts.append({"uid": FALLBACK_UID, "password": FALLBACK_PASSWORD})

    return accounts


# ==================== MAIN ====================

async def main():
    print_colored("=" * 60, Colors.CYAN)
    print_colored("    TEAM 84FF - FreeFire Level Up Bot (Web Dashboard Mode)", Colors.GREEN)
    print_colored("   Persistent Device ID + TRUE Parallel + Smart DNS", Colors.WHITE)
    print_colored("=" * 60, Colors.CYAN)
    print_info(f"Start Match Interval: {START_MATCH_INTERVAL}s")
    print_info(f"Offline Wait: {NEW_MATCH_DELAY}s (after match found)")
    print_info(f"Non-match Reconnect: {NON_MATCH_RECONNECT_DELAY}s")
    print_info(f"Cache Invalidation Threshold: {MAX_CONSECUTIVE_PARSE_FAILURES}x")
    print_info(f"Parallel Matches: UNLIMITED (background)")
    print_info(f"Cache TTL: {TOKEN_CACHE_TTL}s ({TOKEN_CACHE_TTL//60} min)")
    print_info(f"Priority Regions: {PRIORITY_REGIONS}")
    print_info("Device System: 1 ID = 1 Persistent Device ID (devices.json)")
    if FF_PROXY:
        print_info("Network Proxy: enabled via FF_PROXY")
    print_colored("=" * 60, Colors.CYAN)

    dashboard_runner = None
    try:
        dashboard_runner = await start_web_dashboard(host=WEB_HOST, port=WEB_PORT)
        print_success(f"Web Dashboard live at http://localhost:{WEB_PORT}")
    except Exception as e:
        print_error(f"Could not start web dashboard: {e}")

    async def on_account_added_handler(data):
        if "token" in data and data["token"]:
            t = str(data["token"]).strip()
            token_key = f"tok_{t[:20]}"
            existing = bot_state.account_workers.get(token_key) or bot_state.account_workers.get(t[:10])
            if existing and not existing.done():
                print_warning(f"Worker already running for token {t[:10]}...")
                return
            task = asyncio.create_task(account_loop_token(t))
            _track_worker_aliases(task, token_key, t[:10])
        elif "uid" in data and "password" in data:
            u = str(data["uid"]).strip()
            p = str(data["password"]).strip()
            existing = bot_state.account_workers.get(u)
            if existing and not existing.done():
                print_warning(f"Worker already running for UID {u}")
                return
            task = asyncio.create_task(account_loop_guest(u, p))
            _track_worker_aliases(task, u)

    async def on_refresh_account_handler(uid):
        await refresh_account_profile(uid)

    bot_state.refresh_callbacks["on_account_added"] = on_account_added_handler
    bot_state.refresh_callbacks["on_refresh_account"] = on_refresh_account_handler

    accounts = load_accounts()

    if not accounts:
        print_warning(f"No accounts found in {ACCOUNTS_FILE}! Add accounts from Web Dashboard.")
        print_warning(f"Open: http://localhost:{WEB_PORT}")

    for acc in accounts:
        if "token" in acc and acc["token"]:
            token = str(acc["token"])
            task = asyncio.create_task(account_loop_token(token))
            _track_worker_aliases(task, f"tok_{token[:20]}", token[:10])
        elif "uid" in acc and "password" in acc and acc["uid"]:
            u = str(acc["uid"])
            task = asyncio.create_task(account_loop_guest(u, acc["password"]))
            _track_worker_aliases(task, u)

    try:
        while True:
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        print_warning("\n[STOP] Shutting down all accounts...")
        tasks = list({task for task in bot_state.account_workers.values()})
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if dashboard_runner is not None:
            await dashboard_runner.cleanup()
        await client.aclose()
        print_success("All sessions cleanly closed.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print_warning("\nProgram stopped by user.")
