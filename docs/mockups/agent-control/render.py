"""Export the standalone mockups with Chromium. No backend or API key required.

Dependencies: playwright, pillow, and Playwright Chromium (or local Chrome).
Run from any directory: python docs/mockups/agent-control/render.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "exports"
VIEWS = (
    ("workspace", "01-main-workspace", "01   MAIN WORKSPACE", "Conversation, approval, and a persistent cloud computer"),
    ("computer", "02-live-cloud-computer", "02   LIVE CLOUD COMPUTER", "Expanded browser, terminal, and session activity"),
    ("files", "03-files-and-activity", "03   FILES & ACTIVITY", "Published artifacts, previews, and the handoff history"),
)


def font(size: int):
    for name in ("C:/Windows/Fonts/segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    OUTPUT.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception:
            browser = playwright.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, device_scale_factor=2)
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        for view, name, *_ in VIEWS:
            page.goto(f"{(ROOT / 'index.html').as_uri()}?view={view}")
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(OUTPUT / f"{name}.png"), animations="disabled")
            dimensions = page.evaluate("""() => ({
                width: document.documentElement.scrollWidth,
                height: document.documentElement.scrollHeight,
                viewportWidth: innerWidth,
                viewportHeight: innerHeight,
                overflowing: [...document.querySelectorAll('.chat-scroll, .computer-panel, .preview-content')]
                    .filter(el => el.scrollHeight > el.clientHeight + 2)
                    .map(el => ({class: el.className, height: el.clientHeight, content: el.scrollHeight}))
            })""")
            print(f"{name}.png: 3200 x 2000; layout {dimensions}")
        browser.close()
        if failures:
            raise RuntimeError("Browser errors: " + "; ".join(failures))

    sheet = Image.new("RGB", (2464, 664), "#0b0c0f")
    draw = ImageDraw.Draw(sheet)
    draw.text((32, 24), "AGENT CONTROL", font=font(23), fill="#f4f4f5")
    draw.text((32, 60), "Main workspace + Live Cloud Computer / Desktop design study", font=font(15), fill="#a1a1aa")
    for index, (_, filename, title, caption) in enumerate(VIEWS):
        x = 32 + index * 808
        with Image.open(OUTPUT / f"{filename}.png") as image:
            thumbnail = image.convert("RGB").resize((784, 490), Image.Resampling.LANCZOS)
            sheet.paste(thumbnail, (x, 107))
        draw.text((x, 609), title, font=font(13), fill="#00e5ff")
        draw.text((x, 633), caption, font=font(12), fill="#a1a1aa")
    sheet.save(OUTPUT / "00-overview.png")
    print(f"Saved exports to {OUTPUT}")


if __name__ == "__main__":
    main()
