"""Test Feed API endpoint."""
import httpx
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

BASE = 'http://127.0.0.1:8000'
API_KEY = 'sna_fb4fedfc801a37f3a5e587aa7155bc89'
headers = {'X-API-Key': API_KEY}

r = httpx.get(f'{BASE}/api/feed', headers=headers, params={
    'since': '2025-01-01T00:00:00Z'
})
data = r.json()
print(f'Status: {r.status_code}')
print(f'Count: {data["count"]}')
print(f'Total: {data["total"]}')
print(f'Has more: {data["has_more"]}')
print(f'Since: {data["since"]}')
print(f'Until: {data["until"]}')
print(f'Items count: {len(data["items"])}')

if data["items"]:
    print("\nFirst item:")
    item = data["items"][0]
    print(f'  tweet_id: {item["tweet_id"]}')
    print(f'  author: {item["author_username"]}')
    print(f'  created_at: {item["created_at"]}')
    print(f'  text: {item["text"][:100]}...' if len(item.get("text", "")) > 100 else f'  text: {item.get("text", "")}')
    print(f'  has_summary: {item["summary_text"] is not None}')
    print(f'  has_translation: {item["translation_text"] is not None}')
