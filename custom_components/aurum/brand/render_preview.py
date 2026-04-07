import pathlib, json

brand = pathlib.Path(r"C:\Users\cmueller.LEVICRON\Documents\M_HA\Aurum\custom_components\aurum\brand")
icon_svg = (brand / "icon.svg").read_text(encoding="utf-8")
logo_svg = (brand / "logo.svg").read_text(encoding="utf-8")
print(f"icon: {len(icon_svg)} chars")
print(f"logo: {len(logo_svg)} chars")
