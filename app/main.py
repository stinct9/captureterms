import asyncio
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, Page, Download

WELLS_URL = "https://apply.wellsfargo.com/getting_started?FPID=7086BAI6000000&applicationtype=businesscreditcard&product_code=BD&subproduct_code=BCMC&cx_nm=CXNAME_CSMPD_CG&sub_channel=WEB&vendor_code=WF&linkloc=fnbcmc&lang=en&refdmn=www_wellsfargo_com"


def ensure_output_dir() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path("outputs") / timestamp
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "screenshots").mkdir(parents=True, exist_ok=True)
    (out_dir / "downloads").mkdir(parents=True, exist_ok=True)
    return out_dir


async def safe_click(page: Page, selector: str, *, timeout_ms: int = 15000, click_delay_ms: int = 50) -> None:
    await page.wait_for_selector(selector, state="visible", timeout=timeout_ms)
    await page.locator(selector).click(delay=click_delay_ms)


async def wait_and_screenshot(page: Page, out_dir: Path, name: str) -> None:
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        try:
            await page.wait_for_load_state("load", timeout=20000)
        except Exception:
            await page.wait_for_timeout(1000)
    path = out_dir / "screenshots" / f"{int(time.time()*1000)}-{name}.png"
    await page.screenshot(path=str(path), full_page=True)


async def capture_pdf_from_print(page: Page, out_dir: Path, name: str) -> Optional[Path]:
    # The site likely opens a new window for print preview. We'll listen for new pages and downloads.
    downloads: list[Download] = []

    def on_download(download: Download) -> None:
        downloads.append(download)

    page.context.on("download", on_download)

    try:
        # Try standard print with Chromium's printToPDF if allowed
        context = page.context
        browser_name = context.browser.browser_type.name if context.browser else "unknown"
        if browser_name == "chromium":
            # Attempt to trigger native window.print() if available on page
            # Some pages block, but we try and then use PDF generation via new_page.pdf() if route is different
            try:
                await page.emulate_media(media="print")
                pdf_path = out_dir / "downloads" / f"{name}.pdf"
                # Use Playwright's page.pdf only for Chromium
                await page.pdf(path=str(pdf_path), format="A4", print_background=True)
                return pdf_path
            except Exception:
                pass

        # Fallback: wait for any download triggered
        if downloads:
            d = downloads[-1]
            save_path = out_dir / "downloads" / f"{name}.pdf"
            await d.save_as(str(save_path))
            return save_path

        return None
    finally:
        try:
            page.context.remove_listener("download", on_download)
        except Exception:
            pass


async def run() -> None:
    out_dir = ensure_output_dir()

    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = await browser.new_context(accept_downloads=True, viewport={"width": 1400, "height": 900})
        page: Page = await context.new_page()

        # Step 1: Navigate to URL
        await page.goto(WELLS_URL, wait_until="domcontentloaded")
        # Try to accept cookies or close banners if present
        try:
            for text in ["Accept", "Agree", "I agree", "Got it", "Close", "OK"]:
                loc = page.get_by_role("button", name=text)
                if await loc.count() > 0 and await loc.first.is_visible():
                    await loc.first.click()
                    break
        except Exception:
            pass
        await wait_and_screenshot(page, out_dir, "landing")

        # Step 2: Click Yes for customer
        # Try multiple selectors defensively since markup may vary
        yes_selectors = [
            "button:has-text('Yes')",
            "[data-automation='are-you-customer-yes']",
            "input[type='radio'][value='yes']",
            "role=button[name='Yes']",
        ]
        clicked_yes = False
        for sel in yes_selectors:
            try:
                if await page.locator(sel).first.is_visible():
                    await page.locator(sel).first.click()
                    clicked_yes = True
                    break
            except Exception:
                continue
        if not clicked_yes:
            # Try label based
            labels = page.locator("label").filter(has_text="Yes")
            if await labels.first.count() > 0:
                try:
                    await labels.first.click()
                    clicked_yes = True
                except Exception:
                    pass
        # Some pages require scrolling into view before click registers
        if not clicked_yes:
            try:
                await page.get_by_text("Yes", exact=False).first.scroll_into_view_if_needed()
                await page.get_by_text("Yes", exact=False).first.click()
                clicked_yes = True
            except Exception:
                pass
        await wait_and_screenshot(page, out_dir, "after-yes")

        # Step 3: Click Continue without signing on
        continue_selectors = [
            "button:has-text('Continue without signing on')",
            "a:has-text('Continue without signing on')",
            "role=button[name='Continue without signing on']",
            "[data-automation='continue-without-signing-on']",
        ]
        clicked_continue = False
        for sel in continue_selectors:
            try:
                if await page.locator(sel).first.is_visible():
                    await page.locator(sel).first.click()
                    clicked_continue = True
                    break
            except Exception:
                continue
        if not clicked_continue:
            # fallback: find partial text
            try:
                await page.get_by_text("Continue without signing on", exact=False).first.scroll_into_view_if_needed()
                await page.get_by_text("Continue without signing on", exact=False).first.click()
                clicked_continue = True
            except Exception:
                pass
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        await wait_and_screenshot(page, out_dir, "after-continue")

        # Step 4: Scroll to Important Disclosures / Terms and Conditions
        # Try common anchors
        targets = [
            "text=Important Disclosures",
            "text=Terms and Conditions",
            "text=Terms & Conditions",
            "text=Disclosures",
            "role=heading[name*='Disclosure']",
        ]
        found_disclosure = False
        for t in targets:
            loc = page.locator(t).first
            try:
                if await loc.count() > 0 and await loc.is_visible():
                    await loc.scroll_into_view_if_needed()
                    found_disclosure = True
                    break
            except Exception:
                continue
        if not found_disclosure:
            # Try scrolling gradually to find "Important Disclosures"
            for _ in range(10):
                try:
                    if await page.get_by_text("Important Disclosures", exact=False).count() > 0:
                        await page.get_by_text("Important Disclosures", exact=False).first.scroll_into_view_if_needed()
                        found_disclosure = True
                        break
                except Exception:
                    pass
                await page.mouse.wheel(0, 1200)
                await page.wait_for_timeout(500)

        await wait_and_screenshot(page, out_dir, "disclosures-visible")

        # Step 5: Click Print button in that section
        print_selectors = [
            "button:has-text('Print')",
            "a:has-text('Print')",
            "role=button[name='Print']",
            "[aria-label='Print']",
        ]
        clicked_print = False
        for sel in print_selectors:
            try:
                if await page.locator(sel).first.is_visible():
                    # Ensure in view
                    await page.locator(sel).first.scroll_into_view_if_needed()
                    await page.locator(sel).first.click()
                    clicked_print = True
                    break
            except Exception:
                continue
        await wait_and_screenshot(page, out_dir, "after-print-click")

        # Attempt to capture PDF
        pdf_path = await capture_pdf_from_print(page, out_dir, "important-disclosures")

        # Final full page screenshot
        await wait_and_screenshot(page, out_dir, "final")

        # Close
        await context.close()
        await browser.close()

        print(f"Artifacts saved to: {out_dir}")
        if pdf_path:
            print(f"Saved PDF: {pdf_path}")
        else:
            print("No PDF file captured via print; see screenshots for details.")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        sys.exit(130)