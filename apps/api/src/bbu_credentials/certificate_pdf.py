"""Dependency-light PDF renderer for BBU professional credentials."""
from __future__ import annotations

import unicodedata

import segno


PAGE_WIDTH = 792
PAGE_HEIGHT = 612
NAVY = (0.067, 0.239, 0.365)
SKY = (0.427, 0.627, 0.859)
ICE = (0.922, 0.969, 1.0)
INK = (0.105, 0.153, 0.2)
MUTED = (0.42, 0.435, 0.475)


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
    """Render a landscape letter-size, one-page credential certificate."""
    commands = [
        "q",
        _rgb(ICE),
        f"0 0 {PAGE_WIDTH} {PAGE_HEIGHT} re f",
        _rgb(NAVY),
        f"0 0 {PAGE_WIDTH} 14 re f",
        f"0 {PAGE_HEIGHT - 14} {PAGE_WIDTH} 14 re f",
        f"0 0 14 {PAGE_HEIGHT} re f",
        f"{PAGE_WIDTH - 14} 0 14 {PAGE_HEIGHT} re f",
        _rgb(SKY, stroke=True),
        "2 w",
        f"31 31 {PAGE_WIDTH - 62} {PAGE_HEIGHT - 62} re S",
    ]
    _centered_text(
        commands,
        "BIRTH & BABY UNIVERSITY",
        y=545,
        size=12,
        font="F2",
        color=SKY,
        factor=0.6,
    )
    _centered_text(
        commands,
        "Certificate of Professional Credential",
        y=501,
        size=28,
        font="F3",
        color=NAVY,
        factor=0.48,
    )
    _centered_text(
        commands,
        "This certifies that",
        y=446,
        size=13,
        color=MUTED,
    )
    name_size = _fit_font(holder_name, 31, 610, 0.5)
    _centered_text(
        commands,
        holder_name,
        y=398,
        size=name_size,
        font="F3",
        color=INK,
        factor=0.5,
    )
    commands.extend([_rgb(SKY, stroke=True), "1.5 w", "110 386 m 682 386 l S"])
    _centered_text(
        commands,
        "holds the Birth & Baby University credential",
        y=350,
        size=14,
        color=MUTED,
    )
    credential_size = _fit_font(credential_name, 25, 610, 0.5)
    _centered_text(
        commands,
        credential_name,
        y=307,
        size=credential_size,
        font="F3",
        color=NAVY,
        factor=0.5,
    )
    _centered_text(
        commands,
        credential_level.upper(),
        y=274,
        size=11,
        font="F2",
        color=SKY,
        factor=0.6,
    )

    _text(
        commands,
        f"Effective: {effective_date}",
        x=68,
        y=166,
        size=11,
        font="F2",
        color=MUTED,
    )
    _text(
        commands,
        f"Valid through: {expiration_date}",
        x=68,
        y=144,
        size=11,
        font="F2",
        color=MUTED,
    )
    _text(
        commands,
        f"Credential ID: {public_credential_id}",
        x=68,
        y=122,
        size=10,
        font="F2",
        color=MUTED,
    )
    commands.extend(_qr_commands(verification_url, x=351, y=91, size=90))
    _text(
        commands,
        "Scan to verify",
        x=365,
        y=76,
        size=8,
        font="F1",
        color=MUTED,
    )
    _text(
        commands,
        "Anna Rodney",
        x=620,
        y=142,
        size=17,
        font="F3",
        color=NAVY,
    )
    commands.extend([_rgb(MUTED, stroke=True), "0.75 w", "592 130 m 735 130 l S"])
    _text(
        commands,
        "Birth & Baby University",
        x=606,
        y=113,
        size=8,
        color=MUTED,
    )
    if status == "replaced":
        commands.extend(["0.76 0.10 0.10 rg", "0.15 0.15 0.15 RG"])
        _centered_text(
            commands,
            "REPLACED - SEE CURRENT CREDENTIAL HISTORY",
            y=52,
            size=10,
            font="F2",
            color=(0.65, 0.09, 0.09),
            factor=0.6,
        )
    commands.append("Q")

    content = "\n".join(commands).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 792 612] "
            b"/Resources << /Font << /F1 5 0 R /F2 6 0 R /F3 7 0 R >> >> "
            b"/Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Bold >>",
    ]
    return _pdf(objects)
