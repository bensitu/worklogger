"""Small encoded media fixtures without an additional imaging dependency."""

import base64


def animated_background_bytes():
    # Two lossless 1280-by-720 WebP frames with an 80 ms delay and infinite looping.
    return base64.b64decode(
        "UklGRogAAABXRUJQVlA4WAoAAAACAAAA/wQAzwIAQU5JTQYAAAAAAAAAAABBTk1GKgAAAAAA"
        "AAAAAP8EAM8CAFAAAAJWUDhMEQAAAC//xLMAB9Choteu/4GI6H8AAEFOTUYqAAAAAAAAAAAA"
        "/wQAzwIAUAAAAFZQOEwRAAAAL//EswAH0NraNLT/gYjofwAA"
    )
