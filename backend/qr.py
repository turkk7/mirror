"""توليد رمز QR كـ SVG (بلا اعتماد على مكتبات صور) لعرضه بجودة عالية."""

import qrcode


def make_qr_svg(
    data: str,
    box: int = 10,
    fg: str = "#201b18",
    bg: str = "#f6f4ef",
) -> str:
    """يبني SVG لرمز QR. المصفوفة تتضمّن الهامش (quiet zone)."""
    qr = qrcode.QRCode(
        border=3,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
    )
    qr.add_data(data)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    n = len(matrix)
    size = n * box

    rects = []
    for y, row in enumerate(matrix):
        for x, filled in enumerate(row):
            if filled:
                rects.append(
                    f'<rect x="{x * box}" y="{y * box}" '
                    f'width="{box}" height="{box}"/>'
                )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}" shape-rendering="crispEdges">'
        f'<rect width="{size}" height="{size}" fill="{bg}"/>'
        f'<g fill="{fg}">{"".join(rects)}</g></svg>'
    )
