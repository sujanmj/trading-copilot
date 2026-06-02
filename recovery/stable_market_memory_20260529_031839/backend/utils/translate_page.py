"""
TRANSLATE PAGE - Helper script for GUI
Fetches a webpage, extracts content, translates to English
"""

import sys
import json
import requests
from pathlib import Path
from bs4 import BeautifulSoup



def fetch_and_translate(url):
    """Fetch URL, extract text, translate to English"""
    try:
        response = requests.get(url, timeout=15, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        if response.status_code != 200:
            return {'success': False, 'error': f'HTTP {response.status_code}'}

        soup = BeautifulSoup(response.content, 'lxml')

        # Remove scripts, styles, navigation
        for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
            tag.decompose()

        # Try multiple content selectors
        content_selectors = [
            'div.innner-page-main-about-us-content-right-part',
            'div#PdfDiv',
            'div.contentMain',
            'div.PressDtlContent',
            'div.detail-content',
            'div.article-body',
            'main',
            'article',
        ]

        body_text = ''
        for selector in content_selectors:
            element = soup.select_one(selector)
            if element:
                body_text = element.get_text(separator=' ', strip=True)
                if len(body_text) > 200:
                    break

        if len(body_text) < 200:
            paragraphs = soup.find_all('p')
            body_text = ' '.join(p.get_text(strip=True) for p in paragraphs)

        body_text = ' '.join(body_text.split())[:6000]

        if not body_text:
            return {'success': False, 'error': 'Could not extract content'}

        # Check if translation is needed
        hindi_chars = sum(1 for c in body_text if '\u0900' <= c <= '\u097F')
        total_chars = len(body_text)

        if hindi_chars / total_chars < 0.1:
            # Already mostly English
            return {
                'success': True,
                'translated': False,
                'text': body_text,
                'message': 'Already in English'
            }

        # Translate using Gemini
        from backend.ai.ai_router import ask_ai

        prompt = f"""Translate this Hindi text to clean, well-formatted English.
Keep all key facts, dates, names, numbers, policy details.
Format as a readable news article with paragraphs.
Highlight important quotes and announcements.

TEXT:
{body_text}

Provide ONLY the English translation. Use proper paragraphs."""

        result = ask_ai(prompt, use_case='translate', max_tokens=3000)

        if result.get('success'):
            return {
                'success': True,
                'translated': True,
                'text': result.get('text', ''),
                'original_length': len(body_text),
                'model_used': result.get('model', '')
            }
        else:
            return {
                'success': False,
                'error': result.get('error', 'Translation failed'),
                'original_text': body_text  # Return original if translation fails
            }

    except Exception as e:
        return {'success': False, 'error': str(e)}


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({'success': False, 'error': 'No URL provided'}))
        sys.exit(1)

    url = sys.argv[1]
    result = fetch_and_translate(url)

    # Output JSON for GUI to parse
    print(json.dumps(result, ensure_ascii=False))