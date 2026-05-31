import pathlib

brand = pathlib.Path(__file__).parent
icon_svg = (brand / "icon.svg").read_text(encoding="utf-8")
logo_svg = (brand / "logo.svg").read_text(encoding="utf-8")
print(f"icon: {len(icon_svg)} chars")
print(f"logo: {len(logo_svg)} chars")
