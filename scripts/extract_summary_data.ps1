$filePath = 'C:\Users\xisun\.claude\projects\C--dailywork-x-watcher\1cf221fb-832d-4778-bd90-8daf58d8f1ae\tool-results\mcp-x-watcher-get_topic_tweets_for_summary-1778075595456.txt'
$content = Get-Content $filePath -Raw -Encoding UTF8
$outer = $content | ConvertFrom-Json
$inner = $outer.result | ConvertFrom-Json
$data = $inner.data

$prompt = $data.default_prompt
Write-Host "Prompt total length: $($prompt.Length)"

# 输出 prompt 的各段（每段 8000 字符）
$segSize = 8000
$totalSegs = [Math]::Ceiling($prompt.Length / $segSize)
Write-Host "Total segments: $totalSegs"

# 段 1
$start = 0
$len = [Math]::Min($segSize, $prompt.Length - $start)
Write-Host "=== SEG1 START ==="
Write-Host $prompt.Substring($start, $len)
Write-Host "=== SEG1 END ==="
