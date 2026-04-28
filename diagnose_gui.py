import asyncio
from playwright.async_api import async_playwright

async def run_diagnostics():
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        print("--- Starting GUI Diagnostics ---")
        
        # 1. Capture console logs
        page.on("console", lambda msg: print(f"BROWSER CONSOLE: [{msg.type}] {msg.text}"))
        
        # 2. Capture network requests
        page.on("request", lambda request: print(f"NETWORK REQ: {request.method} {request.url}"))
        page.on("response", lambda response: print(f"NETWORK RES: {response.status} {response.url}"))

        try:
            # 3. Navigate to app
            print("Navigating to http://localhost:8002...")
            await page.goto("http://localhost:8002")

            # 4. Login
            print("Attempting login...")
            await page.fill("#username", "admin")
            await page.fill("#password", "password")
            await page.click("button:has-text('Login')")

            # Wait for main view
            await page.wait_for_selector("#main-view:not(.hidden)", timeout=5000)
            print("Login successful.")

            # 5. Click Scan Button
            print("Clicking 'Scan for VMs' button...")
            await page.click("button:has-text('Scan for VMs')")

            # 6. Wait for results or error
            print("Waiting 10 seconds for results...")
            await asyncio.sleep(10)

            # Check if scan results are visible
            is_visible = await page.is_visible("#scan-results:not(.hidden)")
            if is_visible:
                print("SUCCESS: Scan results are visible in GUI.")
                content = await page.inner_text("#discovered-list")
                print(f"Discovered content: {content}")
            else:
                print("FAILURE: Scan results are NOT visible.")

        except Exception as e:
            print(f"DIAGNOSTIC ERROR: {str(e)}")
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(run_diagnostics())
