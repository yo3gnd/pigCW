import logging, os, subprocess, tomllib
from pathlib import Path


L = logging.getLogger(__name__)

BOOT_WIFI_FILES = [
    Path("/boot/firmware/pigcw-wifi.toml"),
    Path("/boot/pigcw-wifi.toml"),
]

NMCLI = "/usr/bin/nmcli"
SUDO = "/usr/bin/sudo"
CON_NAME = "pigcw-wifi"


def _run(xs):
    if os.geteuid() != 0:
        if not Path(SUDO).exists():
            L.warning("wifi no sudo")
            return None
        xs = [SUDO, "-n"] + xs

    try:
        return subprocess.run(
            xs,
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception as e:
        L.warning("wifi run fail %s", e)
        return None


def _wifi_file():
    for p in BOOT_WIFI_FILES:
        if p.exists():
            return p
    return None


def _wifi_dev():
    p = Path("/sys/class/net/wlan0")
    if p.exists():
        return "wlan0"

    for p in sorted(Path("/sys/class/net").glob("wl*")):
        return p.name

    return None


def _wifi_cfg():
    p = _wifi_file()
    if not p:
        return None

    try:
        with open(p, "rb") as f:
            z = tomllib.load(f)
    except Exception as e:
        L.warning("wifi toml fail %s", e)
        return None

    ssid = z.get("ssid")
    password = z.get("password")

    if not isinstance(ssid, str) or not isinstance(password, str):
        L.warning("wifi toml need ssid/password")
        return None

    if not ssid or not password:
        L.warning("wifi toml empty")
        return None

    if any(x in ssid for x in "\r\n\0") or any(x in password for x in "\r\n\0"):
        L.warning("wifi toml bad chars")
        return None

    return {
        "ssid": ssid,
        "password": password,
        "path": str(p),
    }


def maybe_apply_boot_wifi():
    z = _wifi_cfg()
    if not z:
        return False

    if not Path(NMCLI).exists():
        L.warning("wifi no nmcli")
        return False

    dev = _wifi_dev()
    if not dev:
        L.warning("wifi no dev")
        return False

    r = _run([NMCLI, "-g", "NAME", "connection", "show", CON_NAME])
    if not r or r.returncode != 0:
        r = _run([
            NMCLI, "connection", "add",
            "type", "wifi",
            "ifname", dev,
            "con-name", CON_NAME,
            "ssid", z["ssid"],
        ])
        if not r or r.returncode != 0:
            L.warning("wifi add fail %s", r.stderr.strip() if r else "")
            return False

    r = _run([
        NMCLI, "connection", "modify", CON_NAME,
        "connection.interface-name", dev,
        "connection.autoconnect", "yes",
        "connection.autoconnect-priority", "100",
        "wifi.ssid", z["ssid"],
        "wifi-sec.key-mgmt", "wpa-psk",
        "wifi-sec.psk", z["password"],
    ])
    if not r or r.returncode != 0:
        L.warning("wifi mod fail %s", r.stderr.strip() if r else "")
        return False

    r = _run([NMCLI, "connection", "up", CON_NAME, "ifname", dev])
    if not r or r.returncode != 0:
        L.warning("wifi up fail %s", r.stderr.strip() if r else "")
        return False

    L.info("wifi from %s on %s", z["path"], dev)
    return True
