# -*- coding: utf-8 -*-
"""mercari-proxy 自签 HTTPS 证书（复用 mitmproxy 自带的 cryptography 依赖）。

局域网 IP / 域名访问必须走 https，否则浏览器不是安全上下文，crypto.subtle 不可用，
煤炉 DPoP 签不出 → 商品刷不出。证书仅用于本机/内网自用，浏览器会提示不受信任，点继续即可。
"""
from __future__ import annotations

import datetime
import ipaddress
import os
import socket
from typing import Iterable, List, Optional, Tuple

DATA_DIRNAME = "mercari_proxy"


def _backend_root() -> str:
    # backend/src/mercari_proxy/cert.py → 上溯三级到 backend/
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def cert_dir() -> str:
    override = (os.environ.get("MERCARI_PROXY_CERT_DIR") or "").strip()
    root = os.path.abspath(override) if override else os.path.join(_backend_root(), "data", DATA_DIRNAME)
    os.makedirs(root, exist_ok=True)
    return root


def _local_ips() -> List[str]:
    ips = {"127.0.0.1"}
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None):
            ip = info[4][0]
            if ":" not in ip:  # 仅 IPv4
                ips.add(ip)
    except Exception:  # noqa: BLE001
        pass
    return sorted(ips)


def ensure_cert(
    target_dir: Optional[str] = None,
    *,
    extra_hosts: Iterable[str] = (),
    force: bool = False,
    common_name: str = "mercari-proxy",
    days: int = 3650,
) -> Tuple[Optional[str], Optional[str]]:
    """确保自签证书存在，返回 (cert_path, key_path)；cryptography 不可用时返回 (None, None)。

    target_dir 指定证书存放目录（如打包后 exe 同级根目录）；不传则用默认 data/mercari_proxy。
    extra_hosts 追加进 SAN 的域名 / IP（本机名与本机 IPv4 总是包含）；force=True 时即使已有证书也重新生成。
    days 为有效期；iOS / macOS 拒绝超过 825 天、或不带 serverAuth EKU 的 TLS 证书（连「继续访问」都不给），
    手机要访问的证书必须把 days 压到 825 以内。
    """
    d = os.path.abspath(target_dir) if target_dir else cert_dir()
    os.makedirs(d, exist_ok=True)
    cert_path = os.path.join(d, "cert.pem")
    key_path = os.path.join(d, "key.pem")
    if not force and os.path.isfile(cert_path) and os.path.isfile(key_path):
        return cert_path, key_path

    try:
        from cryptography import x509
        from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        return None, None

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])

    san: List[x509.GeneralName] = [x509.DNSName("localhost")]
    try:
        san.append(x509.DNSName(socket.gethostname()))
    except Exception:  # noqa: BLE001
        pass
    for ip in _local_ips():
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            pass
    for h in extra_hosts:
        h = (h or "").strip()
        if not h:
            continue
        try:
            entry: x509.GeneralName = x509.IPAddress(ipaddress.ip_address(h))
        except ValueError:
            entry = x509.DNSName(h)
        if entry not in san:
            san.append(entry)

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        # CA:TRUE 与 ``openssl req -x509`` 的默认一致：iPhone 只有装的是 CA 证书，才会出现在
        # 「证书信任设置」里让人手动开启完全信任；自签叶子证书同时充当自己的根，Chrome 也接受。
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=False, key_encipherment=True,
                data_encipherment=False, key_agreement=False, key_cert_sign=True,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )

    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path
