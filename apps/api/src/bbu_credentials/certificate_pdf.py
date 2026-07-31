"""PDF renderer for BBU professional credentials using Anna's artwork."""
from __future__ import annotations

from datetime import date
from pathlib import Path
import unicodedata
import zlib

from PIL import Image
import segno


PAGE_WIDTH = 792
PAGE_HEIGHT = 612
NAVY = (0.067, 0.239, 0.365)
SKY = (0.427, 0.627, 0.859)
ICE = (0.922, 0.969, 1.0)
INK = (0.105, 0.153, 0.2)
MUTED = (0.42, 0.435, 0.475)
TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "cert_templates"


def _ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return normalized.encode("ascii", "ignore").decode("ascii")


def _escape(value: str) -> str:
    return _ascii(value).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _rgb(color: tuple[float, float, float], *, stroke: bool = False) -> str:
    operator = "RG" if stroke else "rg"
    return f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} {operator}"


def _fit_font(text: str, maximum: float, width: float, factor: float = 0.53) -> float:
    if not text:
        return maximum
    return max(15.0, min(maximum, width / (len(_ascii(text)) * factor)))


def _center_x(text: str, size: float, factor: float = 0.53) -> float:
    estimated_width = len(_ascii(text)) * size * factor
    return max(48.0, (PAGE_WIDTH - estimated_width) / 2)


def _text(
    commands: list[str],
    value: str,
    *,
    x: float,
    y: float,
    size: float,
    font: str = "F1",
    color: tuple[float, float, float] = INK,
) -> None:
    commands.extend(
        [
            _rgb(color),
            f"BT /{font} {size:.2f} Tf {x:.2f} {y:.2f} Td ({_escape(value)}) Tj ET",
        ]
    )


def _centered_text(
    commands: list[str],
    value: str,
    *,
    y: float,
    size: float,
    font: str = "F1",
    color: tuple[float, float, float] = INK,
    factor: float = 0.53,
) -> None:
    _text(
        commands,
        value,
        x=_center_x(value, size, factor),
        y=y,
        size=size,
        font=font,
        color=color,
    )


def _field_text(
    commands: list[str],
    value: str,
    *,
    center_x: float,
    y: float,
    maximum: float,
    width: float,
    font: str = "F2",
) -> None:
    size = max(6.0, min(maximum, width / max(1, len(_ascii(value))) / 0.53))
    x = center_x - len(_ascii(value)) * size * 0.53 / 2
    _text(commands, value, x=x, y=y, size=size, font=font, color=NAVY)


def _display_date(value: str) -> str:
    try:
        parsed = date.fromisoformat((value or "")[:10])
        return parsed.strftime("%m/%d/%Y")
    except (TypeError, ValueError):
        return _ascii(value)


def _template_image(credential_name: str) -> tuple[bytes, int, int]:
    filename = (
        "bbu_cert-02.png"
        if "postpartum" in (credential_name or "").lower()
        else "bbu_cert-01.png"
    )
    with Image.open(TEMPLATE_DIR / filename) as source:
        image = source.convert("RGB")
        width, height = image.size
        return zlib.compress(image.tobytes(), 9), width, height


def _qr_commands(url: str, *, x: float, y: float, size: float) -> list[str]:
    matrix = tuple(tuple(row) for row in segno.make(url, error="m").matrix)
    border = 4
    modules = len(matrix) + border * 2
    module_size = size / modules
    commands = [_rgb((1.0, 1.0, 1.0)), f"{x:.2f} {y:.2f} {size:.2f} {size:.2f} re f"]
    commands.append(_rgb(NAVY))
    for row_index, row in enumerate(matrix):
        for column_index, dark in enumerate(row):
            if not dark:
                continue
            left = x + (column_index + border) * module_size
            bottom = y + (len(matrix) - row_index - 1 + border) * module_size
            commands.append(
                f"{left:.2f} {bottom:.2f} {module_size + 0.08:.2f} "
                f"{module_size + 0.08:.2f} re f"
            )
    return commands


def _pdf(objects: list[bytes]) -> bytes:
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_id, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_id} 0 obj\n".encode())
        output.extend(body)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return bytes(output)


def build_credential_certificate_pdf(
    *,
    holder_name: str,
    credential_name: str,
    credential_level: str,
    public_credential_id: str,
    effective_date: str,
    expiration_date: str,
    verification_url: str,
    status: str,
) -> bytes:
    """Render the exact legacy BBU certificate with dynamic verification data."""
    image_data, image_width, image_height = _template_image(credential_name)
    commands = [
        f"q {PAGE_WIDTH} 0 0 {PAGE_HEIGHT} 0 0 cm /BG Do Q",
    ]
    _field_text(
        commands, holder_name, center_x=396, y=329, maximum=29, width=490, font="F3"
    )
    _field_text(
        commands,
        _display_date(effective_date),
        center_x=313,
        y=163,
        maximum=10,
        width=128,
    )
    _field_text(
        commands,
        _display_date(expiration_date),
        center_x=479,
        y=163,
        maximum=10,
        width=128,
    )
    _field_text(
        commands,
        public_credential_id,
        center_x=313,
        y=114,
        maximum=8.5,
        width=145,
    )
    commands.extend(_qr_commands(verification_url, x=628, y=93, size=68))
    _text(
        commands,
        "Scan to verify",
        x=638,
        y=82,
        size=7,
        font="F1",
        color=MUTED,
    )
    if status == "replaced":
        commands.extend(["1 1 1 rg", "110 54 572 24 re f"])
        _centered_text(
            commands,
            "REPLACED - SEE CURRENT CREDENTIAL HISTORY",
            y=61,
            size=9,
            font="F2",
            color=(0.65, 0.09, 0.09),
            factor=0.6,
        )

    content = "\n".join(commands).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 792 612] "
            b"/Resources << /Font << /F1 5 0 R /F2 6 0 R /F3 7 0 R >> "
            b"/XObject << /BG 8 0 R >> >> "
            b"/Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Bold >>",
        (
            f"<< /Type /XObject /Subtype /Image /Width {image_width} "
            f"/Height {image_height} /ColorSpace /DeviceRGB "
            f"/BitsPerComponent 8 /Filter /FlateDecode /Length {len(image_data)} >>\n"
        ).encode()
        + b"stream\n"
        + image_data
        + b"\nendstream",
    ]
    return _pdf(objects)
