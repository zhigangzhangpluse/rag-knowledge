"""使用本机 Edge 验收真实网页和学习手册；需额外安装 playwright。"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def main():
    kb = json.loads(Path('reports/sample-kb.json').read_text(encoding='utf-8'))['kb_id']
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width':1440,'height':1000})
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto('http://127.0.0.1:8000')
        expect(page.locator('#mode')).to_contain_text('真实服务模式')
        page.locator('#kb').select_option(kb)
        expect(page.locator('#documents')).to_contain_text('可问答', timeout=30000)
        page.locator('#question').fill('正式员工每年有几天年假？')
        page.locator('#send').click()
        expect(page.locator('#status')).to_contain_text('完成', timeout=180000)
        expect(page.locator('#messages')).to_contain_text('5')
        citation = page.locator('#messages details').first
        citation.locator('summary').click()
        expect(citation).to_contain_text('正式员工每年享有 5 天带薪年假')
        page.screenshot(path='reports/real-browser.png', full_page=True)
        page.goto('http://127.0.0.1:8000/learn')
        page.locator('nav a[href="#daily-operation"]').click()
        expect(page.locator('#daily-operation')).to_be_in_viewport()
        page.screenshot(path='reports/guide-daily.png')
        page.locator('#search').fill('compose.yaml')
        page.locator('nav .files a:visible').first.click()
        section = page.locator('section').filter(has=page.locator('h2', has_text='compose.yaml')).first
        section.locator('summary').click()
        expect(section.locator('.source')).to_be_visible()
        page.screenshot(path='reports/guide-compose.png')
        assert not errors, errors
        Path('reports/browser-verification.json').write_text(json.dumps({'status':'passed','browser':'local Edge headless','checks':['production mode','sample documents','real chat SSE rendered','citation expanded','daily chapter navigation','file search','line table expanded'],'page_errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
        browser.close()


if __name__ == '__main__':
    main()
