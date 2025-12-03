import logging
import tempfile
import threading
from pathlib import Path

from browser.automation import sync_playwright  # pylint: disable=import-error
from browser.browser_executable_manager import (  # pylint: disable=import-error
    BrowserManager,
)

logger = logging.getLogger(__name__)
browser_manager = BrowserManager()


def create_resume_output_dir() -> Path:
    """Create output directory for resume PDFs."""
    from constants import RESUME_DIR  # noqa: E402

    output_dir = Path(RESUME_DIR)
    output_dir.mkdir(exist_ok=True)
    return output_dir


def _generate_pdf_sync(
    html_content: str,
    output_dir: Path,
    filename: str,
    margin: dict,
    page_ranges: str = None,
) -> Path:
    """Internal sync function to generate PDF using Playwright."""
    # Ensure filename has .pdf extension
    if not filename.endswith(".pdf"):
        filename = f"{filename}.pdf"

    pdf_path = output_dir / filename

    # Create temporary HTML file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as temp_html:
        temp_html.write(html_content)
        temp_html_path = Path(temp_html.name)

    try:
        # Try to use Chrome first (if installed), otherwise fall back to bundled Chromium
        chrome_path = browser_manager.get_chrome_executable_path()
        import os

        if chrome_path and os.path.exists(chrome_path):
            # Use Chrome if available (no download needed)
            executable_path = chrome_path
            logger.info(f"Using Chrome for PDF generation: {executable_path}")
        else:
            # Fall back to bundled Chromium (will download if needed)
            logger.info("Chrome not found, using bundled Chromium for PDF generation")
            executable_path = browser_manager.prepare_browser_executable_path()
            if not executable_path:
                raise RuntimeError("Failed to prepare browser for PDF generation")
            logger.info(f"Using bundled Chromium: {executable_path}")

        # Generate PDF using Playwright
        with sync_playwright() as p:
            # Launch with explicit executable path
            browser = p.chromium.launch(headless=True, executable_path=executable_path)
            context = browser.new_context()
            page = context.new_page()

            # Load HTML file
            file_url = temp_html_path.resolve().as_uri()
            page.goto(file_url)

            # Wait for page to load completely
            page.wait_for_load_state("networkidle")

            # Generate PDF with proper formatting
            pdf_options = {
                "path": str(pdf_path),
                "print_background": True,
                "format": "A4",
                "margin": margin,
                "prefer_css_page_size": True,
            }

            # Only add page_ranges if specified (for single page exports)
            if page_ranges:
                pdf_options["page_ranges"] = page_ranges

            page.pdf(**pdf_options)

            browser.close()

        logger.info(f"PDF generated successfully: {pdf_path}")
        return pdf_path

    finally:
        # Clean up temporary HTML file
        try:
            temp_html_path.unlink()
        except Exception as e:
            logger.warning(f"Failed to clean up temp HTML file: {e}")


def generate_pdf_from_html(
    html_content: str,
    output_dir: Path,
    filename: str = "resume",
    margin: dict = {
        "top": "0.2in",
        "right": "0.2in",
        "bottom": "0.2in",
        "left": "0.2in",
    },
    page_ranges: str = None,
) -> Path:
    """
    Generate PDF from HTML content using Playwright.  # noqa: E402

    This function runs Playwright in a separate thread to avoid conflicts
    with asyncio event loops.

    Args:
        html_content: The HTML content to convert
        output_dir: Directory to save the PDF
        filename: Base filename (without extension)
        margin: PDF margins
        page_ranges: Page ranges to export (e.g., "1" for first page only)

    Returns:
        Path to the generated PDF file
    """
    try:
        # Use a thread to run the sync Playwright code
        # This avoids the "Playwright Sync API inside asyncio loop" error
        result = [None]  # Use list to store result from thread  # noqa: E402
        exception = [None]  # Use list to store exception from thread  # noqa: E402

        def run_in_thread():
            try:
                result[0] = _generate_pdf_sync(
                    html_content, output_dir, filename, margin, page_ranges
                )
            except Exception as e:
                exception[0] = e

        thread = threading.Thread(target=run_in_thread)
        thread.start()
        thread.join()  # Wait for thread to complete

        err = exception[0]
        if err is not None:
            raise err

        return result[0]

    except Exception as e:
        logger.error(f"Failed to generate PDF: {e}")
        raise


async def generate_pdf_from_html_async(
    html_content: str,
    output_dir: Path,
    filename: str = "resume",
    margin: dict = {
        "top": "0.2in",
        "right": "0.2in",
        "bottom": "0.2in",
        "left": "0.2in",
    },
    page_ranges: str = None,
) -> Path:
    """
    Async version of PDF generation.

    Args:
        html_content: The HTML content to convert
        output_dir: Directory to save the PDF
        filename: Base filename (without extension)
        margin: PDF margins

    Returns:
        Path to the generated PDF file
    """
    import asyncio  # noqa: E402

    # Run the sync version in a thread pool
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        generate_pdf_from_html,
        html_content,
        output_dir,
        filename,
        margin,
        page_ranges,
    )
