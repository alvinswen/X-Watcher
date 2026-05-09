$filePath = 'C:\Users\xisun\.claude\projects\C--dailywork-x-watcher\1cf221fb-832d-4778-bd90-8daf58d8f1ae\tool-results\mcp-x-watcher-get_topic_tweets_for_summary-1778075595456.txt'
$content = Get-Content $filePath -Raw -Encoding UTF8
$outer = $content | ConvertFrom-Json
$inner = $outer.result | ConvertFrom-Json
$data = $inner.data
$prompt = $data.default_prompt

# segment 8: chars 56000 to end
$remaining = $prompt.Length - 56000
Write-Host "Remaining chars: $remaining"
Write-Host "=== SEG8 ==="
Write-Host $prompt.Substring(56000, $remaining)
Write-Host "=== SEG8_END ==="
